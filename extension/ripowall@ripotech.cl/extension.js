// RipoWall — extensión de GNOME Shell (prototipo fase 0).
// Pone como fondo de cada monitor la ventana del reproductor de RipoWall (ripowall-renderer):
//   1. lanza el reproductor como cliente Wayland privilegiado (Meta.WaylandClient): solo sus ventanas
//      cuentan como fondo, ninguna otra app puede hacerse pasar por él;
//   2. mantiene esas ventanas minimizadas y fuera de Alt+Tab, la vista de actividades y la lista de apps;
//   3. dentro del fondo de GNOME de cada monitor mete un clon en vivo (Clutter.Clone) de la ventana de
//      ese monitor. La escala y los monitores los maneja GNOME: nada de XWayland.
// Técnica estudiada de Hanabi (jeffshee/gnome-ext-hanabi, GPL-3.0); código propio.
// SPDX-License-Identifier: GPL-3.0-or-later

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Workspace from 'resource:///org/gnome/shell/ui/workspace.js';
import * as WorkspaceThumbnail from 'resource:///org/gnome/shell/ui/workspaceThumbnail.js';

// Las ventanas del reproductor se titulan «@ripowall!<conector>» (solo informativo: se reconocen por dueño)
const REINTENTO_RENDERER_MS = 2000;  // si el reproductor se cae, se relanza
const BUSCAR_VENTANA_MS = 500;       // el fondo espera a que aparezca la ventana de su monitor

const log = (msg) => console.log(`[ripowall] ${msg}`);

/** Ruta del reproductor: el instalado por RipoWall (~/.local/bin o /usr/bin). */
function rutaRenderer() {
    const cands = [
        GLib.getenv('RIPOWALL_RENDERER'),
        GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'ripowall-renderer']),
        '/usr/bin/ripowall-renderer',
    ];
    return cands.find(p => p && GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE)) ?? null;
}

/** El reproductor, lanzado como cliente Wayland propio de GNOME Shell. */
class Renderer {
    constructor() {
        this._client = null;
        this._proc = null;
        this._cancel = null;
        this._reintentoId = 0;
        this._detenido = true;
    }

