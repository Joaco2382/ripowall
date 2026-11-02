#!/usr/bin/env bash
# Prueba las escenas de Wallpaper Engine en otra distro (Docker), de punta a punta:
#   1. engine/instalar-motor.sh tal cual (dependencias con el gestor de la distro, compila el motor y, si hace
#      falta, GLFW 3.4);
#   2. el motor solo dibuja la escena (captura PNG, para comparar con su preview);
#   3. GNOME Shell (sin pantalla) con RipoWall: la extensión lanza el motor y pone su ventana como fondo.
# Usa la GPU del equipo (/dev/dri) y un servidor de audio (como en un escritorio real), los recursos de Wallpaper
# Engine de este PC (solo lectura) y una escena del Workshop de este PC.
#   scripts/probar-escenas-docker.sh <distro> <id-escena> [carpeta-salida]
# Necesita la imagen de scripts/probar-gnome-docker.sh para esa distro. Tarda (compila el motor).
# Deja en la carpeta: motor.log, motor.png, shell.log, captura.png e informe.txt. Sale con 1 si algo falla.
set -euo pipefail
DISTRO="${1:?distro}"; ESCENA="${2:?id de la escena}"
OUT="$(realpath -m "${3:-$(mktemp -d)}")"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORKSHOP="$HOME/.local/share/Steam/steamapps/workshop/content/431960"
ASSETS="$HOME/.local/share/Steam/steamapps/common/wallpaper_engine/assets"
IMAGEN="ripowall-prueba:$DISTRO"
mkdir -p "$OUT"
docker image inspect "$IMAGEN" >/dev/null 2>&1 || { echo "falta $IMAGEN (scripts/probar-gnome-docker.sh $DISTRO)" >&2; exit 2; }
[ -d "$WORKSHOP/$ESCENA" ] && [ -d "$ASSETS" ] || { echo "falta la escena $ESCENA o los recursos de WE" >&2; exit 2; }

