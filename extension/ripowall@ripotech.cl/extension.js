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

/**
 * Un programa lanzado como cliente Wayland propio de GNOME Shell (el reproductor o un motor de escenas):
 * solo sus ventanas se reconocen como fondo, ninguna otra app puede hacerse pasar por él.
 */
class ClienteWayland {
    /**
     * @param {string} nombre      para el registro
     * @param {() => string[]|null} argv  se evalúa en cada arranque (null: no se puede lanzar)
     * @param {number} reintentos   cuántas veces se relanza si termina solo (Infinity: siempre)
     */
    constructor(nombre, argv, reintentos = Infinity) {
        this.nombre = nombre;
        this._argv = argv;
        this._reintentos = reintentos;
        this._client = null;
        this._proc = null;
        this._cancel = null;
        this._reintentoId = 0;
        this._detenido = true;
    }

    iniciar() {
        this._detenido = false;
        const argv = this._argv();
        if (!argv) {
            log(`${this.nombre}: no se puede lanzar (programa no encontrado)`);
            return;
        }
        const launcher = new Gio.SubprocessLauncher({
            flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE,
        });
        if (Meta.WaylandClient.new_subprocess) {  // GNOME 49 o más nuevo
            this._client = Meta.WaylandClient.new_subprocess(global.context, launcher, argv);
            this._proc = this._client.get_subprocess();
        } else {  // GNOME 45 a 48: se crea el cliente y después se lanza
            this._client = Meta.WaylandClient.new(global.context, launcher);
            this._proc = this._client.spawnv(global.display, argv);
        }
        this._cancel = new Gio.Cancellable();
        log(`${this.nombre} iniciado: ${argv.join(' ')} (pid ${this._proc.get_identifier()})`);
        this._leerSalida(Gio.DataInputStream.new(this._proc.get_stdout_pipe()));
        const proc = this._proc;
        proc.wait_async(this._cancel, () => {
            if (this._proc !== proc)
                return;
            this._client = null;
            if (this._detenido)
                return;
            if (this._reintentos <= 0) {
                log(`${this.nombre} terminó (código ${proc.get_exit_status()}); no se relanza`);
                return;
            }
            this._reintentos--;
            log(`${this.nombre} terminó (código ${proc.get_exit_status()}); se relanza en ${REINTENTO_RENDERER_MS} ms`);
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
                log(`${this.nombre}: ${linea}`);
            } catch (e) {
                if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                    log(`error leyendo a ${this.nombre}: ${e.message}`);
                return;
            }
            this._leerSalida(stream);
        });
    }

    /** ¿Esta ventana es de este programa? (por dueño Wayland, no por título: no se puede falsificar) */
    esSuya(window) {
        try {
            return !!this._client && this._client.owns_window(window);
        } catch {
            return false;
        }
    }

    /** Pausa (SIGSTOP) o reanuda (SIGCONT) el proceso sin perder su estado. */
    congelar(si) {
        this._proc?.send_signal(si ? 19 : 18);
    }

    detener() {
        this._detenido = true;
        if (this._reintentoId) {
            GLib.source_remove(this._reintentoId);
            this._reintentoId = 0;
        }
        this._cancel?.cancel();
        this._proc?.send_signal(18);  // si estaba congelado, que pueda terminar
        this._proc?.force_exit();
        this._client = null;
        this._proc = null;
    }
}

/**
 * Monitor de una ventana del reproductor, por su título «@ripowall!<conector>». Sin título todavía (o con
 * conector desconocido «?»), -1: mientras tanto no se usa como fondo de ningún monitor, salvo que haya uno solo.
 */
