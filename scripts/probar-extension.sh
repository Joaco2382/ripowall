#!/usr/bin/env bash
# Prueba la extensión de RipoWall en un GNOME anidado (gnome-shell --devkit), sin tocar la sesión real:
# dconf y extensiones van en una carpeta temporal, así nada queda activado en el escritorio de verdad.
#   [FONDO=<ruta>] scripts/probar-extension.sh [segundos=25] [carpeta-de-salida]
# Deja en la carpeta de salida: shell.log (registro de GNOME anidado) y captura.png (a los 10 s).
#
# OJO (2026-10-29): las variables XDG_* tienen que estar puestas ANTES de dbus-run-session. Si se ponen
# adentro, el dconf-service que arranca el bus usa la configuración real y los gsettings pisan la sesión
# de verdad (pasó: dejó enabled-extensions = ['ripowall@ripotech.cl']). Por eso además se compara la
# configuración real antes y después, y si cambió se restaura y la prueba falla.
set -euo pipefail
SEG="${1:-25}"
OUT="${2:-$(mktemp -d)}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UUID="ripowall@ripotech.cl"
CLAVES=(enabled-extensions disable-user-extensions)
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/data/gnome-shell/extensions" "$T/config" "$T/cache" "$OUT"
ln -s "$REPO/extension/$UUID" "$T/data/gnome-shell/extensions/$UUID"
rm -f "$OUT/captura.png"
# Config de prueba: copia de la real (para no escribirla) con pausa por ventana maximizada activa
python3 -I - "$T/ripowall.json" <<'PY'
import json, os, sys
for src in ("~/.config/ripowall/config.json", "~/.config/hidamari/config.json"):
    try:
        cfg = json.load(open(os.path.expanduser(src), encoding="utf-8")); break
    except (OSError, json.JSONDecodeError):
        cfg = {}
cfg["is_pause_when_maximized"] = True
if os.environ.get("FONDO"):  # FONDO=<ruta>: ese fondo en todos los monitores
    cfg["data_source"] = {"Default": os.environ["FONDO"]}
json.dump(cfg, open(sys.argv[1], "w", encoding="utf-8"))
PY
# Ventana maximizada de prueba: aparece a los 12 s y se cierra a los 18 s
cat > "$T/maximizada.py" <<'PY'
import gi; gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
app = Gtk.Application(application_id="cl.ripotech.RipoWall.PruebaMaximizada")
def activar(a):
    w = Gtk.ApplicationWindow(application=a, title="Prueba maximizada"); w.maximize(); w.present()
    GLib.timeout_add_seconds(6, lambda: (a.quit(), False)[1])
app.connect("activate", activar); app.run([])
PY

declare -A ANTES
for k in "${CLAVES[@]}"; do ANTES[$k]="$(gsettings get org.gnome.shell "$k")"; done

XDG_DATA_HOME="$T/data" XDG_CONFIG_HOME="$T/config" XDG_CACHE_HOME="$T/cache" \
RIPOWALL_RENDERER="$REPO/ripowall_renderer.py" RIPOWALL_PRUEBA_CAPTURA="$OUT/captura.png" \
RIPOWALL_CONFIG="$T/ripowall.json" T="$T" \
dbus-run-session -- bash -c '
  set -u
  gsettings set org.gnome.shell disable-user-extensions false
  gsettings set org.gnome.shell enabled-extensions "[\"'"$UUID"'\"]"
  gsettings set org.gnome.shell welcome-dialog-last-shown-version "999"
  (sleep 12; WAYLAND_DISPLAY=ripowall-anidado python3 "$T/maximizada.py" >/dev/null 2>&1) &
  timeout '"$SEG"' gnome-shell --devkit --wayland --wayland-display ripowall-anidado > "'"$OUT"'/shell.log" 2>&1 || true
'

CAMBIO=0
for k in "${CLAVES[@]}"; do
  ahora="$(gsettings get org.gnome.shell "$k")"
  if [ "$ahora" != "${ANTES[$k]}" ]; then
    echo "¡La prueba cambió la configuración REAL ($k: ${ANTES[$k]} -> $ahora)! Se restaura." >&2
    gsettings set org.gnome.shell "$k" "${ANTES[$k]}"
    CAMBIO=1
  fi
done

echo "registro: $OUT/shell.log"
grep -aE "ripowall|JS ERROR|$UUID" "$OUT/shell.log" || echo "(sin líneas de ripowall en el registro)"
[ -f "$OUT/captura.png" ] && echo "captura: $OUT/captura.png" || echo "sin captura"
exit $CAMBIO
