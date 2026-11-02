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

# ── Dependencias ────────────────────────────────────────────────────────

install_deps() {
    echo -e "\n${YELLOW}Instalando dependencias...${RESET}"

    case "$DISTRO" in
        arch)
            sudo pacman -S --needed --noconfirm \
                python python-gobject python-pydbus python-vlc python-setproctitle \
                vlc yt-dlp libwnck3 webkitgtk-6.0 \
                gtk4 libadwaita steam 2>/dev/null || true
            ;;
        debian|ubuntu)
            sudo apt update
            sudo apt install -y \
                python3 python3-pip python3-gi python3-dbus \
                vlc yt-dlp libwnck-3-dev libwebkitgtk-6.0-dev \
                libgtk-4-dev libadwaita-1-dev \
                gir1.2-gtk-4.0 gir1.2-adw-1 steam-installer 2>/dev/null || true
            ;;
        fedora)
            sudo dnf install -y \
                python3 python3-pip python3-gobject python3-dbus \
                vlc yt-dlp libwnck3-devel webkitgtk6.0-devel \
                gtk4-devel libadwaita-devel steam 2>/dev/null || true
            ;;
        suse)
            sudo zypper install -y \
                python3 python3-pip python3-gobject python3-dbus-python \
                vlc yt-dlp libwnck3-devel webkitgtk6.0-devel \
                gtk4-devel libadwaita-devel steam 2>/dev/null || true
            ;;
        *)
            echo -e "${YELLOW}Distro no reconocida. Instala manualmente:${RESET}"
            echo "  - Python 3 + pip"
            echo "  - GTK4 + libadwaita"
            echo "  - VLC + python-vlc"
            echo "  - yt-dlp"
            echo "  - Steam + Wallpaper Engine"
            echo "  - Hidamari (AUR o compilar)"
            ;;
    esac
}

# ── Instalar Hidamari ───────────────────────────────────────────────────

install_hidamari() {
    echo -e "\n${YELLOW}Verificando Hidamari...${RESET}"

    if command -v hidamari &>/dev/null; then
        echo -e "${GREEN}✓ Hidamari ya instalado${RESET}"
        return
    fi

    case "$DISTRO" in
        arch)
            echo "Instalando Hidamari desde AUR..."
            if command -v paru &>/dev/null; then
                paru -S --noconfirm hidamari 2>/dev/null || {
                    echo -e "${RED}Error instalando Hidamari. Intentá manualmente: paru -S hidamari${RESET}"
                }
            elif command -v yay &>/dev/null; then
                yay -S --noconfirm hidamari 2>/dev/null || {
                    echo -e "${RED}Error instalando Hidamari. Intentá manualmente: yay -S hidamari${RESET}"
                }
            else
                echo -e "${YELLOW}No se encontro paru/yay. Instala Hidamari manualmente desde AUR.${RESET}"
            fi
            ;;
        *)
            echo -e "${YELLOW}Hidamari no esta en los repos de ${DISTRO}."
            echo "Compilalo desde: https://github.com/jeffshee/gnome-ext-hidamari${RESET}"
            ;;
    esac
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
    for f in hidamari_core.py hidamari-daemon hidamari-gui wallpaper_engine_launcher.py workshop_api.py; do
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
echo "  [1] Instalacion completa (dependencias + Hidamari + RipoWall)"
echo "  [2] Solo RipoWall (ya tenes Hidamari y dependencias)"
echo "  [3] Solo actualizar RipoWall scripts"
echo "  [4] Solo el motor de escenas (linux-wallpaperengine con los parches de RipoWall)"
read -rp "Elegi [1-4]: " choice

case "$choice" in
    1)
        install_deps
        install_hidamari
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
echo -e "\nPara abrir: ${BOLD}ripowall-gui${RESET} o busca 'RipoWall' en el menu GNOME."
echo -e "Para Wallpaper Engine: ${BOLD}ripowall-we --browse${RESET}"
echo -e "\nLanza Steam, abri RipoWall y hace click en el icono de wallpaper para"
echo -e "abrir Wallpaper Engine y descargar wallpapers del Workshop."
echo -e "\n${CYAN}RipoTech — ripotech.cl${RESET}"
