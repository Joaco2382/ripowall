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

# Salida real de `gdbus call ... Properties.GetAll` con Hidamari corriendo (2026-10-29)
GDBUS_GETALL = (
    "({'mode': <'MODE_VIDEO'>, 'volume': <0>, 'blur_radius': <5>, "
    "'is_mute': <true>, 'is_playing': <true>, 'is_paused_by_user': <false>, "
    "'is_static_wallpaper': <true>, 'is_pause_when_maximized': <false>, "
    "'is_mute_when_maximized': <false>},)\n"
)


class TestServerProperties(unittest.TestCase):
    def _run_with(self, stdout):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        with mock.patch.object(H.subprocess, "run", return_value=done):
            return H.get_server_properties()

    def test_lee_booleanos_enteros_y_textos(self):
        props = self._run_with(GDBUS_GETALL)
        self.assertIs(props["is_mute"], True)
        self.assertIs(props["is_paused_by_user"], False)
        self.assertIs(props["is_pause_when_maximized"], False)
        self.assertEqual(props["volume"], 0)
        self.assertEqual(props["blur_radius"], 5)
        self.assertEqual(props["mode"], "MODE_VIDEO")

    def test_enteros_con_tipo_explicito(self):
        props = self._run_with("({'volume': <int32 42>, 'is_mute': <false>},)")
        self.assertEqual(props["volume"], 42)
        self.assertIs(props["is_mute"], False)

    def test_error_de_dbus_devuelve_vacio(self):
        err = subprocess.CalledProcessError(1, ["gdbus"])
        with mock.patch.object(H.subprocess, "run", side_effect=err):
            self.assertEqual(H.get_server_properties(), {})


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


if __name__ == "__main__":
    unittest.main()
