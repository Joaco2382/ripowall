"""El daemon respeta los wallpapers elegidos al conectar/desconectar monitores.

No toca Hidamari, systemd ni tus ajustes reales: monitores, config y settings.json son falsos.
"""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hidamari_core as H  # noqa: E402
import hidamari_daemon as D  # noqa: E402

WALLS = [types.SimpleNamespace(path=f"/wp/{i}.mp4", title=f"Fondo {i}") for i in range(10)]


class TestMonitores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conectados = ["eDP-1"]
        for target, new in [
            (mock.patch.object(H, "SETTINGS_PATH", os.path.join(self.tmp.name, "settings.json")), None),
            (mock.patch.object(D, "get_connected_monitors",
                               side_effect=lambda: [types.SimpleNamespace(connector=c) for c in self.conectados]), None),
            (mock.patch.object(D, "save_config", return_value=True), None),
            (mock.patch.object(D, "log"), None),
        ]:
            target.start()
            self.addCleanup(target.stop)

    def _config(self, **ds):
        return {"data_source": dict(ds), "fade_interval": 0.1, "audio_volume": 50}

    def test_conectar_monitor_no_pisa_los_demas(self):
        cfg = self._config(**{"eDP-1": WALLS[3].path, "Default": WALLS[3].path})
        self.conectados = ["eDP-1", "HDMI-1"]
        faltan = D.missing_monitors(cfg, WALLS)
        self.assertEqual(faltan, ["HDMI-1"])
        D.assign_wallpapers_to_config(cfg, WALLS, only=faltan)
        ds = cfg["data_source"]
        self.assertEqual(ds["eDP-1"], WALLS[3].path, "el monitor que ya tenia fondo no cambia")
        self.assertIn(ds["HDMI-1"], {w.path for w in WALLS})
        self.assertNotEqual(ds["HDMI-1"], WALLS[3].path, "el nuevo recibe uno distinto")
        self.assertEqual(ds["Default"], WALLS[3].path)

    def test_desconectar_y_reconectar_recupera_su_fondo(self):
        cfg = self._config(**{"eDP-1": WALLS[1].path, "HDMI-1": WALLS[7].path, "Default": WALLS[1].path})
        self.conectados = ["eDP-1"]                     # se desconecta HDMI-1
        D.assign_wallpapers_to_config(cfg, WALLS, only=D.missing_monitors(cfg, WALLS))
        self.assertNotIn("HDMI-1", cfg["data_source"])
        self.assertEqual(cfg["data_source"]["eDP-1"], WALLS[1].path)
        self.assertEqual(H.load_settings()["monitores_recordados"]["HDMI-1"], WALLS[7].path)

        self.conectados = ["eDP-1", "HDMI-1"]           # vuelve a conectarse
        D.assign_wallpapers_to_config(cfg, WALLS, only=D.missing_monitors(cfg, WALLS))
        self.assertEqual(cfg["data_source"]["HDMI-1"], WALLS[7].path, "recupera el que tenia")
        self.assertEqual(cfg["data_source"]["eDP-1"], WALLS[1].path)

    def test_recordado_que_ya_no_existe_recibe_uno_nuevo(self):
        H.save_settings({"monitores_recordados": {"HDMI-1": "/wp/borrado.mp4"}})
        cfg = self._config(**{"eDP-1": WALLS[0].path, "Default": WALLS[0].path})
        self.conectados = ["eDP-1", "HDMI-1"]
        D.assign_wallpapers_to_config(cfg, WALLS, only=D.missing_monitors(cfg, WALLS))
        self.assertIn(cfg["data_source"]["HDMI-1"], {w.path for w in WALLS})

    def test_rotar_cambia_todos(self):
        cfg = self._config(**{"eDP-1": WALLS[0].path, "HDMI-1": WALLS[1].path, "Default": WALLS[0].path})
        self.conectados = ["eDP-1", "HDMI-1"]
        D.assign_wallpapers_to_config(cfg, WALLS)       # only=None: rotacion
        ds = cfg["data_source"]
        self.assertNotEqual(ds["eDP-1"], WALLS[0].path)
        self.assertNotEqual(ds["HDMI-1"], WALLS[1].path)
        self.assertNotEqual(ds["eDP-1"], ds["HDMI-1"])
        self.assertEqual(ds["Default"], ds["eDP-1"])

    def test_sin_faltantes_no_cambia_nada(self):
        cfg = self._config(**{"eDP-1": WALLS[5].path, "Default": WALLS[5].path})
        D.assign_wallpapers_to_config(cfg, WALLS, only=D.missing_monitors(cfg, WALLS))
        self.assertEqual(cfg["data_source"], {"eDP-1": WALLS[5].path, "Default": WALLS[5].path})

    def test_config_sin_data_source(self):
        cfg = {"fade_interval": 0.1, "audio_volume": 50}
        D.assign_wallpapers_to_config(cfg, WALLS, only=D.missing_monitors(cfg, WALLS))
        self.assertIn(cfg["data_source"]["eDP-1"], {w.path for w in WALLS})
        self.assertEqual(cfg["data_source"]["Default"], cfg["data_source"]["eDP-1"])