function monitorDelReproductor(window) {
    const titulo = window.get_title() ?? '';
    if (!titulo.startsWith('@ripowall!'))
        return -1;
    const i = global.backend.get_monitor_manager().get_monitor_for_connector(titulo.slice('@ripowall!'.length));
    if (i >= 0)
        return i;
    return global.display.get_n_monitors() === 1 ? 0 : -1;
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

const BUS_RENDERER = 'cl.ripotech.RipoWall.Renderer';
const RUTA_RENDERER = '/cl/ripotech/RipoWall/Renderer';
const ASSETS_WE = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'share', 'Steam', 'steamapps',
    'common', 'wallpaper_engine', 'assets']);

/**
 * Escenas de Wallpaper Engine: el reproductor publica en su acción «escenas» qué escena va en cada monitor
 * ({conector: {carpeta, props, pausado, silencio, volumen}}); aquí se lanza linux-wallpaperengine para
 * cada una, como cliente Wayland propio, y su ventana pasa a ser el fondo de ese monitor.
 */
class Escenas {
    constructor(alCambiar) {
        this._alCambiar = alCambiar;        // hay que rehacer los fondos (apareció o se fue una escena)
        this._motores = new Map();          // conector -> {cliente, clave, pausado, ventana}
        this._cancel = new Gio.Cancellable();  // consultas en curso: se cancelan al desactivar
        this._destruida = false;
        this._sub = Gio.DBus.session.signal_subscribe(BUS_RENDERER, 'org.gtk.Actions', 'Changed', RUTA_RENDERER,
            null, Gio.DBusSignalFlags.NONE, (_c, _s, _p, _i, _sig, params) => {
                const estados = params.deep_unpack()[2];
                if ('escenas' in estados)
                    this._aplicar(estados.escenas.deep_unpack());
            });
    }

    /** Pide al reproductor su lista actual (al arrancar o reiniciarse). */
    consultar() {
        Gio.DBus.session.call(BUS_RENDERER, RUTA_RENDERER, 'org.gtk.Actions', 'Describe',
            new GLib.Variant('(s)', ['escenas']), null, Gio.DBusCallFlags.NONE, -1, this._cancel, (c, res) => {
                try {
                    const [[, , estado]] = c.call_finish(res).deep_unpack();
                    if (estado.length)
                        this._aplicar(estado[0].deep_unpack());
                } catch (e) {
                    if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
                        log(`no se pudo leer las escenas del reproductor: ${e.message}`);
                }
            });
    }

    _aplicar(json) {
        if (this._destruida)  // una respuesta que llega después de desactivar no lanza motores
            return;
        let deseadas;
        try {
            deseadas = JSON.parse(json);
        } catch (e) {
            log(`lista de escenas ilegible: ${e.message}`);
            return;
        }
        for (const [conector, m] of [...this._motores]) {
            if (!(conector in deseadas))
                this._quitar(conector, m);
        }
        for (const [conector, e] of Object.entries(deseadas)) {
            const clave = JSON.stringify([e.carpeta, e.props, e.silencio, e.volumen]);
            const actual = this._motores.get(conector);
            if (!actual || actual.clave !== clave) {
                if (actual)
                    this._quitar(conector, actual);
                this._lanzar(conector, e, clave);
            } else if (actual.pausado !== e.pausado) {
                actual.pausado = e.pausado;
                if (actual.ventana) {  // antes de su primer cuadro no se congela (el clon quedaría vacío)
                    actual.cliente.congelar(e.pausado);
                    log(`escena ${conector}: ${e.pausado ? 'pausada' : 'reanudada'}`);
                }
            }
        }
    }

