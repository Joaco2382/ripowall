#!/usr/bin/env python3
"""
ripowall-renderer — reproductor de fondos de RipoWall (reemplaza a Hidamari).

Una ventana GTK4 a pantalla completa por monitor. No se usa solo: lo lanza la extensión de GNOME
(ripowall@ripotech.cl) como cliente Wayland privilegiado, la mantiene minimizada y la muestra como fondo
con un clon en vivo. Según el tipo de fondo asignado al monitor:
  video   GStreamer (Gtk.MediaFile), en bucle
  web     WebKit, con la API de Wallpaper Engine para fondos web (applyUserProperties, setPaused)
  preset  el fondo web/escena original + los ajustes y archivos del preset
  scene   la vista previa como respaldo; la extensión lanza linux-wallpaperengine y lo pone encima
          (la lista de escenas por monitor se publica en la acción «escenas»)

Configuración: ~/.config/ripowall/config.json (la escriben el daemon y la GUI); se recarga sola al
cambiar. Control en vivo por D-Bus (acciones de GApplication, interfaz org.gtk.Actions en
/cl/ripotech/RipoWall/Renderer):
  recargar           relee la configuración
  pausado  (b)       pausa del usuario (estado)
  silencio (b)       sin sonido (estado)
  volumen  (i)       0-100 (estado)
  cubierto (iib)     x, y del monitor y si una ventana maximizada/pantalla completa lo tapa
                     (lo manda la extensión; pausa ese monitor si is_pause_when_maximized)
  escenas  (s)       solo lectura: JSON {conector: {carpeta, props, pausado, silencio, volumen}}
Cada ventana se titula «@ripowall!<conector>». RIPOWALL_VIDEO=<ruta> fuerza un fondo (pruebas).
"""

import json
import os
import re
import sys
import urllib.parse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("WebKit", "6.0")
    gi.require_version("Soup", "3.0")
    from gi.repository import Soup, WebKit  # noqa: E402
except (ImportError, ValueError) as e:  # sin WebKitGTK 6: los fondos web muestran su vista previa
    WebKit = None
    print(f"WebKitGTK 6.0 no disponible ({e}): los fondos web se verán como imagen", flush=True)

APP_ID = "cl.ripotech.RipoWall.Renderer"
MARCA = "@ripowall!"
# RIPOWALL_CONFIG=<ruta> usa otra configuración (pruebas)
CONFIG = os.environ.get("RIPOWALL_CONFIG") or os.path.expanduser("~/.config/ripowall/config.json")

# API de Wallpaper Engine para fondos web: se define antes de que cargue la página. El audio todavía no
# se entrega (los visualizadores quedan quietos en vez de fallar).
API_WE_JS = """
window.wallpaperRegisterAudioListener = window.wallpaperRegisterAudioListener || function (cb) { window.__ripowallAudio = cb; };
window.wallpaperRegisterMediaStatusListener = window.wallpaperRegisterMediaStatusListener || function () {};
window.wallpaperRegisterMediaPropertiesListener = window.wallpaperRegisterMediaPropertiesListener || function () {};
window.wallpaperRegisterMediaThumbnailListener = window.wallpaperRegisterMediaThumbnailListener || function () {};
window.wallpaperRegisterMediaPlaybackListener = window.wallpaperRegisterMediaPlaybackListener || function () {};
window.wallpaperRegisterMediaTimelineListener = window.wallpaperRegisterMediaTimelineListener || function () {};
"""


def log(msg: str) -> None:
    print(msg, flush=True)  # la extensión lo pasa al registro de GNOME Shell (journalctl)


def leer_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log(f"sin configuración en {CONFIG}: fondos vacíos hasta que el daemon asigne")
    except (OSError, json.JSONDecodeError) as e:
        log(f"no se pudo leer {CONFIG}: {e}")
    return {}


def debe_reproducir(pausado: bool, pausa_si_maximizada: bool, cubierto: bool) -> bool:
    """Un monitor reproduce si el usuario no pausó y (no se pausa con ventanas maximizadas o no está tapado)."""
    return not pausado and not (pausa_si_maximizada and cubierto)


