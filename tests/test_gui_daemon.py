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
except (ImportError, ValueError) as e:  # sin GTK4/Adwaita instalados
    G = None
    GUI_IMPORT_ERROR = e


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
