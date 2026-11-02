"""Diagnóstico: aviso de códec H.264 (Fedora no lo trae y los videos del Workshop no se reproducen)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ripowall_diagnostics as D  # noqa: E402


class TestCodecH264(unittest.TestCase):
    def _revisar(self, decodificadores):
        r = D.DiagnosticReport()
        with mock.patch.object(D, "decodificadores_h264", return_value=decodificadores):
            D.check_codec_h264(r)
        return r.results[-1]

    def test_sin_decodificador_es_error_con_la_solucion(self):
        res = self._revisar([])
        self.assertEqual(res.status, "error")
        self.assertIn("RPM Fusion", res.fix_suggestion)

    def test_con_decodificador_ok(self):
        res = self._revisar(["avdec_h264"])
        self.assertEqual(res.status, "ok")
        self.assertIn("avdec_h264", res.message)

    def test_esta_en_el_diagnostico_completo(self):
        self.assertIn(D.check_codec_h264, D.ALL_CHECKS)


class TestSinSteamAbierto(unittest.TestCase):
    """Sin Steam ni la app de Wallpaper Engine abiertos, RipoWall igual muestra fondos: no es un error."""

    def test_steam_y_we_cerrados_no_son_error(self):
        r = D.DiagnosticReport()
        with mock.patch.object(D, "_pgrep", return_value=[]):
            D.check_steam_running(r)
            D.check_we_processes(r)
        self.assertEqual([x.status for x in r.results], ["ok", "ok"])
        self.assertFalse(D.has_critical_errors(r))


if __name__ == "__main__":
    unittest.main()
