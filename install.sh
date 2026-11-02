#!/usr/bin/env bash
# RipoWall — Instalador universal para Linux
# Compatible con: Arch, Ubuntu/Debian, Fedora, openSUSE
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

BIN_DIR="${HOME}/.local/bin"
APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons"
SYSTEMD_USER="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/ripowall"
EXT_UUID="ripowall@ripotech.cl"
EXT_DIR="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"

RIPOWALL_VERSION="3.2.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}${BOLD}═══ RipoWall v${RIPOWALL_VERSION} — Instalador ═══${RESET}"
echo -e "${CYAN}by RipoTech (ripotech.cl)${RESET}\n"

# ── Detectar distro ─────────────────────────────────────────────────────

detect_distro() {
    if [ -f /etc/arch-release ]; then
        echo "arch"
    elif [ -f /etc/debian_version ]; then
        echo "debian"
    elif [ -f /etc/fedora-release ]; then
        echo "fedora"
    elif [ -f /etc/SUSE-brand ]; then
        echo "suse"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
echo -e "Distro detectada: ${BOLD}${DISTRO}${RESET}"

# ── Requisitos del escritorio ───────────────────────────────────────────

# RipoWall necesita GNOME 45 o más nuevo en una sesión Wayland (la extensión pone el reproductor de fondo)
check_gnome() {
    local v
    v=$(gnome-shell --version 2>/dev/null | grep -oE "[0-9]+" | head -1 || true)
    if [ -z "$v" ]; then
        echo -e "${RED}✗ No se encontró GNOME Shell: RipoWall funciona solo en GNOME 45 o más nuevo.${RESET}"
        return 1
    fi
    if [ "$v" -lt 45 ]; then
        echo -e "${RED}✗ GNOME ${v}: RipoWall necesita GNOME 45 o más nuevo.${RESET}"
        return 1
    fi
    echo -e "GNOME Shell: ${BOLD}${v}${RESET} ${GREEN}✓${RESET}"
    if [ "${XDG_SESSION_TYPE:-}" = "x11" ]; then
        echo -e "${YELLOW}! Esta sesión es X11: los fondos animados necesitan GNOME en Wayland."
        echo -e "  Al cerrar sesión, elige «GNOME» (no «GNOME en Xorg») en el engranaje de la pantalla de inicio.${RESET}"
    fi
}

# ── Dependencias ────────────────────────────────────────────────────────

# Python + GTK4/Adwaita (GUI), WebKitGTK 6 (fondos web y login de Steam) y GStreamer con H.264 (videos)
install_deps() {
    echo -e "\n${YELLOW}Instalando dependencias...${RESET}"
    local ok=0
    case "$DISTRO" in
        arch)
            sudo pacman -S --needed --noconfirm \
                python python-gobject gtk4 libadwaita webkitgtk-6.0 \
                gst-plugins-base gst-plugins-good gst-libav || ok=1
            ;;
        debian)
            sudo apt-get update && sudo apt-get install -y \
                python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 gir1.2-soup-3.0 \
                libgtk-4-media-gstreamer gstreamer1.0-plugins-good gstreamer1.0-libav || ok=1
            ;;
        fedora)
            sudo dnf install -y \
                python3-gobject gtk4 libadwaita webkitgtk6.0 gstreamer1-plugins-good || ok=1
            # Fedora no trae H.264 (el formato de casi todos los videos del Workshop): OpenH264 es el de Fedora
            sudo dnf install -y --enablerepo=fedora-cisco-openh264 gstreamer1-plugin-openh264 || {
                echo -e "${YELLOW}! No se pudo instalar OpenH264: los videos no se van a reproducir."
                echo -e "  Alternativa: activar RPM Fusion e instalar gstreamer1-libav.${RESET}"
                ok=1
            }
            ;;
        suse)
            sudo zypper install -y \
                python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 typelib-1_0-WebKit-6_0 \
                gstreamer-plugins-good gstreamer-plugins-libav || ok=1
            ;;
        *)
            echo -e "${YELLOW}Distro no reconocida. Instala a mano:${RESET}"
            echo "  - Python 3 + PyGObject"
            echo "  - GTK4, libadwaita y WebKitGTK 6.0 (con sus typelibs de GObject Introspection)"
            echo "  - GStreamer con plugins good y un decodificador H.264 (gst-libav u openh264)"
            ;;
    esac
    if [ "$ok" -ne 0 ]; then
        echo -e "${RED}✗ Algunas dependencias no se instalaron (ver el error de arriba).${RESET}"
        return 1
    fi
    echo -e "  ${GREEN}✓${RESET} dependencias listas"
}

