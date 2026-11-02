"""La GUI mantiene el daemon corriendo sola y solo avisa si algo falla.

No abre ventanas ni toca systemd: usa un objeto falso en vez de la ventana y
simula get_daemon_status / daemon_start.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import hidamari_gui as G
except (ImportError, ValueError):  # sin GTK4/Adwaita instalados
    if os.environ.get("RIPOWALL_REQUIERE_GUI"):  # en el CI no se permite saltar estas pruebas
        raise
    G = None


class _Label:
    def __init__(self):
        self.text = ""

    def set_label(self, text):
        self.text = text


class _Box:
    def __init__(self):
        self.visible = True

    def set_visible(self, v):
        self.visible = v


def _fake_window():
    w = types.SimpleNamespace(
        _problems={}, _last_daemon_start=0,
        problem_label=_Label(), problem_box=_Box(),
    )
    w._set_problem = types.MethodType(G.RipoWallWindow._set_problem, w)
    w._refresh_daemon = types.MethodType(G.RipoWallWindow._refresh_daemon, w)
    return w


@unittest.skipIf(G is None, "GTK4/Adwaita no disponibles")
class TestRefreshDaemon(unittest.TestCase):
    def setUp(self):
        self.clock = [100_000_000]  # microsegundos, como GLib.get_monotonic_time
        p = mock.patch.object(G.GLib, "get_monotonic_time", side_effect=lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)

    def _run(self, w, status, start_ok=True):
        with mock.patch.object(G.H, "get_daemon_status", return_value=status), \
             mock.patch.object(G.H, "daemon_start", return_value=start_ok) as start:
            self.assertTrue(w._refresh_daemon())  # True = seguir en el timeout
            return start

    def test_activo_no_muestra_aviso(self):
        w = _fake_window()
        start = self._run(w, "active")
        start.assert_not_called()
        self.assertFalse(w.problem_box.visible)

    def test_reiniciando_no_es_un_fallo(self):
        w = _fake_window()
        start = self._run(w, "activating")
        start.assert_not_called()
        self.assertFalse(w.problem_box.visible)

    def test_detenido_lo_arranca_solo(self):
        w = _fake_window()
        start = self._run(w, "inactive")
        start.assert_called_once()
        self.assertTrue(w.problem_box.visible)
        self.assertIn("Iniciando", w.problem_label.text)

    def test_si_no_arranca_avisa_con_el_detalle(self):
        w = _fake_window()
        self._run(w, "failed", start_ok=False)
        self.assertTrue(w.problem_box.visible)
        self.assertIn("no funciona (failed)", w.problem_label.text)
        self.assertIn("journalctl", w.problem_label.text)

    def test_no_reintenta_antes_de_30_segundos(self):
        w = _fake_window()
        self._run(w, "failed", start_ok=False)
        self.clock[0] += 5_000_000
        self._run(w, "failed").assert_not_called()
        self.clock[0] += 30_000_000
        self._run(w, "failed").assert_called_once()

    def test_al_recuperarse_el_aviso_desaparece(self):
        w = _fake_window()
        self._run(w, "failed", start_ok=False)
        self._run(w, "active")
        self.assertFalse(w.problem_box.visible)
        self.assertEqual(w.problem_label.text, "")

    def test_avisos_independientes(self):
        w = _fake_window()
        w._set_problem("monitores", "No se pudieron leer los monitores: x")
        self._run(w, "active")  # el daemon bien no borra el aviso de monitores
        self.assertTrue(w.problem_box.visible)
        self.assertIn("monitores", w.problem_label.text)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(G is None, "GTK4/Adwaita no disponibles")
class TestBorrarFondo(unittest.TestCase):
    """Al borrar un fondo original, sus presets dejan de ofrecerse y de estar asignados."""

    def setUp(self):
        import json
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = self.tmp.name
        for wid, proyecto in (("200", {"type": "web"}), ("400", {"dependency": "200", "preset": {}}),
                              ("410", {"dependency": "2000", "preset": {}}), ("300", {"type": "scene"})):
            os.makedirs(os.path.join(self.w, wid))
            with open(os.path.join(self.w, wid, "project.json"), "w") as f:
                json.dump(proyecto, f)
        self.fondos = [G.H.Wallpaper(title=wid, path=os.path.join(self.w, wid), workshop_id=wid, tipo="x")
                       for wid in ("200", "400", "410", "300")]
        self.config = {"data_source": {"eDP-1": os.path.join(self.w, "400"),
                                       "HDMI-1": os.path.join(self.w, "410"),
                                       "Default": os.path.join(self.w, "300")}}

    def test_presets_del_original_borrado(self):
        v = types.SimpleNamespace(_all_wallpapers=list(self.fondos), _refresh_gallery=lambda: None,
                                  _refresh_monitors=lambda: None, _show_toast=lambda m: None,
                                  _show_error=lambda m: self.fail(m))
        guardada = {}
        with mock.patch.object(G.H, "delete_wallpaper_files", return_value=True), \
             mock.patch.object(G.H, "try_unsubscribe"), \
             mock.patch.object(G.H, "load_config", return_value=self.config), \
             mock.patch.object(G.H, "save_config", side_effect=lambda c: guardada.update(c) or True), \
             mock.patch.object(G.H, "reload_config"):
            G.RipoWallWindow._do_delete_wallpaper(v, self.fondos[0])   # borra el 200
        self.assertEqual([w.workshop_id for w in v._all_wallpapers], ["410", "300"])
        self.assertEqual(sorted(guardada["data_source"]), ["Default", "HDMI-1"])
