"""resolver_fondo: qué muestra el reproductor para cada ruta de config.json (Workshop falso)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAGINA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pagina_webkit.py")
try:
    import ripowall_renderer as R
except (ImportError, ValueError):  # sin GTK4 instalado
    if os.environ.get("RIPOWALL_REQUIERE_GUI"):  # en el CI no se permite saltar estas pruebas
        raise
    R = None


@unittest.skipIf(R is None, "GTK4 no disponible")
class TestResolverFondo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = self.tmp.name
        self.web = self._fondo("200", {"type": "web", "file": "index.html", "preview": "preview.jpg",
                                       "general": {"properties": {
                                           "color": {"type": "color", "value": "0 0 0"},
                                           "fondo": {"type": "file", "value": ""},
                                           "texto": {"text": "solo texto, sin valor"}}}},
                               ["index.html", "preview.jpg"])
        self.escena = self._fondo("300", {"type": "scene", "file": "scene.json"}, ["scene.pkg", "preview.gif"])
        self.video = self._fondo("100", {"type": "video", "file": "a.mp4"}, ["a.mp4"])

    def _fondo(self, wid, proyecto, archivos):
        d = os.path.join(self.w, wid)
        os.makedirs(os.path.join(d, "files"), exist_ok=True)
        with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
            json.dump(proyecto, f)
        for a in archivos:
            open(os.path.join(d, a), "w").close()
        return d

    def test_video_por_archivo_y_por_carpeta(self):
        mp4 = os.path.join(self.video, "a.mp4")
        self.assertEqual(R.resolver_fondo(mp4), {"tipo": "video", "archivo": mp4})
        self.assertEqual(R.resolver_fondo(self.video), {"tipo": "video", "archivo": mp4})

    def test_web_con_valores_por_defecto(self):
        f = R.resolver_fondo(self.web)
        self.assertEqual(f["tipo"], "web")
        self.assertEqual(f["html"], os.path.join(self.web, "index.html"))
        self.assertEqual(f["props"], {"color": {"value": "0 0 0"}, "fondo": {"value": ""}})
        self.assertEqual(f["preview"], os.path.join(self.web, "preview.jpg"))

    def test_preset_cambia_valores_y_sus_archivos_pasan_a_ruta_completa(self):
        preset = self._fondo("400", {"dependency": "200", "preview": "preview.jpg",
                                     "preset": {"color": "1 0 0", "fondo": "files/miku.jpg", "texto": None}},
                             ["preview.jpg"])
        f = R.resolver_fondo(preset)
        self.assertEqual(f["tipo"], "web")
        self.assertEqual(f["html"], os.path.join(self.web, "index.html"), "usa el html del original")
        self.assertEqual(f["props"]["color"], {"value": "1 0 0"})
        self.assertEqual(f["props"]["fondo"], {"value": os.path.join(preset, "files/miku.jpg")})
        self.assertEqual(f["preview"], os.path.join(preset, "preview.jpg"), "la vista previa es la del preset")

    def test_preset_con_none_deja_el_valor_del_original(self):
        preset = self._fondo("410", {"dependency": "200", "preset": {"color": None}}, [])
        self.assertEqual(R.resolver_fondo(preset)["props"]["color"], {"value": "0 0 0"})

    def test_escena(self):
        f = R.resolver_fondo(self.escena)
        self.assertEqual((f["tipo"], f["carpeta"], f["props"]), ("scene", self.escena, {}))
        self.assertTrue(f["preview"].endswith("preview.gif"))

    def test_preset_de_escena_lleva_sus_ajustes_al_motor(self):
        preset = self._fondo("420", {"dependency": "300", "preset": {"brillo": 0.5, "nada": None}}, [])
        f = R.resolver_fondo(preset)
        self.assertEqual((f["tipo"], f["carpeta"], f["props"]), ("scene", self.escena, {"brillo": 0.5}))

    def test_preset_de_escena_pasa_sus_archivos_con_ruta_completa(self):
        self.escena = self._fondo("310", {"type": "scene", "general": {"properties": {
            "imagen": {"type": "file", "value": ""}}}}, ["scene.pkg"])
        preset = self._fondo("430", {"dependency": "310", "preset": {"imagen": "files/propia.jpg"}}, [])
        self.assertEqual(R.resolver_fondo(preset)["props"], {"imagen": os.path.join(preset, "files/propia.jpg")})

    def test_lo_que_no_se_puede_mostrar(self):
        sin_html = self._fondo("500", {"type": "web", "file": "index.html"}, [])
        huerfano = self._fondo("510", {"dependency": "999", "preset": {}}, [])
        app = self._fondo("520", {"type": "application", "file": "x.exe"}, ["x.exe"])
        for ruta in (None, "", os.path.join(self.w, "no-existe"), sin_html, huerfano, app):
            self.assertIsNone(R.resolver_fondo(ruta), ruta)


@unittest.skipIf(R is None, "GTK4 no disponible")
class TestEsquemaFondoWeb(unittest.TestCase):
    """ripowall-fondo:// solo sirve archivos de la carpeta del fondo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fondo = os.path.join(self.tmp.name, "123")
        os.makedirs(os.path.join(self.fondo, "js"))
        for a in ("index.html", "js/app.js", "con espacio.json"):
            open(os.path.join(self.fondo, a), "w").close()
        open(os.path.join(self.tmp.name, "secreto.txt"), "w").close()
        os.symlink(os.path.join(self.tmp.name, "secreto.txt"), os.path.join(self.fondo, "enlace.txt"))
        self.url = R.url_fondo_web(self.fondo, os.path.join(self.fondo, "index.html"))

    def test_sirve_los_archivos_del_fondo(self):
        self.assertEqual(self.url, "ripowall-fondo://w123/index.html")
        base = "ripowall-fondo://w123/"
        real = os.path.realpath(self.fondo)
        self.assertEqual(R.archivo_de_url(base + "js/app.js"), os.path.join(real, "js", "app.js"))
        self.assertEqual(R.archivo_de_url(base + "con%20espacio.json"), os.path.join(real, "con espacio.json"))

    def test_no_sale_de_la_carpeta(self):
        for uri in ("ripowall-fondo://w123/..%2Fsecreto.txt",      # .. codificado (el parser no lo quita)
                    "ripowall-fondo://w123/%2E%2E/secreto.txt",
                    "ripowall-fondo://w123/enlace.txt",              # enlace que apunta afuera
                    "ripowall-fondo://w999/index.html",              # carpeta no registrada
                    "file://" + os.path.join(self.fondo, "index.html"),
                    "ripowall-fondo://w123/no-existe.js"):
            self.assertIsNone(R.archivo_de_url(uri), uri)


