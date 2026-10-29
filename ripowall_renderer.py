#!/usr/bin/env python3
"""
ripowall-renderer — reproductor de fondos de RipoWall (reemplaza a Hidamari).

Una ventana GTK4 a pantalla completa por monitor que reproduce en bucle el video asignado a ese
monitor. No se usa solo: lo lanza la extensión de GNOME (ripowall@ripotech.cl) como cliente Wayland
privilegiado, la mantiene minimizada y la muestra como fondo con un clon en vivo.

Configuración: ~/.config/ripowall/config.json (la escriben el daemon y la GUI); se recarga sola al
cambiar. Control en vivo por D-Bus (acciones de GApplication, interfaz org.gtk.Actions en
/cl/ripotech/RipoWall/Renderer):
  recargar           relee la configuración
  pausado  (b)       pausa del usuario (estado)
  silencio (b)       sin sonido (estado)
  volumen  (i)       0-100 (estado)
  cubierto (iib)     x, y del monitor y si una ventana maximizada/pantalla completa lo tapa
                     (lo manda la extensión; pausa ese monitor si is_pause_when_maximized)
Cada ventana se titula «@ripowall!<conector>». RIPOWALL_VIDEO=<ruta> fuerza un video (pruebas).
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "cl.ripotech.RipoWall.Renderer"
MARCA = "@ripowall!"
# RIPOWALL_CONFIG=<ruta> usa otra configuración (pruebas)
CONFIG = os.environ.get("RIPOWALL_CONFIG") or os.path.expanduser("~/.config/ripowall/config.json")


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


class VentanaFondo(Gtk.Window):
    def __init__(self, app: "Renderer", monitor: Gdk.Monitor):
        super().__init__(application=app, decorated=False)
        self.monitor = monitor
        self.conector = monitor.get_connector() or "?"
        self.set_title(f"{MARCA}{self.conector}")
        self.ruta = None
        self.media = None
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.set_child(self.picture)
        self.fullscreen_on_monitor(monitor)
        self.present()

    def posicion(self) -> tuple[int, int]:
        g = self.monitor.get_geometry()
        return g.x, g.y

    def poner_video(self, ruta: str | None) -> None:
        if ruta == self.ruta:
            return
        if self.media:
            self.media.pause()
        self.ruta, self.media = ruta, None
        if ruta and os.path.isfile(ruta):
            self.media = Gtk.MediaFile.new_for_filename(ruta)
            self.media.set_loop(True)
            self.media.connect("notify::error", self._error)
            log(f"{self.conector}: {ruta}")
        else:
            log(f"{self.conector}: sin video válido ({ruta})")
        self.picture.set_paintable(self.media)

    def aplicar(self, reproducir: bool, silencio: bool, volumen: int) -> None:
        if not self.media:
            return
        self.media.set_muted(silencio)
        self.media.set_volume(max(0, min(volumen, 100)) / 100)
        if reproducir and not self.media.get_playing():
            self.media.play()
        elif not reproducir and self.media.get_playing():
            self.media.pause()

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
            v.poner_video(None)
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
            v.poner_video(forzado or ds.get(v.conector) or ds.get("Default"))
        self.aplicar()

    def aplicar(self):
        pausa_max = bool(self.config.get("is_pause_when_maximized", True))
        for v in self.ventanas:
            v.aplicar(
                debe_reproducir(self.pausado.get_state().get_boolean(), pausa_max,
                                self.cubiertos.get(v.posicion(), False)),
                self.silencio.get_state().get_boolean(),
                self.volumen.get_state().get_int32(),
            )


if __name__ == "__main__":
    sys.exit(Renderer().run([]))