def _proyecto(carpeta: str) -> dict:
    try:
        with open(os.path.join(carpeta, "project.json"), encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _preview(carpeta: str, proyecto: dict) -> str | None:
    for nombre in (proyecto.get("preview"), "preview.jpg", "preview.png", "preview.gif"):
        if nombre and os.path.isfile(os.path.join(carpeta, nombre)):
            return os.path.join(carpeta, nombre)
    return None


# Los fondos web se cargan desde ripowall-fondo://<host>/<archivo> en vez de file://: el esquema solo sirve
# archivos de la carpeta del fondo que se está mostrando, así un fondo del Workshop no puede leer otros
# archivos del usuario (por ejemplo la sesión de Steam) con fetch/XHR y mandarlos afuera.
ESQUEMA = "ripowall-fondo"
_RAICES: dict[str, str] = {}   # host -> carpeta real que puede servir


def url_fondo_web(carpeta: str, html: str) -> str:
    """URL con que se carga un fondo web; desde ahí solo se pueden leer los archivos de `carpeta`."""
    host = "w" + re.sub(r"[^a-z0-9]", "", os.path.basename(carpeta.rstrip("/")).lower())
    _RAICES[host] = os.path.realpath(carpeta)
    return f"{ESQUEMA}://{host}/" + urllib.parse.quote(os.path.relpath(html, carpeta))


def archivo_de_url(uri: str) -> str | None:
    """Archivo que sirve el esquema para `uri`, o None si no existe o queda fuera de la carpeta del fondo."""
    partes = urllib.parse.urlsplit(uri)
    raiz = _RAICES.get(partes.hostname or "") if partes.scheme == ESQUEMA else None
    if not raiz:
        return None
    destino = os.path.realpath(os.path.join(raiz, urllib.parse.unquote(partes.path).lstrip("/")))
    if os.path.commonpath([raiz, destino]) != raiz or not os.path.isfile(destino):
        return None
    return destino


def servir_esquema(peticion) -> None:
    """Responde una petición ripowall-fondo:// (WebKit.URISchemeRequest)."""
    archivo = archivo_de_url(peticion.get_uri())
    if not archivo:
        log(f"fondo web: no se sirve {peticion.get_uri()} (no existe o está fuera de la carpeta del fondo)")
        peticion.finish_error(GLib.Error.new_literal(
            Gio.io_error_quark(), "fuera de la carpeta del fondo", Gio.IOErrorEnum.NOT_FOUND))
        return
    try:
        flujo = Gio.File.new_for_path(archivo).read(None)
    except GLib.Error as e:
        log(f"fondo web: no se pudo leer {archivo}: {e.message}")
        peticion.finish_error(e)
        return
    tipo, _ = Gio.content_type_guess(archivo, None)
    respuesta = WebKit.URISchemeResponse.new(flujo, os.path.getsize(archivo))
    respuesta.set_content_type(Gio.content_type_get_mime_type(tipo) or "application/octet-stream")
    # El esquema es «local» (para mostrar las imágenes file:// de un preset), y WebKit da a las páginas
    # locales un origen único: sin este encabezado, el fondo no podría hacer fetch/XHR de sus propios
    # archivos. Lo que se comparte es solo la carpeta pública del fondo.
    encabezados = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
    encabezados.append("Access-Control-Allow-Origin", "*")
    respuesta.set_http_headers(encabezados)
    peticion.finish_with_response(respuesta)


_esquema_registrado = False


def registrar_esquema() -> None:
    """Registra ripowall-fondo:// en WebKit (una vez por proceso)."""
    global _esquema_registrado
    if not WebKit or _esquema_registrado:
        return
    contexto = WebKit.WebContext.get_default()
    contexto.register_uri_scheme(ESQUEMA, servir_esquema)
    # «local»: la página puede mostrar imágenes file:// (los fondos arman 'file:///' + valor con las
    # imágenes elegidas en un preset), pero no leer su contenido con fetch/XHR
    seguridad = contexto.get_security_manager()
    seguridad.register_uri_scheme_as_local(ESQUEMA)
    # fetch/XHR a sus propios archivos (mismo host); el esquema igual solo sirve la carpeta del fondo
    seguridad.register_uri_scheme_as_cors_enabled(ESQUEMA)
    _esquema_registrado = True


def nueva_vista_web(contenido=None):
    """WebView para un fondo web: sin acceso libre a archivos (la página viene de ripowall-fondo://)."""
    registrar_esquema()
    web = WebKit.WebView(user_content_manager=contenido) if contenido else WebKit.WebView()
    ajustes = web.get_settings()
    ajustes.set_enable_developer_extras(False)
    ajustes.set_allow_file_access_from_file_urls(False)
    ajustes.set_allow_universal_access_from_file_urls(False)
    ajustes.set_media_playback_requires_user_gesture(False)
    return web


def resolver_fondo(ruta: str | None) -> dict | None:
    """Qué hay que mostrar para una ruta de config.json.

    Devuelve {tipo, ...} o None si no se puede mostrar:
      video:  archivo
      web:    carpeta, html, props ({nombre: {"value": v}}), preview
      scene:  carpeta, props ({nombre: valor} para --set-property), preview
    Un preset se resuelve al tipo de su original, con los ajustes del preset encima (los archivos del
    preset, «files/x.jpg», pasan a ruta absoluta; None = dejar el valor del original).
    """
    if not ruta:
        return None
    if os.path.isfile(ruta):
        return {"tipo": "video", "archivo": ruta}
    if not os.path.isdir(ruta):
        return None
    proyecto = _proyecto(ruta)
    tipo = str(proyecto.get("type", "")).lower()
    ajustes, carpeta_preset = {}, None
    if not tipo and proyecto.get("dependency") and isinstance(proyecto.get("preset"), dict):
        ajustes, carpeta_preset = proyecto["preset"], ruta
        ruta = os.path.join(os.path.dirname(ruta.rstrip("/")), str(proyecto["dependency"]))
        proyecto = _proyecto(ruta)
        tipo = str(proyecto.get("type", "")).lower()
    props_def = ((proyecto.get("general") or {}).get("properties") or {})
    valores = {k: v.get("value") for k, v in props_def.items() if isinstance(v, dict) and "value" in v}
    for k, v in ajustes.items():
        if v is None:
            continue
        tipo_prop = (props_def.get(k) or {}).get("type")
        if tipo_prop in ("file", "directory") and isinstance(v, str) and v and carpeta_preset:
            v = os.path.join(carpeta_preset, v)
        valores[k] = v
    preview = _preview(carpeta_preset or ruta, _proyecto(carpeta_preset) if carpeta_preset else proyecto) \
        or _preview(ruta, proyecto)
    if tipo == "web":
        html = os.path.join(ruta, proyecto.get("file") or "index.html")
        if not os.path.isfile(html):
            return None
        return {"tipo": "web", "carpeta": ruta, "html": html, "props": {k: {"value": v} for k, v in valores.items()},
                "preview": preview}
    if tipo == "scene":
        return {"tipo": "scene", "carpeta": ruta,
                "props": {k: valores[k] for k, v in ajustes.items() if v is not None},
                "preview": preview}
    if tipo == "video":
        archivo = os.path.join(ruta, proyecto.get("file") or "")
        return {"tipo": "video", "archivo": archivo} if os.path.isfile(archivo) else None
    return None


class VentanaFondo(Gtk.Window):
    def __init__(self, app: "Renderer", monitor: Gdk.Monitor):
        super().__init__(application=app, decorated=False)
        self.monitor = monitor
        self.conector = monitor.get_connector() or "?"
        self.set_title(f"{MARCA}{self.conector}")
        self.ruta = None
        self.fondo = None        # lo que devolvió resolver_fondo
        self.media = None        # video
        self.web = None          # WebKit.WebView
        self.reproduciendo = True  # último estado aplicado (se repite al terminar de cargar una página)
        self.set_child(Gtk.Box())
        self.fullscreen_on_monitor(monitor)
        self.present()

    def posicion(self) -> tuple[int, int]:
        g = self.monitor.get_geometry()
        return g.x, g.y

    def _limpiar(self):
        if self.media:
            self.media.pause()
        if self.web:
            self.web.try_close()
        self.media = self.web = None

    def poner_fondo(self, ruta: str | None) -> None:
        if ruta == self.ruta:
            return
        self._limpiar()
        self.ruta, self.fondo = ruta, resolver_fondo(ruta)
        f = self.fondo
        if not f:
            log(f"{self.conector}: sin fondo válido ({ruta})")
            self.set_child(Gtk.Box())
            return
        if f["tipo"] == "video":
            self.media = Gtk.MediaFile.new_for_filename(f["archivo"])
            self.media.set_loop(True)
            self.media.connect("notify::error", self._error)
            self.set_child(self._picture(self.media))
        elif f["tipo"] == "web" and WebKit:
            self.set_child(self._webview(f))
        else:  # escena (la dibuja linux-wallpaperengine encima) o web sin WebKit: vista previa
            self.set_child(self._vista_previa(f.get("preview")))
        log(f"{self.conector}: {f['tipo']} {ruta}")

    def _vista_previa(self, archivo: str | None) -> Gtk.Widget:
        # Solo es un respaldo: una vista previa corrupta o a medio bajar no impide mostrar el fondo
        if not archivo:
            return Gtk.Box()
        try:
            return self._picture(Gdk.Texture.new_from_filename(archivo))
        except GLib.Error as e:
            log(f"{self.conector}: vista previa ilegible {archivo}: {e.message}")
            return Gtk.Box()

    @staticmethod
    def _picture(paintable) -> Gtk.Picture:
        pic = Gtk.Picture.new_for_paintable(paintable)
        pic.set_content_fit(Gtk.ContentFit.COVER)
        return pic

    def _webview(self, f: dict):
        contenido = WebKit.UserContentManager()
        contenido.add_script(WebKit.UserScript.new(
            API_WE_JS, WebKit.UserContentInjectedFrames.TOP_FRAME,
            WebKit.UserScriptInjectionTime.START, None, None))
        self.web = nueva_vista_web(contenido)
        self.web.set_background_color(Gdk.RGBA(0, 0, 0, 1))
        props = json.dumps(f["props"])

        self.web.connect("load-changed", lambda _w, ev: ev == WebKit.LoadEvent.FINISHED
                         and self._js(self._js_al_cargar(props)))
        self.web.load_uri(url_fondo_web(f["carpeta"], f["html"]))
        return self.web

    def _js_al_cargar(self, props: str) -> str:
        # Ajustes y también el estado actual: un setPaused anterior pudo llegar antes de que la página
        # registrara wallpaperPropertyListener
        return ("var l = window.wallpaperPropertyListener;"
                f"if (l && l.applyUserProperties) l.applyUserProperties({props});"
                "if (l && l.applyGeneralProperties) l.applyGeneralProperties({fps: 30});"
                + self._js_pausa())

    def _js_pausa(self) -> str:
        return ("var l = window.wallpaperPropertyListener;"
                f"if (l && l.setPaused) l.setPaused({'false' if self.reproduciendo else 'true'});")

    def _js(self, codigo: str):
        if self.web:
            self.web.evaluate_javascript(codigo, -1, None, None, None, None, None)

    def aplicar(self, reproducir: bool, silencio: bool, volumen: int) -> None:
        self.reproduciendo = reproducir
        if self.media:
            self.media.set_muted(silencio)
            self.media.set_volume(max(0, min(volumen, 100)) / 100)
            if reproducir and not self.media.get_playing():
                self.media.play()
            elif not reproducir and self.media.get_playing():
                self.media.pause()
        if self.web:
            self.web.set_is_muted(silencio)
            self._js(self._js_pausa())

    def _error(self, media, _pspec):
        if media.get_error():
            log(f"{self.conector}: error de reproducción: {media.get_error().message}")


class Renderer(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.ventanas: list[VentanaFondo] = []
        self.config: dict = {}
        self.cubiertos: dict[tuple[int, int], bool] = {}
        self._recarga_id = 0
        self._monitor_config = None

    # --- acciones D-Bus -------------------------------------------------------------------------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        registrar_esquema()
        cfg = leer_config()
        self.pausado = Gio.SimpleAction.new_stateful("pausado", None, GLib.Variant.new_boolean(False))
        self.silencio = Gio.SimpleAction.new_stateful(
            "silencio", None, GLib.Variant.new_boolean(bool(cfg.get("is_mute", True))))
        self.volumen = Gio.SimpleAction.new_stateful(
            "volumen", None, GLib.Variant.new_int32(int(cfg.get("audio_volume", 50))))
        for accion in (self.pausado, self.silencio, self.volumen):
            accion.connect("change-state", self._cambiar_estado)
            self.add_action(accion)
        recargar = Gio.SimpleAction.new("recargar", None)
        recargar.connect("activate", lambda *_: self.recargar())
        self.add_action(recargar)
        cubierto = Gio.SimpleAction.new("cubierto", GLib.VariantType.new("(iib)"))
        cubierto.connect("activate", self._cubierto)
        self.add_action(cubierto)
        # Solo lectura para la extensión: qué escena va en cada monitor y en qué estado
        self.escenas = Gio.SimpleAction.new_stateful("escenas", None, GLib.Variant.new_string("{}"))
        self.escenas.connect("change-state", lambda *_: None)  # no se cambia desde afuera
        self.add_action(self.escenas)

    def _cambiar_estado(self, accion, valor):
        if accion is self.volumen:
            valor = GLib.Variant.new_int32(max(0, min(valor.get_int32(), 100)))
        accion.set_state(valor)
        log(f"{accion.get_name()} = {valor.unpack()}")
        self.aplicar()

    def _cubierto(self, _accion, param):
        x, y, tapado = param.unpack()
        if self.cubiertos.get((x, y)) != tapado:
            self.cubiertos[(x, y)] = tapado
            log(f"monitor en {x},{y}: {'tapado por una ventana maximizada' if tapado else 'despejado'}")
            self.aplicar()

    # --- ventanas y configuración ---------------------------------------------------------------
    def do_activate(self):
        monitores = Gdk.Display.get_default().get_monitors()
        monitores.connect("items-changed", lambda *_: GLib.idle_add(self._armar))
        self._monitor_config = Gio.File.new_for_path(CONFIG).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._monitor_config.connect("changed", lambda *_: self._programar_recarga())
        self._armar()
        self.hold()  # sigue vivo aunque cambien los monitores (se cierran y recrean ventanas)

    def _programar_recarga(self):
        # Guardar config.json dispara varios eventos (tmp + rename): se recarga una vez, 300 ms después
        if self._recarga_id:
            GLib.source_remove(self._recarga_id)
        self._recarga_id = GLib.timeout_add(300, self._recarga_programada)

    def _recarga_programada(self):
        self._recarga_id = 0
        self.recargar()
        return GLib.SOURCE_REMOVE

    def _armar(self):
        for v in self.ventanas:
            v.poner_fondo(None)
            v.destroy()
        monitores = Gdk.Display.get_default().get_monitors()
        self.ventanas = [VentanaFondo(self, monitores.get_item(i)) for i in range(monitores.get_n_items())]
        log(f"{len(self.ventanas)} monitor(es)")
        self.recargar()
        return GLib.SOURCE_REMOVE

    def recargar(self):
        self.config = leer_config()
        ds = self.config.get("data_source", {})
        forzado = os.environ.get("RIPOWALL_VIDEO")
        for v in self.ventanas:
            v.poner_fondo(forzado or ds.get(v.conector) or ds.get("Default"))
        self.aplicar()

    def aplicar(self):
        pausa_max = bool(self.config.get("is_pause_when_maximized", True))
        silencio = self.silencio.get_state().get_boolean()
        volumen = self.volumen.get_state().get_int32()
        escenas = {}
        for v in self.ventanas:
            reproducir = debe_reproducir(self.pausado.get_state().get_boolean(), pausa_max,
                                         self.cubiertos.get(v.posicion(), False))
            v.aplicar(reproducir, silencio, volumen)
            if v.fondo and v.fondo["tipo"] == "scene":
                escenas[v.conector] = {"carpeta": v.fondo["carpeta"], "props": v.fondo["props"],
                                       "pausado": not reproducir, "silencio": silencio, "volumen": volumen}
        nuevo = json.dumps(escenas, sort_keys=True)
        if nuevo != self.escenas.get_state().get_string():
            self.escenas.set_state(GLib.Variant.new_string(nuevo))
            log(f"escenas: {list(escenas) or 'ninguna'}")


if __name__ == "__main__":
    sys.exit(Renderer().run([]))
