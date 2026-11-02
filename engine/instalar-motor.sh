#!/usr/bin/env bash
# Instala el motor de escenas de RipoWall: linux-wallpaperengine de upstream en el commit fijo de motor.conf,
# con los parches de engine/patches/ (personajes "puppet" de Wallpaper Engine).
#   engine/instalar-motor.sh             instala o actualiza el motor
#   engine/instalar-motor.sh --revisar   solo dice qué motor hay instalado
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

instalar_compilando() {
    local fuente="$CACHE/fuente" build="$CACHE/build"
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
    if [ "$encontrado" != "$BIN/linux-wallpaperengine" ]; then
        echo "Atención: el comando linux-wallpaperengine que se usa es $encontrado, no el de RipoWall." >&2
        echo "Poner $BIN antes en el PATH o desinstalar el otro motor." >&2
    fi
}

case "${1:-}" in
    --revisar) revisar ;;
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
