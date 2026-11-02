"""Argumentos con que la extensión lanza linux-wallpaperengine (se leen del código de la extensión)."""
import os
import re
import shutil
import subprocess
import unittest

EXTENSION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "extension", "ripowall@ripotech.cl", "extension.js")


def argv_escena() -> list[str]:
    """Literales del arreglo inicial `const argv = [motor, ...]` de Escenas._lanzar."""
    with open(EXTENSION, encoding="utf-8") as f:
        codigo = f.read()
    m = re.search(r"const argv = \[motor,(.*?)\];", codigo, re.S)
    if not m:
        raise AssertionError("no se encontró el argv del motor en extension.js")
    return [a or b for a, b in re.findall(r"'([^']*)'|`([^`]*)`", m.group(1))]


class TestArgvEscena(unittest.TestCase):
    def test_scaling_fill_justo_despues_de_window(self):
        # El motor aplica --scaling a la salida anterior: tiene que ir después de --window
        argv = argv_escena()
        i = argv.index("--window")
        self.assertEqual(argv[i + 2:i + 4], ["--scaling", "fill"], argv)

    def test_ventana_del_tamano_del_monitor_y_sin_mouse(self):
        argv = argv_escena()
        self.assertEqual(argv[argv.index("--window") + 1], "0x0x${geo.width}x${geo.height}")
        self.assertIn("--disable-mouse", argv)


def clase_escenas() -> str:
    """Código de la clase Escenas, para correrla en gjs con un D-Bus falso."""
    with open(EXTENSION, encoding="utf-8") as f:
        codigo = f.read()
    m = re.search(r"^class Escenas \{.*?^\}$", codigo, re.S | re.M)
    if not m:
        raise AssertionError("no se encontró la clase Escenas en extension.js")
    return m.group(0).replace("Gio.DBus.session", "SESION")


PRUEBA_GJS = """
const {Gio, GLib} = imports.gi;
const BUS_RENDERER = 'b', RUTA_RENDERER = 'r', ASSETS_WE = '';
const log = () => {};
let respuesta = null;
const SESION = {
    signal_subscribe: () => 1,
    signal_unsubscribe: () => {},
    call: (...args) => { respuesta = args[args.length - 1]; },
};
%s
function probar(desactivarAntes) {
    const e = new Escenas(() => {});
    let lanzados = 0;
    e._lanzar = () => { lanzados++; };
    e.consultar();
    if (desactivarAntes)
        e.destruir();
    const json = '{"eDP-1": {"carpeta": "/x", "props": {}, "pausado": false, "silencio": true, "volumen": 50}}';
    respuesta({call_finish: () => ({deep_unpack: () => [[true, '', [{deep_unpack: () => json}]]]})}, null);
    return lanzados;
}
print(`activa=${probar(false)} desactivada=${probar(true)}`);
"""


@unittest.skipIf(shutil.which("gjs") is None and not os.environ.get("RIPOWALL_REQUIERE_GUI"), "gjs no disponible")
class TestEscenasAlDesactivar(unittest.TestCase):
    def test_respuesta_tardia_no_lanza_motores(self):
        # Si la extensión se desactiva con la consulta en curso, la respuesta no debe lanzar escenas
        r = subprocess.run(["gjs", "-c", PRUEBA_GJS % clase_escenas()], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout.strip(), "activa=1 desactivada=0", r.stderr)


if __name__ == "__main__":
    unittest.main()