# ── Motor de escenas (linux-wallpaperengine con los parches de RipoWall) ─

install_motor() {
    echo -e "\n${YELLOW}Instalando el motor de escenas (linux-wallpaperengine + parches de RipoWall)...${RESET}"
    if "${SCRIPT_DIR}/engine/instalar-motor.sh"; then
        echo -e "  ${GREEN}✓${RESET} motor de escenas listo"
    else
        echo -e "  ${RED}✗${RESET} no se pudo instalar el motor: las escenas de Wallpaper Engine no se van a ver."
        echo -e "      Revisar el error de arriba y correr: ${BOLD}engine/instalar-motor.sh${RESET}"
        return 1
    fi
}

# ── Instalar scripts de RipoWall ────────────────────────────────────────

install_ripowall() {
    echo -e "\n${YELLOW}Instalando RipoWall...${RESET}"

    mkdir -p "$BIN_DIR" "$APPS_DIR" "$CONFIG_DIR" "$SYSTEMD_USER"

    # Scripts
    for f in hidamari_core.py hidamari-daemon hidamari-gui wallpaper_engine_launcher.py workshop_api.py \
             ripowall_diagnostics.py; do
        if [ -f "${SCRIPT_DIR}/${f}" ]; then
            cp "${SCRIPT_DIR}/${f}" "$BIN_DIR/"
            chmod +x "$BIN_DIR/$f"
            echo -e "  ${GREEN}✓${RESET} $f → $BIN_DIR/"
        fi
    done

    # Reproductor propio (lo lanza la extensión de GNOME)
    cp "${SCRIPT_DIR}/ripowall_renderer.py" "$BIN_DIR/ripowall-renderer"
    chmod +x "$BIN_DIR/ripowall-renderer"
    echo -e "  ${GREEN}✓${RESET} ripowall-renderer → $BIN_DIR/"

    # Extensión de GNOME Shell (pone el reproductor como fondo de cada monitor)
    mkdir -p "$EXT_DIR"
    cp "${SCRIPT_DIR}/extension/${EXT_UUID}/"* "$EXT_DIR/"
    echo -e "  ${GREEN}✓${RESET} extensión ${EXT_UUID} → $EXT_DIR/"
    if gnome-extensions enable "$EXT_UUID"; then
        echo -e "  ${GREEN}✓${RESET} extensión activada (si es la primera vez: cerrar sesión y volver a entrar)"
    else
        echo -e "  ${YELLOW}!${RESET} no se pudo activar la extensión ahora: cerrar sesión, volver a entrar y correr:"
        echo -e "      gnome-extensions enable ${EXT_UUID}"
    fi

    # Nombre corto para abrir la app desde la terminal
    ln -sf "$BIN_DIR/hidamari-gui" "$BIN_DIR/ripowall-gui"
    ln -sf "$BIN_DIR/ripowall_diagnostics.py" "$BIN_DIR/ripowall-diagnostics"
    echo -e "  ${GREEN}✓${RESET} ripowall-gui → $BIN_DIR/"

    # Symlink ripowall CLI
    if [ -f "${SCRIPT_DIR}/wallpaper_engine_launcher.py" ]; then
        ln -sf "$BIN_DIR/wallpaper_engine_launcher.py" "$BIN_DIR/ripowall-we"
        chmod +x "$BIN_DIR/ripowall-we"
        echo -e "  ${GREEN}✓${RESET} ripowall-we → $BIN_DIR/"
    fi

    # Config default si no existe
    if [ ! -f "$CONFIG_DIR/config.json" ]; then
        cat > "$CONFIG_DIR/config.json" << 'EOF'
{
  "data_source": {},
  "mode": "MODE_VIDEO",
  "is_mute": true,
  "audio_volume": 50,
  "is_pause_when_maximized": true
}
EOF
        echo -e "  ${GREEN}✓${RESET} Config default creada"
    fi

    # Systemd user services
    for f in hidamari-daemon.service; do
        if [ -f "${SCRIPT_DIR}/${f}" ]; then
            cp "${SCRIPT_DIR}/${f}" "$SYSTEMD_USER/"
            echo -e "  ${GREEN}✓${RESET} $f → $SYSTEMD_USER/"
        fi
    done

    # Desktop entry
    cat > "$APPS_DIR/cl.ripotech.RipoWall.desktop" << EOF
[Desktop Entry]
Type=Application
Name=RipoWall
Comment=Gestiona wallpapers animados en Linux (RipoTech)
Exec=${BIN_DIR}/hidamari-gui
Icon=ripowall
Categories=GNOME;GTK;Video;Utility;
StartupNotify=true
Terminal=false
Keywords=wallpaper;animated;live;video;steam;workshop;
EOF
    echo -e "  ${GREEN}✓${RESET} cl.ripotech.RipoWall.desktop → $APPS_DIR/"
}

