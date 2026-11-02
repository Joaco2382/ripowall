#!/usr/bin/env bash
# Prueba install.sh de punta a punta en otra distro (Docker): corre la instalación completa (opción 1) y después
# arranca GNOME Shell sin pantalla usando SOLO lo instalado (extensión en ~/.local/share, reproductor en
# ~/.local/bin), con un video de prueba. Usa las imágenes de scripts/probar-gnome-docker.sh (hay que correr esa
# primero para la distro). El motor de escenas no se compila acá (tarda mucho): se prueba aparte.
#   scripts/probar-instalador-docker.sh <distro> [carpeta-salida]
# Deja en la carpeta: instalar.log, shell.log e informe.txt. Termina con 1 si algo no dio lo esperado.
set -euo pipefail
DISTRO="${1:?distro}"
OUT="$(realpath -m "${2:-$(mktemp -d)}")"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
IMAGEN="ripowall-prueba:$DISTRO"
mkdir -p "$OUT"
docker image inspect "$IMAGEN" >/dev/null 2>&1 || { echo "falta la imagen $IMAGEN (scripts/probar-gnome-docker.sh $DISTRO)" >&2; exit 2; }
[ -s "$OUT/video.mp4" ] || ffmpeg -loglevel error -y -f lavfi -i testsrc2=size=1280x720:rate=30 -t 6 \
  -c:v libx264 -pix_fmt yuv420p "$OUT/video.mp4"

docker run --rm -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 -v "$REPO:/repo:ro" -v "$OUT:/out" "$IMAGEN" bash -c '
  set -u
  # En el contenedor se es root: sudo pasa la orden tal cual
  printf "#!/bin/sh\nexec \"\$@\"\n" > /usr/local/bin/sudo && chmod +x /usr/local/bin/sudo
  cp -r /repo /tmp/ripowall
  printf "#!/bin/sh\necho \"(prueba: el motor de escenas no se compila aquí)\"\n" > /tmp/ripowall/engine/instalar-motor.sh
  export HOME=/tmp/casa XDG_RUNTIME_DIR=/tmp/run XDG_CONFIG_HOME=/tmp/casa/.config GSETTINGS_BACKEND=keyfile
  mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME/glib-2.0/settings" && chmod 700 "$XDG_RUNTIME_DIR"
  cd /tmp/ripowall && printf "1\n" | XDG_SESSION_TYPE=wayland bash install.sh > /out/instalar.log 2>&1
  echo "SALIDA_INSTALADOR=$?" >> /out/instalar.log
  ls -la $HOME/.local/bin $HOME/.local/share/gnome-shell/extensions/ripowall@ripotech.cl >> /out/instalar.log 2>&1
  python3 $HOME/.local/bin/ripowall-diagnostics --help > /dev/null 2>&1 && echo "DIAGNOSTICO_EJECUTA=ok" >> /out/instalar.log
  # GNOME con lo instalado: sin RIPOWALL_RENDERER, la extensión busca ~/.local/bin/ripowall-renderer
  dbus-uuidgen --ensure 2>/dev/null; dbus-uuidgen --ensure=/etc/machine-id 2>/dev/null
  mkdir -p /run/dbus && dbus-daemon --system --fork; rm -rf /run/systemd
  python3 - <<PY
import json
p = "$HOME/.config/ripowall/config.json"
c = json.load(open(p)); c["data_source"] = {"Default": "/out/video.mp4"}; json.dump(c, open(p, "w"))
PY
  printf "[org/gnome/shell]\nenabled-extensions=[\047ripowall@ripotech.cl\047]\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version=\047999\047\n" \
    > "$XDG_CONFIG_HOME/glib-2.0/settings/keyfile"
  RIPOWALL_PRUEBA_CAPTURA=/out/captura.png dbus-run-session -- timeout 25 gnome-shell --headless --wayland \
    --no-x11 --virtual-monitor 1280x720 > /out/shell.log 2>&1 || true
' || true

python3 -I - "$OUT" <<'PY'
import os, sys
out = sys.argv[1]
leer = lambda f: open(os.path.join(out, f), encoding="utf-8", errors="replace").read() \
    if os.path.exists(os.path.join(out, f)) else ""
inst, log = leer("instalar.log"), leer("shell.log")
casos = [
    ("el instalador terminó bien", "SALIDA_INSTALADOR=0" in inst),
    ("instaló las dependencias (los paquetes existen en esta distro)", "dependencias listas" in inst),
    ("dejó el reproductor, la GUI y el diagnóstico",
     all(n in inst for n in ("ripowall-renderer", "ripowall-gui", "ripowall-diagnostics", "hidamari_core.py"))),
    ("el diagnóstico se ejecuta", "DIAGNOSTICO_EJECUTA=ok" in inst),
    ("GNOME activó la extensión instalada", "extensión activada" in log),
    ("lanzó el reproductor instalado", "reproductor iniciado: /tmp/casa/.local/bin/ripowall-renderer" in log),
    ("reprodujo el video", "/out/video.mp4" in log and "error de reproducción" not in log),
    ("sin errores de JavaScript", "JS ERROR" not in log and "Extension ripowall@ripotech.cl:" not in log),
]
lineas = [("OK    " if ok else "FALLA ") + t for t, ok in casos]
fallos = sum(not ok for _, ok in casos)
lineas.append(f"{len(casos) - fallos}/{len(casos)} OK")
open(os.path.join(out, "informe.txt"), "w").write("\n".join(lineas) + "\n")
print("\n".join(lineas))
sys.exit(1 if fallos else 0)
PY