@unittest.skipIf(R is None, "GTK4 no disponible")
class TestVentanaFondo(unittest.TestCase):
    """Partes de VentanaFondo que no necesitan una ventana de verdad."""

    def _ventana(self, reproduciendo=True):
        v = R.VentanaFondo.__new__(R.VentanaFondo)  # sin __init__: no abre ventana
        v.conector, v.reproduciendo = "eDP-1", reproduciendo
        return v

    def test_vista_previa_corrupta_no_corta_la_recarga(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
            f.write(b"no es una imagen")
            f.flush()
            hijo = self._ventana()._vista_previa(f.name)
        self.assertIsInstance(hijo, R.Gtk.Box)

    def test_al_terminar_de_cargar_repite_la_pausa(self):
        js = self._ventana(reproduciendo=False)._js_al_cargar('{"a": {"value": 1}}')
        self.assertIn('applyUserProperties({"a": {"value": 1}})', js)
        self.assertIn("setPaused(true)", js)
        self.assertIn("setPaused(false)", self._ventana(reproduciendo=True)._js_al_cargar("{}"))


PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d4944415478da63f8cfc0f01f0005000201a1a3e3a1"
                        "0000000049454e44ae426082")


@unittest.skipIf(R is None or getattr(R, "WebKit", None) is None
                 or not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")),
                 "sin WebKit o sin pantalla")
class TestAislamientoFondoWeb(unittest.TestCase):
    """Una página de verdad en WebKit: lee lo suyo y las imágenes del preset, pero no otros archivos."""

    def test_pagina_no_puede_leer_archivos_ajenos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fondo = os.path.join(tmp.name, "321")
        os.makedirs(fondo)
        secreto = os.path.join(tmp.name, "steam_session")
        with open(secreto, "w") as f:
            f.write("SECRETO")
        imagen = os.path.join(tmp.name, "preset", "files", "foto.png")
        os.makedirs(os.path.dirname(imagen))
        with open(imagen, "wb") as f:
            f.write(PNG_1X1)
        with open(os.path.join(fondo, "datos.json"), "w") as f:
            f.write('{"propio": 1}')
        with open(os.path.join(fondo, "index.html"), "w") as f:
            f.write("""<!doctype html><script>
const r = {};
async function probar(n, f) { try { r[n] = await f(); } catch (e) { r[n] = 'bloqueado: ' + e; } }
const xhr = u => new Promise((ok, mal) => { const x = new XMLHttpRequest(); x.open('GET', u);
  x.onload = () => ok(x.responseText); x.onerror = () => mal('error'); x.send(); });
(async () => {
  await probar('propio', () => fetch('datos.json').then(x => x.text()));
  await probar('xhr_propio', () => xhr('datos.json'));
  await probar('fetch_file', () => fetch('file://%(s)s').then(x => x.text()));
  await probar('xhr_file', () => xhr('file://%(s)s'));
  await probar('fuera_por_esquema', () => fetch('..%%2Fsteam_session').then(x => x.text()));
  await probar('imagen_preset', () => new Promise((ok, mal) => { const i = new Image();
    i.onload = () => ok('cargada'); i.onerror = () => mal('error'); i.src = 'file:///' + '%(i)s'; }));
  document.title = 'R:' + JSON.stringify(r);
})();
</script>""" % {"s": secreto, "i": imagen})
        # En otro proceso: WebKit se cae al cerrar Python y no debe tumbar la suite
        hecho = subprocess.run([sys.executable, PAGINA, fondo], capture_output=True, text=True, timeout=60)
        salida = [linea for linea in hecho.stdout.splitlines() if linea.startswith("R:")]
        self.assertTrue(salida, f"la página no terminó:\n{hecho.stdout}\n{hecho.stderr[-2000:]}")
        r = json.loads(salida[-1][2:])
        self.assertEqual(r["propio"], '{"propio": 1}', r)
        self.assertEqual(r["xhr_propio"], '{"propio": 1}', r)
        self.assertEqual(r["imagen_preset"], "cargada", r)
        for clave in ("fetch_file", "xhr_file", "fuera_por_esquema"):
            self.assertNotIn("SECRETO", r[clave], clave)


if __name__ == "__main__":
    unittest.main()
