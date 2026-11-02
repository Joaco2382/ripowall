#!/usr/bin/env bash
# Prueba RipoWall (extensión + reproductor) en la versión de GNOME de otra distro, dentro de Docker:
# GNOME Shell corre sin pantalla (--headless, render por software) con la extensión del repo y un video
# de prueba; nada toca el escritorio real.
#   scripts/probar-gnome-docker.sh <distro> [carpeta-salida]
#   distros: ubuntu-24.04 (GNOME 46) debian-13 (48) fedora-42 (48) fedora-43 (49) ubuntu-26.04 (50)
#            fedora-44 (50) arch (51)
# MONITORES="1280x720 1920x1080" prueba varios monitores (def. uno de 1280x720): el primero lleva un video y
# los demás otro, cada uno en su monitor.
# PRUEBA=caida   a los 5 s se mata el reproductor: la extensión tiene que relanzarlo y volver a mostrarlo.
# PRUEBA=ciclo   a los 5 s se desactiva la extensión y a los 7 s se reactiva (como al bloquear la pantalla).
# CODEC=1 (Fedora) agrega el decodificador H.264 OpenH264, que Fedora no trae por omisión.
# Deja en la carpeta: version.txt, shell.log, captura.png (a los 10 s) e informe.txt.
# La extensión se marca compatible con la versión del contenedor para probar el CÓDIGO; si declara esa
# versión de verdad lo dice metadata.json. Termina con 1 si algo no dio lo esperado.
set -euo pipefail
DISTRO="${1:?distro}"
OUT="$(realpath -m "${2:-$(mktemp -d)}")"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
MONITORES="${MONITORES:-1280x720}"
mkdir -p "$OUT"

case "$DISTRO" in
  ubuntu-*|debian-*)
    BASE="${DISTRO/-/:}"; BASE="${BASE/debian:13/debian:trixie}"
    INSTALAR='export DEBIAN_FRONTEND=noninteractive; apt-get update -q && apt-get install -y -q --no-install-recommends gnome-shell python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0 gir1.2-soup-3.0 libgtk-4-media-gstreamer gstreamer1.0-plugins-good gstreamer1.0-libav libgl1-mesa-dri dbus ca-certificates' ;;
  fedora-*)
    BASE="fedora:${DISTRO#fedora-}"
    INSTALAR='dnf install -y -q --setopt=timeout=20 --setopt=minrate=200k --setopt=retries=20 gnome-shell python3-gobject gtk4 webkitgtk6.0 gstreamer1-plugins-good gstreamer1-plugin-libav mesa-dri-drivers dbus-daemon && dnf clean all' ;;
  arch)
    BASE="archlinux:latest"
    INSTALAR='pacman -Syu --noconfirm --needed gnome-shell python-gobject gtk4 webkitgtk-6.0 gst-plugins-good gst-libav mesa && pacman -Scc --noconfirm' ;;
  *) echo "distro desconocida: $DISTRO" >&2; exit 2 ;;
esac

IMAGEN="ripowall-prueba:$DISTRO"
if [ "${CODEC:-}" = 1 ] && [[ "$DISTRO" == fedora-* ]]; then
  INSTALAR="$INSTALAR && dnf install -y -q --enablerepo=fedora-cisco-openh264 gstreamer1-plugin-openh264"
  IMAGEN="$IMAGEN-codec"
fi
if ! docker image inspect "$IMAGEN" >/dev/null 2>&1; then
  printf 'FROM %s\nRUN %s\n' "$BASE" "$INSTALAR" | docker build -q -t "$IMAGEN" - >/dev/null
fi

# Video de prueba H.264 (como los del Workshop): 6 s de patrón de colores
[ -s "$OUT/video.mp4" ] || ffmpeg -loglevel error -y -f lavfi -i testsrc2=size=1280x720:rate=30 -t 6 \
  -c:v libx264 -pix_fmt yuv420p "$OUT/video.mp4"
[ -s "$OUT/video2.mp4" ] || ffmpeg -loglevel error -y -f lavfi -i smptehdbars=size=1280x720:rate=30 -t 6 \
  -c:v libx264 -pix_fmt yuv420p "$OUT/video2.mp4"

