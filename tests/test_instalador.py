"""install.sh: RipoWall se instala solo en GNOME 45 o más nuevo (se simula gnome-shell con un script falso)."""
import os
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestRevisaGnome(unittest.TestCase):
    def _instalar(self, version_gnome, opcion):
        with tempfile.TemporaryDirectory() as tmp:
            falso = os.path.join(tmp, "gnome-shell")
            with open(falso, "w") as f:
                f.write(f"#!/bin/sh\necho 'GNOME Shell {version_gnome}'\n" if version_gnome else "#!/bin/sh\nexit 1\n")
            os.chmod(falso, 0o755)
            # gnome-extensions falso: la instalación de prueba no toca la sesión real
            with open(os.path.join(tmp, "gnome-extensions"), "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(os.path.join(tmp, "gnome-extensions"), 0o755)
            env = dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}", HOME=tmp)
            return subprocess.run(["bash", os.path.join(REPO, "install.sh")], input=f"{opcion}\n",
                                  capture_output=True, text=True, env=env, timeout=60)

    def test_sin_gnome_no_instala(self):
        r = self._instalar(None, 3)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No se encontró GNOME Shell", r.stdout)

    def test_gnome_44_no_instala(self):
        r = self._instalar("44.9", 3)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("necesita GNOME 45", r.stdout)

    def test_gnome_45_instala(self):
        r = self._instalar("45.0", 3)  # opción 3: solo copia RipoWall (en el HOME temporal)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("GNOME Shell: \x1b[1m45", r.stdout)
        self.assertIn("ripowall-renderer", r.stdout)


if __name__ == "__main__":
    unittest.main()