docker run --rm --device /dev/dri -e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 -e ESCENA="$ESCENA" \
  -v "$REPO:/repo:ro" -v "$OUT:/out" -v "$WORKSHOP/$ESCENA:/escena/$ESCENA:ro" -v "$ASSETS:/assets:ro" \
  "$IMAGEN" bash -c '
  set -u
  printf "#!/bin/sh\nexec \"\$@\"\n" > /usr/local/bin/sudo && chmod +x /usr/local/bin/sudo
  # los espejos HTTP de Ubuntu a veces responden 403 desde Docker: HTTPS
  sed -i "s|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://archive.ubuntu.com|g" \
    /etc/apt/sources.list.d/*.sources 2>/dev/null || true
  export HOME=/tmp/casa XDG_RUNTIME_DIR=/tmp/run XDG_CONFIG_HOME=/tmp/casa/.config GSETTINGS_BACKEND=keyfile
  mkdir -p "$HOME" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME/glib-2.0/settings" "$XDG_CONFIG_HOME/ripowall" && chmod 700 "$XDG_RUNTIME_DIR"
  cp -r /repo /tmp/ripowall
  bash /tmp/ripowall/engine/instalar-motor.sh > /out/motor.log 2>&1; echo "INSTALAR=$?" >> /out/motor.log
  ldd "$HOME/.local/share/ripowall/motor/linux-wallpaperengine" 2>/dev/null | grep -i glfw >> /out/motor.log
  # audio: el motor se conecta al servidor de audio al arrancar (en un escritorio siempre hay uno)
  (command -v pulseaudio >/dev/null || (apt-get install -y -q --no-install-recommends pulseaudio || \
     dnf install -y -q pulseaudio || pacman -S --noconfirm pulseaudio) >/dev/null 2>&1) || true
  dbus-uuidgen --ensure 2>/dev/null; dbus-uuidgen --ensure=/etc/machine-id 2>/dev/null
  mkdir -p /run/dbus && dbus-daemon --system --fork; rm -rf /run/systemd
  # 2) el motor solo
  dbus-run-session -- bash -c "
    pulseaudio --daemonize=yes --exit-idle-time=-1 2>/dev/null
    gnome-shell --headless --wayland --no-x11 --virtual-monitor 1280x720 --wayland-display solo > /out/solo-shell.log 2>&1 &
    for i in \$(seq 1 50); do [ -S \$XDG_RUNTIME_DIR/solo ] && break; sleep 0.2; done
    WAYLAND_DISPLAY=solo XDG_SESSION_TYPE=wayland \$HOME/.local/bin/linux-wallpaperengine --assets-dir /assets \
      --silent --disable-mouse --fps 30 --window 0x0x1280x720 --scaling fill --screenshot /out/motor.png \
      --screenshot-delay 5 /escena/\$ESCENA > /out/motor-solo.log 2>&1 &
    for i in \$(seq 1 90); do [ -s /out/motor.png ] && break; sleep 1; done; sleep 1
    pkill -9 -f linux-wallpaperengine; pkill -f \"gnome-shell --headless\"; pulseaudio --kill 2>/dev/null; sleep 2; true
  "
  # 3) GNOME con RipoWall: la extensión lanza el motor (recursos de WE donde los busca la extensión)
  mkdir -p $HOME/.local/share/Steam/steamapps/common/wallpaper_engine
  ln -s /assets $HOME/.local/share/Steam/steamapps/common/wallpaper_engine/assets
  EXT=$HOME/.local/share/gnome-shell/extensions/ripowall@ripotech.cl
  mkdir -p "$EXT" && cp /repo/extension/ripowall@ripotech.cl/* "$EXT/"
  printf "{\"data_source\": {\"Default\": \"/escena/%s\"}, \"is_mute\": true, \"is_pause_when_maximized\": true}" \
    "$ESCENA" > "$XDG_CONFIG_HOME/ripowall/config.json"
  printf "[org/gnome/shell]\nenabled-extensions=[\047ripowall@ripotech.cl\047]\ndisable-user-extensions=false\nwelcome-dialog-last-shown-version=\047999\047\n" \
    > "$XDG_CONFIG_HOME/glib-2.0/settings/keyfile"
  RIPOWALL_RENDERER=/repo/ripowall_renderer.py RIPOWALL_PRUEBA_CAPTURA=/out/captura.png dbus-run-session -- bash -c "
    pulseaudio --daemonize=yes --exit-idle-time=-1 2>/dev/null
    timeout 30 gnome-shell --headless --wayland --no-x11 --virtual-monitor 1280x720 > /out/shell.log 2>&1
    pkill -9 -f linux-wallpaperengine; true
  "
' || true

python3 -I - "$OUT" "$ESCENA" <<'PY'
import os, sys
out, escena = sys.argv[1], sys.argv[2]
leer = lambda f: open(os.path.join(out, f), encoding="utf-8", errors="replace").read() \
    if os.path.exists(os.path.join(out, f)) else ""
motor, shell = leer("motor.log"), leer("shell.log")
casos = [
    ("instalar-motor.sh terminó bien (dependencias + compilación)", "INSTALAR=0" in motor),
    ("el motor quedó con un GLFW 3.4 o más nuevo", "libglfw.so.3" in motor),
    ("el motor solo dibujó la escena", os.path.getsize(os.path.join(out, "motor.png")) > 10000
     if os.path.exists(os.path.join(out, "motor.png")) else False),
    ("la extensión lanzó el motor", f"escena" in shell and "iniciado" in shell and "linux-wallpaperengine" in shell),
    ("la ventana del motor es el fondo", "clon de «wallpaperengine»" in shell),
    ("sin errores de JavaScript", "JS ERROR" not in shell and "Extension ripowall@ripotech.cl:" not in shell),
]
lineas = [("OK    " if ok else "FALLA ") + t for t, ok in casos]
fallos = sum(not ok for _, ok in casos)
lineas.append(f"{len(casos) - fallos}/{len(casos)} OK")
open(os.path.join(out, "informe.txt"), "w").write("\n".join(lineas) + "\n")
print("\n".join(lineas))
sys.exit(1 if fallos else 0)
PY