    iniciar() {
        this._detenido = false;
        const ruta = rutaRenderer();
        if (!ruta) {
            log('no se encontró ripowall-renderer (~/.local/bin o /usr/bin): sin fondo animado');
            return;
        }
        const launcher = new Gio.SubprocessLauncher({
            flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE,
        });
        this._client = Meta.WaylandClient.new_subprocess(global.context, launcher, [ruta]);
        this._proc = this._client.get_subprocess();
        this._cancel = new Gio.Cancellable();
        log(`reproductor iniciado: ${ruta} (pid ${this._proc.get_identifier()})`);
        this._leerSalida(Gio.DataInputStream.new(this._proc.get_stdout_pipe()));
        this._proc.wait_async(this._cancel, () => {
            this._client = null;
            if (this._detenido)
                return;
            log(`el reproductor terminó (código ${this._proc.get_exit_status()}); se relanza en ${REINTENTO_RENDERER_MS} ms`);
            this._reintentoId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, REINTENTO_RENDERER_MS, () => {
                this._reintentoId = 0;
                this.iniciar();
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _leerSalida(stream) {
        stream.read_line_async(GLib.PRIORITY_DEFAULT, this._cancel, (s, res) => {
            try {
                const [linea] = s.read_line_finish_utf8(res);
                if (linea === null)
                    return;
                log(`reproductor: ${linea}`);
            } catch (e) {
                if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    log(`error leyendo al reproductor: ${e.message}`);
                return;
            }
            this._leerSalida(stream);
        });
    }

    /** ¿Esta ventana es del reproductor? (por dueño Wayland, no por título: no se puede falsificar) */
    esSuya(window) {
        try {
            return !!this._client && this._client.owns_window(window);
        } catch {
            return false;
        }
    }

    detener() {
        this._detenido = true;
        if (this._reintentoId) {
            GLib.source_remove(this._reintentoId);
            this._reintentoId = 0;
        }
        this._cancel?.cancel();
        this._proc?.force_exit();
        this._client = null;
        this._proc = null;
    }
}

/**
 * Mantiene una ventana del reproductor minimizada (la vemos solo a través del clon).
 * Se minimiza recién después de mostrarse la primera vez: si se minimiza antes, nunca recibe su tamaño
 * ni dibuja su primer cuadro (queda en 0x0 y el clon no muestra nada).
 */
class VentanaReproductor {
    constructor(window) {
        this.window = window;
        this._mostrada = false;
        this._ids = [
            window.connect_after('shown', () => {
                this._mostrada = true;
                this._minimizar();
            }),
            window.connect('notify::minimized', () => this._minimizar()),
        ];
    }

    _minimizar() {
        if (this._mostrada && !this.window.minimized)
            this.window.minimize();
    }

    soltar() {
        this._ids.forEach(id => this.window.disconnect(id));
        this._ids = [];
    }
}

/**
 * Detecta qué monitores tapa una ventana maximizada o a pantalla completa (del escritorio activo) y se
 * lo avisa al reproductor (acción «cubierto»), que pausa ese monitor si el usuario lo pidió.
 * Desde GNOME Shell se ven todas las ventanas (Wayland y X11), no solo las X11 como veía Hidamari.
 */
class Cobertura {
    /** listo(): ¿el reproductor ya tiene su ventana? Antes de eso no hay a quién avisarle. */
    constructor(esRenderer, listo) {
        this._esRenderer = esRenderer;
        this._listo = listo;
        this._enviado = new Map();      // "x,y" -> último estado mandado
        this._senales = new Map();      // ventana -> ids
        this._pendiente = 0;
        this._ids = [
            [global.display, global.display.connect('window-created', (_d, w) => this._seguir(w))],
            [global.display, global.display.connect('window-entered-monitor', () => this.programar())],
            [global.workspace_manager, global.workspace_manager.connect('active-workspace-changed', () => this.programar())],
        ];
        global.get_window_actors().forEach(a => this._seguir(a.meta_window));
        this.programar();
    }

    _seguir(w) {
        if (!w || this._senales.has(w))
            return;
        this._senales.set(w, ['size-changed', 'notify::fullscreen', 'notify::minimized', 'workspace-changed']
            .map(s => w.connect(s, () => this.programar()))
            .concat(w.connect('unmanaged', () => {
                this._senales.get(w)?.forEach(id => w.disconnect(id));
                this._senales.delete(w);
                this.programar();
            })));
        this.programar();
    }

    /** Recalcula una sola vez por ráfaga de cambios. */
    programar() {
        if (this._pendiente)
            return;
        this._pendiente = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._pendiente = 0;
            this._calcular();
            return GLib.SOURCE_REMOVE;
        });
    }

    /** El reproductor (re)arrancó: mandarle de nuevo todos los estados. */
    olvidar() {
        this._enviado.clear();
        this.programar();
    }

    _calcular() {
        if (!this._listo())
            return;  // se recalcula con olvidar() cuando aparece la ventana del reproductor
        const ws = global.workspace_manager.get_active_workspace();
        const tapa = w => !this._esRenderer(w) && !w.minimized && w.located_on_workspace(ws) &&
            (w.is_fullscreen() || (w.is_maximized ? w.is_maximized() : w.get_maximized() === Meta.MaximizeFlags.BOTH));
        const ventanas = [...this._senales.keys()].filter(tapa);
        for (let i = 0; i < global.display.get_n_monitors(); i++) {
            const g = global.display.get_monitor_geometry(i);
            const tapado = ventanas.some(w => w.get_monitor() === i);
            const clave = `${g.x},${g.y}`;
            if (this._enviado.get(clave) === tapado)
                continue;
            this._enviado.set(clave, tapado);
            Gio.DBus.session.call(
                'cl.ripotech.RipoWall.Renderer', '/cl/ripotech/RipoWall/Renderer', 'org.gtk.Actions', 'Activate',
                new GLib.Variant('(sava{sv})', ['cubierto', [new GLib.Variant('(iib)', [g.x, g.y, tapado])], {}]),
                null, Gio.DBusCallFlags.NONE, -1, null,
                (con, res) => {
                    try {
                        con.call_finish(res);
                    } catch (e) {
                        this._enviado.delete(clave);  // el reproductor aún no está: se reintenta al arrancar
                        log(`no se pudo avisar «cubierto» al reproductor: ${e.message}`);
                    }
                });
        }
    }

    destruir() {
        if (this._pendiente)
            GLib.source_remove(this._pendiente);
        this._ids.forEach(([obj, id]) => obj.disconnect(id));
        this._senales.forEach((ids, w) => ids.forEach(id => w.disconnect(id)));
        this._senales.clear();
    }
}

export default class RipoWallExtension extends Extension {
    enable() {
        this._renderer = new Renderer();
        this._ventanas = new Map();
        this._fondos = new Set();
        this._inyecciones = new InjectionManager();
        this._todasLasVentanas = () => global.get_window_actors();

        const ext = this;
        const esRenderer = w => !!w && (ext._renderer.esSuya(w) || ext._ventanas.has(w));

        // 1) Fondo: en cada fondo de monitor, un clon en vivo de la ventana del reproductor de ese monitor
        this._inyecciones.overrideMethod(Background.BackgroundManager.prototype, '_createBackgroundActor',
            original => function () {
                const fondo = original.call(this);
                const contenedor = this._container;
                if (contenedor?.style_class?.includes('screen-shield-background'))
                    return fondo;  // pantalla de bloqueo: fondo normal (prototipo)
                ext._ponerClon(fondo);
                return fondo;
            });

        // 2) Las ventanas del reproductor no existen para el resto de GNOME
        this._inyecciones.overrideMethod(Shell.Global.prototype, 'get_window_actors', original => {
            ext._todasLasVentanas = () => original.call(global);
            return function () {
                return original.call(this).filter(a => !esRenderer(a.meta_window));
            };
        });
        for (const proto of [Workspace.Workspace.prototype, WorkspaceThumbnail.WorkspaceThumbnail.prototype]) {
            this._inyecciones.overrideMethod(proto, '_isOverviewWindow', original => function (window) {
                return esRenderer(window) ? false : original.call(this, window);
            });
        }
        this._inyecciones.overrideMethod(Meta.Display.prototype, 'get_tab_list', original =>
            function (type, workspace) {
                return original.call(this, type, workspace).filter(w => !esRenderer(w));
            });
        // Sin aviso «la ventana está lista» (GNOME lo muestra cuando una ventana nueva pide atención)
        this._inyecciones.overrideMethod(Main.windowAttentionHandler, '_onWindowDemandsAttention', original =>
            function (display, window) {
                return esRenderer(window) ? undefined : original.call(this, display, window);
            });
        this._inyecciones.overrideMethod(Shell.App.prototype, 'get_windows', original => function () {
            return original.call(this).filter(w => !esRenderer(w));
        });

        // 3) Cada ventana nueva del reproductor: minimizada y registrada
        this._ventanaCreadaId = global.display.connect('window-created', (_d, window) => {
            if (!this._renderer.esSuya(window))
                return;
            this._ventanas.set(window, new VentanaReproductor(window));
            window.connect('unmanaged', () => {
                this._ventanas.get(window)?.soltar();
                this._ventanas.delete(window);
            });
            log(`ventana del reproductor: «${window.title}» en el monitor ${window.get_monitor()}`);
            this._cobertura?.olvidar();  // reproductor nuevo o reiniciado: reenviar qué monitores están tapados
        });

        this._cobertura = new Cobertura(esRenderer, () => this._ventanas.size > 0);
        this._renderer.iniciar();
        this._recargarFondos();
        this._capturaDePrueba();
        log('extensión activada');
    }

    /** Solo pruebas (GNOME anidado): RIPOWALL_PRUEBA_CAPTURA=<png> guarda la pantalla a los 10 s. */
    _capturaDePrueba() {
        const ruta = GLib.getenv('RIPOWALL_PRUEBA_CAPTURA');
        if (!ruta)
            return;
        this._capturaId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
            this._capturaId = 0;
            const stream = Gio.File.new_for_path(ruta).replace(null, false, Gio.FileCreateFlags.NONE, null);
            new Shell.Screenshot().screenshot(false, stream, (obj, res) => {
                try {
                    obj.screenshot_finish(res);
                    log(`captura de prueba: ${ruta}`);
                } catch (e) {
                    log(`captura de prueba falló: ${e.message}`);
                }
                stream.close(null);
            });
            return GLib.SOURCE_REMOVE;
        });
    }

