#!/usr/bin/env bash
# Prueba el reproductor (ripowall-renderer) y su control por D-Bus en un mutter SIN PANTALLA:
# nada aparece en el escritorio ni se toca la configuración real (bus, XDG y config de RipoWall aislados).
#   scripts/probar-renderer.sh <carpeta-salida> <video>
# Deja en la carpeta: renderer.log y describe-*.txt (estado de las acciones en cada paso).
# Termina con código 1 si algún paso no dio lo esperado.
set -euo pipefail
OUT="$1"; VIDEO="$2"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/config" "$T/data" "$T/cache" "$OUT"
printf '{"data_source": {"Default": "%s"}, "is_mute": true, "audio_volume": 40, "is_pause_when_maximized": true}\n' "$VIDEO" > "$T/ripowall.json"

XDG_CONFIG_HOME="$T/config" XDG_DATA_HOME="$T/data" XDG_CACHE_HOME="$T/cache" \
RIPOWALL_CONFIG="$T/ripowall.json" OUT="$OUT" REPO="$REPO" VIDEO="$VIDEO" \
dbus-run-session -- bash -c '
  set -u
  mutter --headless --wayland --no-x11 --virtual-monitor 1280x720 --wayland-display ripowall-prueba > "$OUT/mutter.log" 2>&1 &
  MUTTER=$!
  for i in $(seq 1 50); do [ -S "$XDG_RUNTIME_DIR/ripowall-prueba" ] && break; sleep 0.2; done
  WAYLAND_DISPLAY=ripowall-prueba python3 "$REPO/ripowall_renderer.py" > "$OUT/renderer.log" 2>&1 &
  REND=$!
  R="--session --dest cl.ripotech.RipoWall.Renderer --object-path /cl/ripotech/RipoWall/Renderer"
  for i in $(seq 1 50); do gdbus call $R --method org.gtk.Actions.List >/dev/null 2>&1 && break; sleep 0.2; done
  gdbus call $R --method org.gtk.Actions.DescribeAll > "$OUT/describe-inicio.txt"
  gdbus call $R --method org.gtk.Actions.SetState pausado "<true>" "{}" >/dev/null
  gdbus call $R --method org.gtk.Actions.SetState volumen "<int32 250>" "{}" >/dev/null
  gdbus call $R --method org.gtk.Actions.DescribeAll > "$OUT/describe-cambios.txt"
  gdbus call $R --method org.gtk.Actions.Activate cubierto "[<(0, 0, true)>]" "{}" >/dev/null
  gdbus call $R --method org.gtk.Actions.Activate recargar "[]" "{}" >/dev/null
  sleep 1
  kill $REND $MUTTER 2>/dev/null; wait 2>/dev/null || true
'
python3 -I - "$OUT" "$VIDEO" <<'PY'
import re, sys
out, video = sys.argv[1], sys.argv[2]
leer = lambda f: open(f"{out}/{f}", encoding="utf-8", errors="ignore").read()
def estado(txt, nombre):
    m = re.search(rf"'{nombre}': \((?:true|false), (?:signature )?'[^']*', \[<([^>]*)>\]\)", txt)
    return m.group(1) if m else None
casos = [
    ("al iniciar, silencio viene de la config (true)", estado(leer("describe-inicio.txt"), "silencio") == "true"),
    ("al iniciar, volumen viene de la config (40)", estado(leer("describe-inicio.txt"), "volumen") == "40"),
    ("al iniciar, no está pausado", estado(leer("describe-inicio.txt"), "pausado") == "false"),
    ("SetState pausado true queda en true", estado(leer("describe-cambios.txt"), "pausado") == "true"),
    ("volumen 250 se limita a 100", estado(leer("describe-cambios.txt"), "volumen") == "100"),
    ("armó 1 monitor", "1 monitor(es)" in leer("renderer.log")),
    ("cargó el video de la config", video in leer("renderer.log")),
    ("sin errores de reproducción", "error de reproducción" not in leer("renderer.log")),
]
fallos = 0
for texto, ok in casos:
    print(("OK    " if ok else "FALLA ") + texto)
    fallos += not ok
print(f"{len(casos) - fallos}/{len(casos)} OK")
sys.exit(1 if fallos else 0)
PY

