"""Pruebas de hidamari_core sin tocar el escritorio (no llaman a DBus ni a Hidamari).

Correr desde la raiz del repo:  python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hidamari_core as H  # noqa: E402

try:
    import ripowall_renderer as R
except (ImportError, ValueError) as e:  # sin GTK4 instalado
    R, RENDERER_ERROR = None, e

# Salida real de `gdbus call ... org.gtk.Actions.DescribeAll` del reproductor propio (2026-10-29)
DESCRIBE_ALL = (
    "({'silencio': (true, signature '', [<true>]), 'volumen': (true, '', [<100>]), "
    "'pausado': (true, '', [<true>]), 'recargar': (true, '', []), 'cubierto': (true, '(iib)', [])},)\n"
)


class TestServerProperties(unittest.TestCase):
    def _run_with(self, stdout):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with mock.patch.object(H.subprocess, "run", return_value=done) as run:
            return H.get_server_properties(), run

    def test_lee_el_estado_del_reproductor_con_las_claves_de_siempre(self):
        props, run = self._run_with(DESCRIBE_ALL)
        self.assertIs(props["is_mute"], True)
        self.assertIs(props["is_paused_by_user"], True)
        self.assertIs(props["is_playing"], False)
        self.assertEqual(props["volume"], 100)
        self.assertIn("org.gtk.Actions.DescribeAll", run.call_args.args[0])
        self.assertIn("cl.ripotech.RipoWall.Renderer", run.call_args.args[0])

    def test_enteros_con_tipo_explicito(self):
        props, _ = self._run_with("({'volumen': (true, '', [<int32 42>]), 'pausado': (true, '', [<false>])},)")
        self.assertEqual(props["volume"], 42)
        self.assertIs(props["is_playing"], True)

    def test_reproductor_apagado_devuelve_vacio(self):
        err = subprocess.CalledProcessError(1, ["gdbus"])
        with mock.patch.object(H.subprocess, "run", side_effect=err):
            self.assertEqual(H.get_server_properties(), {})


class TestControlDelReproductor(unittest.TestCase):
    """Los comandos exactos que el core le manda al reproductor por D-Bus."""

    def _llamar(self, fn, *args):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="()", stderr="")
        with mock.patch.object(H.subprocess, "run", return_value=done) as run:
            ok = fn(*args)
        return ok, [c.args[0] for c in run.call_args_list]

    def test_pausar_y_reanudar(self):
        ok, cmds = self._llamar(H.pause_playback)
        self.assertTrue(ok)
        self.assertIn("org.gtk.Actions.SetState", cmds[0])
        self.assertEqual(cmds[0][-3:], ["pausado", "<true>", "{}"])
        _, cmds = self._llamar(H.start_playback)
        self.assertEqual(cmds[0][-3:], ["pausado", "<false>", "{}"])

    def test_silencio_y_volumen_limitado(self):
        _, cmds = self._llamar(H.set_mute, True)
        self.assertEqual(cmds[0][-3:], ["silencio", "<true>", "{}"])
        _, cmds = self._llamar(H.set_volume, 250)
        self.assertEqual(cmds[0][-3:], ["volumen", "<int32 100>", "{}"])
        _, cmds = self._llamar(H.set_volume, -3)
        self.assertEqual(cmds[0][-3:], ["volumen", "<int32 0>", "{}"])

    def test_recargar(self):
        ok, cmds = self._llamar(H.reload_config)
        self.assertTrue(ok)
        self.assertIn("org.gtk.Actions.Activate", cmds[0])
        self.assertEqual(cmds[0][-3:], ["recargar", "[]", "{}"])

    def test_reproductor_corriendo(self):
        si = subprocess.CompletedProcess(args=[], returncode=0, stdout="(true,)\n", stderr="")
        no = subprocess.CompletedProcess(args=[], returncode=0, stdout="(false,)\n", stderr="")
        with mock.patch.object(H.subprocess, "run", return_value=si):
            self.assertTrue(H.is_server_running())
        with mock.patch.object(H.subprocess, "run", return_value=no):
            self.assertFalse(H.is_server_running())


class TestSanitizeHidamariConfig(unittest.TestCase):
    def test_repara_valores_que_rompen_la_pausa(self):
        cfg = {"fade_interval": 600, "audio_volume": 0, "pause_when_maximized": True}
        self.assertTrue(H.sanitize_hidamari_config(cfg))
        self.assertEqual(cfg["fade_interval"], 0.1)
        self.assertGreater(cfg["audio_volume"], 0)
        self.assertNotIn("pause_when_maximized", cfg)
        self.assertIs(cfg["is_pause_when_maximized"], True)

    def test_config_sana_no_cambia(self):
        cfg = {"fade_interval": 0.1, "audio_volume": 50, "is_pause_when_maximized": False}
        before = dict(cfg)
        self.assertFalse(H.sanitize_hidamari_config(cfg))
        self.assertEqual(cfg, before)

    def test_clave_vieja_no_pisa_la_nueva(self):
        cfg = {"fade_interval": 0.1, "audio_volume": 50,
               "pause_when_maximized": True, "is_pause_when_maximized": False}
        H.sanitize_hidamari_config(cfg)
        self.assertIs(cfg["is_pause_when_maximized"], False)


class TestRotateSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ripowall", "settings.json")
        patcher = mock.patch.object(H, "SETTINGS_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_sin_archivo_usa_default(self):
        self.assertEqual(H.get_rotate_minutes(), H.DEFAULT_ROTATE_MINUTES)

    def test_guardar_y_leer_off(self):
        self.assertTrue(H.save_settings({"rotate_minutes": 0}))
        self.assertEqual(H.get_rotate_minutes(), 0)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"rotate_minutes": 0})

    def test_valor_invalido_usa_default(self):
        for bad in (-5, "10", None, 2.5):
            H.save_settings({"rotate_minutes": bad})
            self.assertEqual(H.get_rotate_minutes(), H.DEFAULT_ROTATE_MINUTES, bad)

    def test_json_corrupto_usa_default(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{no es json")
        self.assertEqual(H.get_rotate_minutes(), H.DEFAULT_ROTATE_MINUTES)


class TestConfigPropia(unittest.TestCase):
    """config.json de RipoWall: migración desde Hidamari y escritura aunque el reproductor no corra."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.propia = os.path.join(self.tmp.name, "ripowall", "config.json")
        self.vieja = os.path.join(self.tmp.name, "hidamari", "config.json")
        for p in (mock.patch.object(H, "CONFIG_PATH", self.propia),
                  mock.patch.object(H, "CONFIG_HIDAMARI", self.vieja)):
            p.start()
            self.addCleanup(p.stop)
        # el reproductor «apagado»: toda llamada por D-Bus falla
        p = mock.patch.object(H.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["gdbus"]))
        p.start()
        self.addCleanup(p.stop)

    def test_migra_la_config_de_hidamari_una_vez(self):
        os.makedirs(os.path.dirname(self.vieja))
        with open(self.vieja, "w", encoding="utf-8") as f:
            json.dump({"data_source": {"eDP-1": "/wp/a.mp4"}, "is_mute": True}, f)
        self.assertEqual(H.load_config()["data_source"], {"eDP-1": "/wp/a.mp4"})
        self.assertTrue(os.path.isfile(self.propia))
        with open(self.vieja, "w", encoding="utf-8") as f:   # cambios posteriores en la vieja no se copian
            json.dump({"data_source": {"eDP-1": "/wp/OTRO.mp4"}}, f)
        self.assertEqual(H.load_config()["data_source"], {"eDP-1": "/wp/a.mp4"})

    def test_sin_ninguna_config_devuelve_vacio(self):
        self.assertEqual(H.load_config(), {})

    def test_asignar_se_guarda_aunque_el_reproductor_no_corra(self):
        self.assertTrue(H.assign_video_to_monitor("/wp/b.mp4", "HDMI-1"))
        cfg = H.load_config()
        self.assertEqual(cfg["data_source"]["HDMI-1"], "/wp/b.mp4")
        self.assertEqual(cfg["mode"], "MODE_VIDEO")

    def test_pausa_con_maximizada_se_guarda_en_la_config(self):
        H.save_config({"is_pause_when_maximized": True})
        H.set_pause_when_maximized(False)
        self.assertIs(H.load_config()["is_pause_when_maximized"], False)


@unittest.skipIf(R is None and not os.environ.get("RIPOWALL_REQUIERE_GUI"), "GTK4 no disponible")
class TestReglaDeReproduccion(unittest.TestCase):
    def test_tabla(self):
        if R is None:
            raise RENDERER_ERROR
        casos = [  # (pausado, pausa_si_maximizada, cubierto) -> reproduce
            ((False, True, False), True),
            ((False, True, True), False),    # tapado y con la opción activa: pausa
            ((False, False, True), True),    # tapado pero la opción está apagada: sigue
            ((True, False, False), False),   # pausa del usuario manda
            ((True, True, True), False),
        ]
        for args, esperado in casos:
            self.assertIs(R.debe_reproducir(*args), esperado, args)


if __name__ == "__main__":
    unittest.main()