# ── Habilitar daemon ────────────────────────────────────────────────────

enable_daemon() {
    echo -e "\n${YELLOW}Configurando daemon...${RESET}"

    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable hidamari-daemon.service 2>/dev/null || true
    systemctl --user start hidamari-daemon.service 2>/dev/null || true

    echo -e "  ${GREEN}✓${RESET} Daemon habilitado (systemd user)"
}

# ── Main ────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Opciones:${RESET}"
echo "  [1] Instalacion completa (dependencias + motor de escenas + RipoWall)"
echo "  [2] Solo RipoWall (ya tienes las dependencias)"
echo "  [3] Solo actualizar RipoWall scripts"
echo "  [4] Solo el motor de escenas (linux-wallpaperengine con los parches de RipoWall)"
read -rp "Elegi [1-4]: " choice

# RipoWall necesita GNOME 45+ (opciones 1-3); el motor solo (4) se puede instalar igual
case "$choice" in
    1|2|3) check_gnome || exit 1 ;;
esac

case "$choice" in
    1)
        if ! install_deps; then
            echo -e "  ${YELLOW}!${RESET} se sigue con la instalación: revisa después con ${BOLD}ripowall-diagnostics${RESET}"
        fi
        # sin motor RipoWall igual sirve para videos y fondos web: la instalación completa sigue
        if ! install_motor; then
            echo -e "  ${YELLOW}!${RESET} se sigue con la instalación sin el motor de escenas"
        fi
        install_ripowall
        enable_daemon
        ;;
    2)
        install_ripowall
        enable_daemon
        ;;
    3)
        install_ripowall
        ;;
    4)
        install_motor
        ;;
    *)
        echo -e "${RED}Opcion invalida${RESET}"
        exit 1
        ;;
esac

echo -e "\n${GREEN}${BOLD}═══ RipoWall instalado ✓ ═══${RESET}"
echo -e "\nSi es la primera vez: ${BOLD}cierra sesión y vuelve a entrar${RESET} (GNOME carga la extensión al iniciar sesión)."
echo -e "Para abrir: ${BOLD}ripowall-gui${RESET} o busca «RipoWall» en las aplicaciones."
echo -e "Si algo no se ve: ${BOLD}ripowall-diagnostics${RESET} revisa todo y dice cómo arreglarlo."
echo -e "\nLos fondos salen de tus suscripciones del Workshop de Wallpaper Engine (Steam)."
echo -e "\n${CYAN}RipoTech — ripotech.cl${RESET}"
