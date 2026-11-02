"""Carga un fondo web como lo hace el reproductor y escribe el título final («R:{json}»).

Uso: python3 tests/pagina_webkit.py <carpeta-del-fondo>  (lo llama test_renderer en otro proceso)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ripowall_renderer as R  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

fondo = sys.argv[1]
Gtk.init()
ventana = Gtk.Window()
web = R.nueva_vista_web()  # la misma que usa VentanaFondo
ventana.set_child(web)
ventana.present()
web.load_uri(R.url_fondo_web(fondo, os.path.join(fondo, "index.html")))
fin = GLib.get_monotonic_time() + 30_000_000
while not (web.get_title() or "").startswith("R:") and GLib.get_monotonic_time() < fin:
    GLib.MainContext.default().iteration(False)
print(web.get_title() or "(sin título)", flush=True)
os._exit(0)  # sin cerrar WebKit: se cae al terminar Python normalmente