    disable() {
        if (this._capturaId)
            GLib.source_remove(this._capturaId);
        global.display.disconnect(this._ventanaCreadaId);
        this._cobertura.destruir();
        this._cobertura = null;
        this._inyecciones.clear();
        this._renderer.detener();
        this._ventanas.forEach(v => v.soltar());
        this._ventanas.clear();
        this._recargarFondos();
        this._renderer = null;
        this._ventanas = null;
        this._inyecciones = null;
        log('extensión desactivada');
    }

    /** Agrega al fondo de un monitor el clon de la ventana del reproductor de ese monitor (cuando aparezca). */
    _ponerClon(fondo) {
        const capa = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            x_expand: true,
            y_expand: true,
            width: fondo.width,
            height: fondo.height,
        });
        fondo.layout_manager = new Clutter.BinLayout();
        fondo.add_child(capa);
        this._fondos.add(capa);

        let buscarId = 0;
        let clon = null;
        let capaViva = true;
        const buscar = () => {
            const ventana = this._todasLasVentanas().find(a =>
                this._ventanas?.has(a.meta_window) && a.meta_window.get_monitor() === fondo.monitor);
            if (!ventana)
                return GLib.SOURCE_CONTINUE;
            clon = new Clutter.Clone({source: ventana, x_expand: true, y_expand: true});
            capa.add_child(clon);
            const fuenteId = ventana.connect('destroy', () => {
                clon?.destroy();
                clon = null;
                if (capaViva)
                    buscarId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, BUSCAR_VENTANA_MS, buscar);
            });
            capa.connect('destroy', () => ventana.disconnect(fuenteId));
            log(`fondo del monitor ${fondo.monitor}: clon de «${ventana.meta_window.title}» (${ventana.width}x${ventana.height})`);
            if (GLib.getenv('RIPOWALL_PRUEBA_CAPTURA')) {
                GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 5, () => {
                    if (capaViva)
                        log(`diagnóstico: fondo ${fondo.width}x${fondo.height} capa ${capa.width}x${capa.height} ` +
                            `clon ${clon?.width}x${clon?.height} ventana ${ventana.width}x${ventana.height} ` +
                            `visible=${ventana.visible} mapeada=${ventana.mapped} minimizada=${ventana.meta_window?.minimized}`);
                    return GLib.SOURCE_REMOVE;
                });
            }
            buscarId = 0;
            return GLib.SOURCE_REMOVE;
        };
        capa.connect('destroy', () => {
            capaViva = false;
            if (buscarId)
                GLib.source_remove(buscarId);
            buscarId = 0;
            this._fondos?.delete(capa);
        });
        if (buscar() === GLib.SOURCE_CONTINUE)
            buscarId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, BUSCAR_VENTANA_MS, buscar);
    }

    _recargarFondos() {
        this._fondos?.forEach(c => c.destroy());
        global.compositor.get_laters().add(Meta.LaterType.BEFORE_REDRAW, () => {
            Main.layoutManager._updateBackgrounds();
            return GLib.SOURCE_REMOVE;
        });
    }
}