    _lanzar(conector, e, clave) {
        const geo = global.display.get_monitor_geometry(this._monitor(conector));
        const cliente = new ClienteWayland(`escena ${conector}`, () => {
            // primero el de ~/.local/bin (el motor con los arreglos de RipoWall fuera de Arch, que puede no estar
            // en el PATH de GNOME hasta volver a iniciar sesión), igual que hidamari_core.motor_de_escenas()
            const local = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'linux-wallpaperengine']);
            const motor = GLib.file_test(local, GLib.FileTest.IS_EXECUTABLE)
                ? local : GLib.find_program_in_path('linux-wallpaperengine');
            if (!motor)
                return null;
            // --scaling fill va justo después de --window (se aplica a la salida anterior): las escenas
            // que no son 16:9 se recortan para cubrir la pantalla, como en Wallpaper Engine
            const argv = [motor, '--window', `0x0x${geo.width}x${geo.height}`, '--scaling', 'fill',
                '--disable-mouse', '--fps', '30'];
            if (GLib.file_test(ASSETS_WE, GLib.FileTest.IS_DIR))
                argv.push('--assets-dir', ASSETS_WE);
            argv.push(...(e.silencio ? ['--silent'] : ['--volume', String(e.volumen)]));
            for (const [k, v] of Object.entries(e.props ?? {}))
                argv.push('--set-property', `${k}=${v}`);
            argv.push(e.carpeta);
            return argv;
        }, 1);
        this._motores.set(conector, {cliente, clave, pausado: e.pausado, ventana: null});
        cliente.iniciar();
    }

    _quitar(conector, m) {
        m.cliente.detener();
        this._motores.delete(conector);
        if (m.ventana)
            this._alCambiar();
    }

    /** Índice de monitor de un conector (el monitor virtual de las pruebas no tiene conector: «?»). */
    _monitor(conector) {
        const i = global.backend.get_monitor_manager().get_monitor_for_connector(conector);
        return i >= 0 ? i : 0;
    }

    /** Monitor de la escena que dibuja `window`, o -1 si no es de una escena. */
    monitorDe(window) {
        const conector = this.deQuien(window);
        return conector === null ? -1 : this._monitor(conector);
    }

    /** Si la ventana es de un motor de escenas, su conector; si no, null. */
    deQuien(window) {
        for (const [conector, m] of this._motores) {
            if (m.cliente.esSuya(window))
                return conector;
        }
        return null;
    }

    /**
     * Ventana nueva de un motor: al mostrarse por primera vez se lleva a su monitor y a pantalla completa
     * (antes de eso GNOME ignora el pedido) y pasa a ser el fondo. Hay que llamarla ANTES de crear su
     * VentanaReproductor, para que esto corra antes de minimizarla.
     */
    ventanaNueva(window, conector) {
        const m = this._motores.get(conector);
        const id = window.connect_after('shown', () => {
            window.disconnect(id);
            window.move_to_monitor(this._monitor(conector));
            window.make_fullscreen();
            m.ventana = window;
            if (m.pausado)
                m.cliente.congelar(true);
            this._alCambiar();
        });
    }

    esEscena(window) {
        return [...this._motores.values()].some(m => m.ventana === window);
    }

    destruir() {
        this._destruida = true;
        this._cancel.cancel();
        Gio.DBus.session.signal_unsubscribe(this._sub);
        this._motores.forEach(m => m.cliente.detener());
        this._motores.clear();
    }
}

