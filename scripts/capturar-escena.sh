#!/usr/bin/env bash
# Dibuja escenas de Wallpaper Engine con linux-wallpaperengine en un mutter SIN PANTALLA (monitor
# virtual, GPU real) y guarda una captura de cada una. No abre nada en el escritorio ni toca la
# configuración real (dbus y XDG_* aislados ANTES de dbus-run-session).
#   scripts/capturar-escena.sh <carpeta-salida> <id-o-carpeta> [<id-o-carpeta>...]
# Variables: CUADROS (cuadros dibujados antes de la captura, def. 150 = 5 s a 30 FPS), ANCHO/ALTO (def. 1280x720),
# MOTOR (comando del motor, def. linux-wallpaperengine; sirve para probar un motor recién compilado),
# MOTOR_ARGS (opciones de la salida, justo después de --window; por ejemplo "--scaling fill", como la extensión).
# Sin pantalla real no hay vsync: sin --fps el motor dibuja cientos de cuadros por segundo.
# Cada escena tiene como máximo 40 s; si no captura en ese tiempo, queda como «sin-captura».
set -euo pipefail
OUT="$1"; shift
mkdir -p "$OUT"
OUT="$(realpath "$OUT")"   # absoluta: el motor puede cambiar de carpeta al arrancar
MOTOR="${MOTOR:-linux-wallpaperengine}"
ASSETS="${ASSETS:-$HOME/.local/share/Steam/steamapps/common/wallpaper_engine/assets}"
CUADROS="${CUADROS:-150}"; W="${ANCHO:-1280}"; H="${ALTO:-720}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/config" "$T/data" "$T/cache"

XDG_CONFIG_HOME="$T/config" XDG_DATA_HOME="$T/data" XDG_CACHE_HOME="$T/cache" XDG_SESSION_TYPE=wayland \
OUT="$OUT" MOTOR="$MOTOR" MOTOR_ARGS="${MOTOR_ARGS:-}" ASSETS="$ASSETS" CUADROS="$CUADROS" W="$W" H="$H" \
dbus-run-session -- bash -c '
  set -u
  mutter --headless --wayland --no-x11 --virtual-monitor "${W}x${H}" --wayland-display ripowall-captura \
    > "$OUT/mutter.log" 2>&1 &
  MUTTER=$!
  for i in $(seq 1 50); do [ -S "$XDG_RUNTIME_DIR/ripowall-captura" ] && break; sleep 0.2; done
  for esc in "$@"; do
    id="$(basename "$esc")"
    rm -f "$OUT/$id.png"
    inicio=$(date +%s%3N)
    WAYLAND_DISPLAY=ripowall-captura "$MOTOR" \
      --assets-dir "$ASSETS" --silent --no-audio-processing --disable-mouse --fps 30 \
      --window "0x0x${W}x${H}" $MOTOR_ARGS --screenshot "$OUT/$id.png" --screenshot-delay "$CUADROS" "$esc" \
      > "$OUT/$id.log" 2>&1 &
    PID_MOTOR=$!
    # El motor no se cierra solo tras la captura: se corta apenas el PNG está completo (o a los 40 s)
    estado="sin-captura"
    for i in $(seq 1 200); do
      if ! kill -0 $PID_MOTOR 2>/dev/null; then estado="se-cayó"; break; fi
      if [ -s "$OUT/$id.png" ]; then sleep 0.5; estado="captura-ok"; break; fi
      sleep 0.2
    done
    kill $PID_MOTOR 2>/dev/null; wait $PID_MOTOR 2>/dev/null; codigo=$?
    [ "$estado" = "se-cayó" ] && [ -s "$OUT/$id.png" ] && estado="captura-ok"
    echo "$id|$estado|$codigo|$(( $(date +%s%3N) - inicio ))ms"
  done
  kill $MUTTER 2>/dev/null; wait $MUTTER 2>/dev/null || true
' _ "$@"
