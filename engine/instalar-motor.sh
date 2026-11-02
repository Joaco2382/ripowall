#!/usr/bin/env bash
# Instala el motor de escenas de RipoWall: linux-wallpaperengine de upstream en el commit fijo de motor.conf,
# con los parches de engine/patches/ (personajes "puppet" de Wallpaper Engine).
#   engine/instalar-motor.sh             instala o actualiza el motor
#   engine/instalar-motor.sh --revisar   solo dice qué motor hay instalado
#   engine/instalar-motor.sh --glfw-propio <versión>   (pruebas) sale con 0 si esa versión de GLFW obliga a
#                                         compilar la propia
# En Arch se construye el paquete linux-wallpaperengine-ripowall (engine/PKGBUILD) y pacman lo instala en lugar
# de linux-wallpaperengine(-git), pidiendo confirmación. En otras distros se compila en ~/.cache/ripowall/motor,
# se instala en ~/.local/share/ripowall/motor y se deja el comando linux-wallpaperengine en ~/.local/bin.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=motor.conf
. "$DIR/motor.conf"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/ripowall/motor"
DESTINO="${XDG_DATA_HOME:-$HOME/.local/share}/ripowall/motor"
BIN="$HOME/.local/bin"
MARCA="$DESTINO/ripowall-motor.txt"
PARCHES=("$DIR"/patches/*.patch)
# GLFW 3.4 (X11 + Wayland), para distros cuyo GLFW es anterior: Ubuntu 24.04 trae 3.3 armado solo para X11, y
# así el motor abriría su ventana por X11 (Xwayland) y la extensión no la reconocería como suya
GLFW_REPO=https://github.com/glfw/glfw.git
GLFW_TAG=3.4

# commit + huella de los parches: si cambia cualquiera de los dos, hay que reinstalar
version_esperada() {
    echo "$MOTOR_COMMIT"
    sha256sum "${PARCHES[@]}" | awk '{print $1}'
}

revisar() {
    if command -v pacman >/dev/null && pacman -Q linux-wallpaperengine-ripowall >/dev/null 2>&1; then
        echo "Motor de RipoWall instalado como paquete: $(pacman -Q linux-wallpaperengine-ripowall)"
        return 0
    fi
    if [ -f "$MARCA" ]; then
        if [ "$(cat "$MARCA")" != "$(version_esperada)" ]; then
            echo "Motor de RipoWall desactualizado en $DESTINO: correr engine/instalar-motor.sh"
            return 1
        fi
        # la marca sola no alcanza: el motor o su comando pueden haberse borrado después
        if [ ! -x "$DESTINO/linux-wallpaperengine" ] || [ ! -x "$BIN/linux-wallpaperengine" ]; then
            echo "Motor de RipoWall incompleto (falta $DESTINO/linux-wallpaperengine o $BIN/linux-wallpaperengine): correr engine/instalar-motor.sh"
            return 1
        fi
        echo "Motor de RipoWall al día en $DESTINO"
        return 0
    fi
    if command -v linux-wallpaperengine >/dev/null; then
        echo "Hay un linux-wallpaperengine sin los parches de RipoWall ($(command -v linux-wallpaperengine))"
    else
        echo "No hay motor de escenas instalado"
    fi
    return 1
}

instalar_arch() {
    local trabajo="$CACHE/paquete"
    rm -rf "$trabajo"
    mkdir -p "$trabajo"
    # makepkg busca las fuentes locales junto al PKGBUILD
    cp "$DIR/PKGBUILD" "${PARCHES[@]}" "$trabajo/"
    (cd "$trabajo" && makepkg --syncdeps --install --needed)
}

# Dependencias para compilar el motor (las de su README + Wayland), con el gestor de paquetes de la distro
instalar_dependencias() {
    if command -v apt-get >/dev/null; then
        sudo apt-get update && sudo apt-get install -y git pkg-config build-essential cmake \
            libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev libgl-dev libglew-dev freeglut3-dev libsdl2-dev \
            liblz4-dev libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libxxf86vm-dev libglm-dev \
            libglfw3-dev libmpv-dev libpulse-dev libfftw3-dev libfreetype-dev \
            libwayland-dev wayland-protocols libegl-dev libxkbcommon-dev
    elif command -v dnf >/dev/null; then
        sudo dnf install -y git pkgconf-pkg-config gcc gcc-c++ cmake make \
            libXrandr-devel libXinerama-devel libXcursor-devel libXi-devel mesa-libGL-devel mesa-libEGL-devel \
            glew-devel freeglut-devel SDL2-devel lz4-devel ffmpeg-free-devel libXxf86vm-devel glm-devel glfw-devel \
            mpv-devel pulseaudio-libs-devel fftw-devel gmp-devel freetype-devel \
            wayland-devel wayland-protocols-devel libxkbcommon-devel
    elif command -v zypper >/dev/null; then
        sudo zypper install -y git pkg-config gcc-c++ cmake make libXrandr-devel libXinerama-devel \
            libXcursor-devel libXi-devel Mesa-libGL-devel Mesa-libEGL-devel glew-devel freeglut-devel \
            libSDL2-devel liblz4-devel ffmpeg-7-libavcodec-devel ffmpeg-7-libavformat-devel \
            ffmpeg-7-libavutil-devel ffmpeg-7-libswscale-devel libXxf86vm-devel glm-devel libglfw-devel \
            mpv-devel libpulse-devel fftw3-devel freetype2-devel wayland-devel wayland-protocols-devel \
            libxkbcommon-devel
    else
        echo "Gestor de paquetes no reconocido: instala a mano las dependencias de" >&2
        echo "  https://github.com/Almamu/linux-wallpaperengine#-installation" >&2
        return 1
    fi
}

# 0 si la versión de GLFW es anterior a 3.4 (hay que compilar la propia)
necesita_glfw_propio() {
    [ -z "$1" ] && return 0
    [ "$(printf '%s\n%s\n' "$1" "$GLFW_TAG" | sort -V | head -1)" != "$GLFW_TAG" ]
}

# GLFW 3.4 propio, dentro de la carpeta del motor (el comando del motor lo carga con LD_LIBRARY_PATH);
# no toca los paquetes del sistema
instalar_glfw_propio() {
    local fuente="$CACHE/glfw" build="$CACHE/glfw-build"
    [ -d "$fuente/.git" ] || git clone --quiet "$GLFW_REPO" "$fuente"
    git -C "$fuente" fetch --quiet --tags origin
    git -C "$fuente" checkout --quiet --force "$GLFW_TAG"
    cmake -B "$build" -S "$fuente" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$DESTINO" \
        -DCMAKE_INSTALL_LIBDIR=lib -DBUILD_SHARED_LIBS=ON -DGLFW_BUILD_X11=ON -DGLFW_BUILD_WAYLAND=ON \
        -DGLFW_BUILD_EXAMPLES=OFF -DGLFW_BUILD_TESTS=OFF -DGLFW_BUILD_DOCS=OFF -Wno-dev
    cmake --build "$build" -j "$(nproc)"
    cmake --install "$build"
}

instalar_compilando() {
    local fuente="$CACHE/fuente" build="$CACHE/build"
    if [ "${RIPOWALL_SIN_DEPENDENCIAS:-}" != 1 ]; then
        instalar_dependencias || exit 1
    fi
    for programa in git cmake make c++ pkg-config; do
        command -v "$programa" >/dev/null || {
            echo "Falta $programa. Las dependencias para compilar el motor están en:" >&2
            echo "  https://github.com/Almamu/linux-wallpaperengine#-installation" >&2
            exit 1
        }
    done

    mkdir -p "$CACHE"
    [ -d "$fuente/.git" ] || git clone "$MOTOR_REPO" "$fuente"
    git -C "$fuente" fetch --quiet origin
    git -C "$fuente" checkout --quiet --force "$MOTOR_COMMIT"
    git -C "$fuente" clean --quiet -fdx
    git -C "$fuente" submodule update --init --recursive
    for parche in "${PARCHES[@]}"; do
        git -C "$fuente" apply --verbose "$parche"
    done

    cmake -B "$build" -S "$fuente" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$DESTINO" -Wno-dev \
        -DCMAKE_CXX_FLAGS="-Wno-builtin-macro-redefined" -DCMAKE_C_FLAGS="-Wno-builtin-macro-redefined"
    cmake --build "$build" -j "$(nproc)"
    rm -rf "$DESTINO"
    cmake --install "$build"
    chmod +x "$DESTINO/linux-wallpaperengine"
    if necesita_glfw_propio "$(pkg-config --modversion glfw3 2>/dev/null || true)"; then
        echo "GLFW del sistema anterior a $GLFW_TAG: se compila GLFW $GLFW_TAG (X11 + Wayland) para el motor"
        instalar_glfw_propio
    fi

    mkdir -p "$BIN"
    cat > "$BIN/linux-wallpaperengine" << EOF
#!/bin/bash
# Motor de escenas de RipoWall (engine/instalar-motor.sh)
export LD_LIBRARY_PATH="$DESTINO/lib:\$LD_LIBRARY_PATH"
cd "$DESTINO" && exec ./linux-wallpaperengine "\$@"
EOF
    chmod +x "$BIN/linux-wallpaperengine"
    version_esperada > "$MARCA"

    local encontrado
    encontrado="$(command -v linux-wallpaperengine || true)"
    # RipoWall busca primero en $BIN (la extensión y el catálogo), así que esto solo importa en la terminal
    if [ -n "$encontrado" ] && [ "$encontrado" != "$BIN/linux-wallpaperengine" ]; then
        echo "Nota: en la terminal, linux-wallpaperengine es $encontrado; RipoWall usa igual el de $BIN." >&2
    fi
}

case "${1:-}" in
    --revisar) revisar ;;
    --glfw-propio) necesita_glfw_propio "${2:-}" ;;
    "")
        if [ -f /etc/arch-release ] && command -v makepkg >/dev/null; then
            instalar_arch
        else
            instalar_compilando
        fi
        revisar
        ;;
    *)
        echo "Uso: $0 [--revisar]" >&2
        exit 2
        ;;
esac