docker run --rm -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 -e MONITORES="$MONITORES" -e PRUEBA="${PRUEBA:-}" -v "$REPO:/repo:ro" -v "$OUT:/out" "$IMAGEN" bash -c '
  set -u
  gnome-shell --version > /out/version.txt
  # GNOME Shell se conecta al bus del sistema al arrancar (logind, etc.): uno vacío basta
  dbus-uuidgen --ensure 2>/dev/null; dbus-uuidgen --ensure=/etc/machine-id 2>/dev/null
  mkdir -p /run/dbus && dbus-daemon --system --fork
  rm -rf /run/systemd  # sin systemd/logind: GNOME Shell usa su gestor de sesión de reemplazo
  V=$(gnome-shell --version | grep -oE "[0-9]+" | head -1)
  export HOME=/tmp/casa XDG_RUNTIME_DIR=/tmp/run XDG_CONFIG_HOME=/tmp/casa/.config GSETTINGS_BACKEND=keyfile
  mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" && chmod 700 "$XDG_RUNTIME_DIR"
  EXT=$HOME/.local/share/gnome-shell/extensions/ripowall@ripotech.cl
  mkdir -p "$EXT" && cp /repo/extension/ripowall@ripotech.cl/* "$EXT/"
  python3 - "$EXT/metadata.json" "$V" <<PY
import json, sys
m = json.load(open(sys.argv[1])); m["shell-version"] = [sys.argv[2]]; json.dump(m, open(sys.argv[1], "w"))
PY
  python3 - <<PY
import json
n = len("$MONITORES".split())
fuentes = {"Default": "/out/video.mp4", **{f"Meta-{i}": "/out/video2.mp4" for i in range(1, n)}}
json.dump({"data_source": fuentes, "is_mute": True, "audio_volume": 50, "is_pause_when_maximized": True},
          open("/tmp/ripowall.json", "w"))
PY
  ARGS=""; for m in $MONITORES; do ARGS="$ARGS --virtual-monitor $m"; done
  export RIPOWALL_RENDERER=/repo/ripowall_renderer.py RIPOWALL_CONFIG=/tmp/ripowall.json RIPOWALL_PRUEBA_CAPTURA=/out/captura.png
  rm -f /out/captura.png
  # Ajustes de GNOME en un archivo (backend keyfile): la extensión activada
  mkdir -p "$XDG_CONFIG_HOME/glib-2.0/settings"
  # (\047 es la comilla simple: este bloque ya va entre comillas simples)
  printf "[org/gnome/shell]\nenabled-extensions=[\047ripowall@ripotech.cl\047]\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version=\047999\047\n" \
    > "$XDG_CONFIG_HOME/glib-2.0/settings/keyfile"
  cat > /tmp/sesion.sh <<SESION
case "\$PRUEBA" in
  caida) (sleep 5; pkill -f "^[p]ython3 /repo/ripowall_renderer.py"; echo "PRUEBA: reproductor matado" >&2) & ;;
  ciclo) (sleep 5; gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell \
            -m org.gnome.Shell.Extensions.DisableExtension ripowall@ripotech.cl >&2
          sleep 2; pgrep -f "^[p]ython3 /repo/ripowall_renderer.py" >/dev/null && echo "PRUEBA: reproductor sigue vivo tras desactivar" >&2
          gdbus call --session -d org.gnome.Shell -o /org/gnome/Shell \
            -m org.gnome.Shell.Extensions.EnableExtension ripowall@ripotech.cl >&2) & ;;
esac
exec timeout 25 gnome-shell --headless --wayland --no-x11 $ARGS
SESION
  dbus-run-session -- bash /tmp/sesion.sh > /out/shell.log 2>&1 || true
' || true

REPO="$REPO" python3 -I - "$OUT" "$MONITORES" "${PRUEBA:-}" <<'PY'
import os, re, sys
out, monitores, prueba = sys.argv[1], sys.argv[2].split(), sys.argv[3]
log = open(os.path.join(out, "shell.log"), encoding="utf-8", errors="replace").read() \
    if os.path.exists(os.path.join(out, "shell.log")) else ""
version = open(os.path.join(out, "version.txt")).read().strip() if os.path.exists(os.path.join(out, "version.txt")) else "?"
import json
declaradas = json.load(open(os.path.join(os.environ["REPO"], "extension", "ripowall@ripotech.cl",
                                         "metadata.json")))["shell-version"]
mayor = re.search(r"(\d+)", version).group(1) if re.search(r"\d+", version) else "?"
casos = [
    (f"metadata.json declara GNOME {mayor}", mayor in declaradas),
    ("la extensión se activó", "extensión activada" in log),
    ("lanzó el reproductor", "reproductor iniciado" in log),
    (f"el reproductor vio {len(monitores)} monitor(es)", f"{len(monitores)} monitor(es)" in log),
    ("cargó el video", "/out/video.mp4" in log and "error de reproducción" not in log),
]
if prueba == "caida":
    casos += [("el reproductor se cayó", "PRUEBA: reproductor matado" in log),
              ("la extensión lo relanzó", log.count("reproductor iniciado") >= 2),
              ("volvió a poner su ventana como fondo", log.count("ventana del reproductor") >= 2)]
if prueba == "ciclo":
    casos += [("se desactivó", "extensión desactivada" in log),
              ("al desactivar, el reproductor se cerró", "reproductor sigue vivo tras desactivar" not in log),
              ("se reactivó y relanzó el reproductor",
               log.count("extensión activada") >= 2 and log.count("reproductor iniciado") >= 2)]
if len(monitores) > 1:
    casos.append(("cada monitor con su propio video", "Meta-1: video /out/video2.mp4" in log))
for m in monitores:
    # Diagnóstico a los 5 s: el fondo de ese monitor lleva el clon de SU ventana (del mismo tamaño; con
    # tamaños distintos por monitor, un clon cruzado se nota). GNOME no numera los monitores por nombre.
    casos.append((f"monitor {m}: el fondo es el clon de su reproductor",
                  bool(re.search(rf"diagnóstico: fondo {m} capa {m} clon {m} ventana {m}", log))))
casos += [
    ("la barra superior se ve (el reproductor no cuenta como pantalla completa)",
     "monitor en pantalla completa=false" in log),
    # «JS ERROR» y también los errores que GNOME atribuye a la extensión (p. ej. al activarla)
    ("sin errores de JavaScript", "JS ERROR" not in log and "Extension ripowall@ripotech.cl:" not in log),
    ("tomó la captura", os.path.exists(os.path.join(out, "captura.png"))),
]
lineas = [f"{version}"] + [("OK    " if ok else "FALLA ") + t for t, ok in casos]
fallos = sum(not ok for _, ok in casos)
lineas.append(f"{len(casos) - fallos}/{len(casos)} OK")
open(os.path.join(out, "informe.txt"), "w").write("\n".join(lineas) + "\n")
print("\n".join(lineas))
sys.exit(1 if fallos else 0)
PY