export default class RipoWallExtension extends Extension {
    enable() {
        // El reproductor y las escenas son clientes Wayland de GNOME Shell: en una sesión X11 (GNOME 45-48
        // todavía la ofrece) no hay cómo mostrarlos. Se avisa en vez de fallar sin decir nada.
        // (GNOME 50 quitó X11 y con él Meta.is_wayland_compositor: si no existe, es Wayland)
        if (Meta.is_wayland_compositor && !Meta.is_wayland_compositor()) {
            this._sinWayland = true;
            log('se necesita una sesión de GNOME en Wayland; esta es X11: RipoWall no hace nada');
            Main.notify('RipoWall', 'Los fondos animados necesitan una sesión de GNOME en Wayland. ' +
                'Cierra sesión y elige «GNOME» (no «GNOME en Xorg») con el engranaje de la pantalla de inicio.');
            return;
        }
        this._renderer = new ClienteWayland('reproductor', () => {
            const ruta = rutaRenderer();
            return ruta ? [ruta] : null;
        });
        this._ventanas = new Map();
        this._fondos = new Set();
        this._inyecciones = new InjectionManager();
        this._todasLasVentanas = () => global.get_window_actors();

        const ext = this;
        this._escenas = new Escenas(() => this._recargarFondos());
        const esRenderer = w => !!w && (ext._renderer.esSuya(w) || ext._ventanas.has(w) || !!ext._escenas?.deQuien(w));

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
        // Las ventanas del reproductor y de las escenas están en pantalla completa (minimizadas), y mutter
        // puede contarlas como «monitor en pantalla completa»: GNOME escondería la barra superior y
        // silenciaría las notificaciones con el escritorio vacío. Solo cuenta una ventana ajena.
        this._inyecciones.overrideMethod(Meta.Display.prototype, 'get_monitor_in_fullscreen', original =>
            function (monitor) {
                return original.call(this, monitor) && this.list_all_windows().some(w =>
                    !esRenderer(w) && w.fullscreen && !w.minimized && w.get_monitor() === monitor);
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
            const conector = this._escenas.deQuien(window);
            if (conector !== null) {
                this._escenas.ventanaNueva(window, conector);  // primero: pantalla completa antes de minimizar
                this._ventanas.set(window, new VentanaReproductor(window));
                window.connect('unmanaged', () => {
                    this._ventanas.get(window)?.soltar();
                    this._ventanas?.delete(window);
                });
                log(`ventana de la escena del monitor ${conector}`);
                return;
            }
            if (!this._renderer.esSuya(window))
                return;
            this._ventanas.set(window, new VentanaReproductor(window));
            window.connect('unmanaged', () => {
                this._ventanas.get(window)?.soltar();
                this._ventanas.delete(window);
            });
            log(`ventana del reproductor: «${window.title}» en el monitor ${window.get_monitor()}`);
            this._cobertura?.olvidar();  // reproductor nuevo o reiniciado: reenviar qué monitores están tapados
            this._escenas.consultar();
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
            if (Main.overview.visible) {  // GNOME arranca en la vista general: la captura es del escritorio
                Main.overview.hide();
                this._capturaId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
                    this._capturaId = 0;
                    this._capturar(ruta);
                    return GLib.SOURCE_REMOVE;
                });
            } else {
                this._capturar(ruta);
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _capturar(ruta) {
        for (const w of global.display.list_all_windows())
            log(`captura: ventana «${w.get_title()}» minimizada=${w.minimized} oculta=${w.is_hidden()} pantalla-completa=${w.fullscreen}`);
        log(`captura: barra visible=${Main.panel.visible} monitor en pantalla completa=` +
            `${Main.layoutManager.primaryMonitor?.inFullscreen} vista general=${Main.overview.visible}`);
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
    }

    disable() {
        if (this._sinWayland) {
            this._sinWayland = false;
            return;
        }
        if (this._capturaId)
            GLib.source_remove(this._capturaId);
        global.display.disconnect(this._ventanaCreadaId);
        this._cobertura.destruir();
        this._cobertura = null;
        this._escenas.destruir();
        this._escenas = null;
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
            const candidatas = this._todasLasVentanas().filter(a => this._ventanas?.has(a.meta_window));
            // Cada ventana se asocia a su monitor por su conector, no por dónde la puso GNOME: al
            // aparecer, todas parten en el monitor 0 hasta que pasan a pantalla completa en el suyo.
            // Si el monitor tiene una escena andando, esa manda; si no, la ventana del reproductor.
            const ventana = candidatas.find(a => this._escenas?.esEscena(a.meta_window) &&
                    this._escenas.monitorDe(a.meta_window) === fondo.monitor) ??
                candidatas.find(a => this._renderer?.esSuya(a.meta_window) &&
                    monitorDelReproductor(a.meta_window) === fondo.monitor);
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