class TestWatchWorkshop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "config.json")
        for p in (mock.patch.object(H, "CONFIG_PATH", self.config),
                  mock.patch.object(H, "CONFIG_HIDAMARI", os.path.join(self.tmp.name, "no-existe.json")),
                  mock.patch.object(D, "reload_config", return_value=True),
                  mock.patch.object(D, "log")):
            p.start()
            self.addCleanup(p.stop)

    def _fondo(self, nombre, edad):
        ruta = os.path.join(self.tmp.name, nombre)
        open(ruta, "w").close()
        os.utime(ruta, (edad, edad))
        return types.SimpleNamespace(path=ruta, title=nombre)

    def test_el_nuevo_de_verdad_pasa_a_default(self):
        viejo = self._fondo("aaa-viejo.mp4", 1000)
        nuevo = self._fondo("zzz-nuevo.mp4", 2000)    # alfabéticamente último: antes elegía «aaa»
        H.save_config({"data_source": {"eDP-1": viejo.path, "Default": viejo.path}})
        actuales = D.watch_workshop({viejo.path}, [viejo, nuevo])
        self.assertEqual(actuales, {viejo.path, nuevo.path})
        cfg = H.load_config()
        self.assertEqual(cfg["data_source"]["Default"], nuevo.path)
        self.assertEqual(cfg["data_source"]["eDP-1"], viejo.path, "no toca el monitor elegido")

    def test_entre_varios_nuevos_elige_el_mas_reciente(self):
        a, b, c = self._fondo("a.mp4", 1000), self._fondo("b.mp4", 3000), self._fondo("c.mp4", 2000)
        H.save_config({"data_source": {}})
        D.watch_workshop(set(), [a, b, c])
        self.assertEqual(H.load_config()["data_source"]["Default"], b.path)

    def test_no_pisa_cambios_de_la_gui(self):
        viejo, nuevo = self._fondo("v.mp4", 1000), self._fondo("n.mp4", 2000)
        H.save_config({"data_source": {"eDP-1": viejo.path}, "is_mute": False})   # lo que dejó la GUI
        D.watch_workshop({viejo.path}, [viejo, nuevo])
        self.assertIs(H.load_config()["is_mute"], False)

    def test_solo_quitados_no_cambia_default(self):
        a, b = self._fondo("a.mp4", 1000), self._fondo("b.mp4", 2000)
        H.save_config({"data_source": {"Default": a.path}})
        actuales = D.watch_workshop({a.path, b.path}, [a])
        self.assertEqual(actuales, {a.path})
        self.assertEqual(H.load_config()["data_source"]["Default"], a.path)


if __name__ == "__main__":
    unittest.main()
