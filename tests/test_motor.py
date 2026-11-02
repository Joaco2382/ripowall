"""Pruebas del motor de escenas que instala RipoWall (engine/): commit fijo, parches y empaquetado.

Que los parches se apliquen sobre el commit de upstream lo comprueba el CI (paso «Parches del motor»), porque
necesita descargar el código del motor.

Correr desde la raiz del repo:  python3 -m unittest discover -s tests -v
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(RAIZ, "engine")


def leer_conf():
    valores = {}
    with open(os.path.join(ENGINE, "motor.conf"), encoding="utf-8") as archivo:
        for linea in archivo:
            linea = linea.strip()
            if linea and not linea.startswith("#"):
                clave, valor = linea.split("=", 1)
                valores[clave] = valor
    return valores


def leer_pkgbuild(*variables):
    """Valores del PKGBUILD tal como los ve makepkg (bash lo carga; solo tiene definiciones)."""
    script = "source PKGBUILD; " + "; ".join(
        f'printf "%s\\0" "${{{v}[@]}}"; printf "\\1"' for v in variables
    )
    salida = subprocess.run(["bash", "-c", script], cwd=ENGINE, capture_output=True, text=True, check=True).stdout
    return [parte.split("\0")[:-1] for parte in salida.split("\1")[:-1]]


def parches():
    return sorted(f for f in os.listdir(os.path.join(ENGINE, "patches")) if f.endswith(".patch"))


class TestMotor(unittest.TestCase):
    def test_el_paquete_usa_el_mismo_commit_que_la_instalacion_compilada(self):
        conf = leer_conf()
        commit, pkgver, fuentes = leer_pkgbuild("_commit", "pkgver", "source")
        self.assertRegex(conf["MOTOR_COMMIT"], r"^[0-9a-f]{40}$")
        self.assertEqual(commit, [conf["MOTOR_COMMIT"]])
        self.assertTrue(pkgver[0].endswith("." + conf["MOTOR_COMMIT"][:8]), pkgver)
        self.assertIn(f"git+{conf['MOTOR_REPO']}#commit={conf['MOTOR_COMMIT']}", fuentes[0])

    def test_cada_parche_esta_en_el_paquete_con_su_suma(self):
        lista = parches()
        self.assertTrue(lista, "engine/patches/ no tiene parches")
        fuentes, sumas = leer_pkgbuild("source", "sha512sums")
        self.assertEqual(len(fuentes), len(sumas))
        locales = dict(zip(fuentes[1:], sumas[1:]))
        self.assertEqual(sorted(locales), lista, "el PKGBUILD no lista exactamente los parches de engine/patches/")
        for nombre in lista:
            with open(os.path.join(ENGINE, "patches", nombre), "rb") as archivo:
                suma = hashlib.sha512(archivo.read()).hexdigest()
            self.assertEqual(locales[nombre], suma, f"sha512sums desactualizado para {nombre}")

    def test_el_paquete_reemplaza_al_motor_sin_parches(self):
        provides, conflicts = leer_pkgbuild("provides", "conflicts")
        self.assertTrue(any(p.split("=")[0] == "linux-wallpaperengine" for p in provides))
        self.assertIn("linux-wallpaperengine-git", conflicts)
        self.assertIn("linux-wallpaperengine", conflicts)

    def test_los_instaladores_son_bash_valido(self):
        for script in ("install.sh", os.path.join("engine", "instalar-motor.sh")):
            resultado = subprocess.run(["bash", "-n", os.path.join(RAIZ, script)], capture_output=True, text=True)
            self.assertEqual(resultado.returncode, 0, f"{script}: {resultado.stderr}")

    def test_revisar_no_da_por_bueno_un_motor_sin_los_parches(self):
        # un PATH con solo lo que usa el script (sin pacman ni linux-wallpaperengine) y un HOME vacío
        with tempfile.TemporaryDirectory() as home:
            bin_aislado = os.path.join(home, "bin")
            os.mkdir(bin_aislado)
            for programa in ("dirname", "cat", "sha256sum", "awk"):
                os.symlink(shutil.which(programa), os.path.join(bin_aislado, programa))
            entorno = {"HOME": home, "PATH": bin_aislado, "XDG_DATA_HOME": os.path.join(home, "datos")}
            script = os.path.join(ENGINE, "instalar-motor.sh")
            bash = shutil.which("bash")  # el PATH aislado no lo tiene
            sin_motor = subprocess.run([bash, script, "--revisar"], env=entorno, capture_output=True, text=True)

            # un motor compilado con otros parches (otra huella) tampoco sirve
            marca = os.path.join(home, "datos", "ripowall", "motor", "ripowall-motor.txt")
            os.makedirs(os.path.dirname(marca))
            with open(marca, "w", encoding="utf-8") as archivo:
                archivo.write(leer_conf()["MOTOR_COMMIT"] + "\n" + "0" * 64 + "\n")
            viejo = subprocess.run([bash, script, "--revisar"], env=entorno, capture_output=True, text=True)

            # la marca de este commit y estos parches, pero sin el motor ni su comando: no está instalado
            with open(marca, "w", encoding="utf-8") as archivo:
                archivo.write(leer_conf()["MOTOR_COMMIT"] + "\n")
                for nombre in parches():
                    with open(os.path.join(ENGINE, "patches", nombre), "rb") as parche:
                        archivo.write(hashlib.sha256(parche.read()).hexdigest() + "\n")
            sin_binario = subprocess.run([bash, script, "--revisar"], env=entorno, capture_output=True, text=True)

            # con el motor y su comando en ~/.local/bin sí
            for ruta in (os.path.join(os.path.dirname(marca), "linux-wallpaperengine"),
                         os.path.join(home, ".local", "bin", "linux-wallpaperengine")):
                os.makedirs(os.path.dirname(ruta), exist_ok=True)
                with open(ruta, "w", encoding="utf-8") as archivo:
                    archivo.write("#!/bin/sh\n")
                os.chmod(ruta, 0o755)
            al_dia = subprocess.run([bash, script, "--revisar"], env=entorno, capture_output=True, text=True)

        self.assertEqual(sin_motor.returncode, 1, sin_motor.stdout + sin_motor.stderr)
        self.assertIn("No hay motor", sin_motor.stdout)
        self.assertEqual(viejo.returncode, 1, viejo.stdout + viejo.stderr)
        self.assertIn("desactualizado", viejo.stdout)
        self.assertEqual(sin_binario.returncode, 1, sin_binario.stdout + sin_binario.stderr)
        self.assertIn("incompleto", sin_binario.stdout)
        self.assertEqual(al_dia.returncode, 0, al_dia.stdout + al_dia.stderr)
        self.assertIn("al día", al_dia.stdout)
    def test_install_sh_falla_si_no_se_pudo_instalar_el_motor(self):
        # install.sh copiado junto a un engine/instalar-motor.sh que falla; opción [4] (solo el motor)
        with tempfile.TemporaryDirectory() as carpeta:
            shutil.copy(os.path.join(RAIZ, "install.sh"), carpeta)
            os.mkdir(os.path.join(carpeta, "engine"))
            falso = os.path.join(carpeta, "engine", "instalar-motor.sh")
            with open(falso, "w", encoding="utf-8") as archivo:
                archivo.write("#!/bin/sh\necho motor-falso-fallo\nexit 1\n")
            os.chmod(falso, 0o755)
            resultado = subprocess.run(
                ["bash", os.path.join(carpeta, "install.sh")], input="4\n", capture_output=True, text=True,
                env={**os.environ, "HOME": carpeta},
            )
        self.assertIn("motor-falso-fallo", resultado.stdout)  # de verdad corrió el instalador del motor
        self.assertNotEqual(resultado.returncode, 0, resultado.stdout)
        self.assertNotIn("RipoWall instalado", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
