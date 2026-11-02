# Maintainer: Joaquín Espinosa (RipoTech) <https://github.com/Joaco2382>

pkgname=ripowall
pkgver=3.2.0
pkgrel=1
pkgdesc="Fondos animados de Wallpaper Engine (videos, web, presets y escenas) en GNOME 45+ sobre Wayland"
arch=('any')
url="https://github.com/Joaco2382/ripowall"
license=('GPL-3.0-only')
depends=(
    'python'
    'python-gobject'
    'gtk4'
    'libadwaita'
    'webkitgtk-6.0'
    'gst-plugins-base'
    'gst-plugins-good'
    'gst-libav'            # H.264: el formato de casi todos los videos del Workshop
    'gnome-shell>=45'
)
optdepends=(
    # escenas de Wallpaper Engine: linux-wallpaperengine-ripowall (engine/PKGBUILD, con los arreglos de RipoWall)
    # o, sin esos arreglos, linux-wallpaperengine-git del AUR
    'linux-wallpaperengine: escenas de Wallpaper Engine'
    'steam: suscribirse a fondos del Workshop de Wallpaper Engine'
)
provides=("${pkgname}")
conflicts=("${pkgname}-git")
source=("${pkgname}-${pkgver}.tar.gz::https://github.com/Joaco2382/ripowall/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('SKIP')

package() {
    cd "${srcdir}/${pkgname}-${pkgver}"

    # Programas (la GUI y el daemon importan los módulos desde su misma carpeta)
    local lib="${pkgdir}/usr/lib/${pkgname}"
    install -Dm755 hidamari_gui.py hidamari_daemon.py ripowall_renderer.py ripowall_diagnostics.py \
        wallpaper_engine_launcher.py -t "${lib}"
    install -Dm644 hidamari_core.py workshop_api.py -t "${lib}"
    install -dm755 "${pkgdir}/usr/bin"
    ln -s "/usr/lib/${pkgname}/hidamari_gui.py"          "${pkgdir}/usr/bin/ripowall-gui"
    ln -s "/usr/lib/${pkgname}/hidamari_gui.py"          "${pkgdir}/usr/bin/hidamari-gui"
    ln -s "/usr/lib/${pkgname}/hidamari_daemon.py"       "${pkgdir}/usr/bin/hidamari-daemon"
    ln -s "/usr/lib/${pkgname}/ripowall_renderer.py"     "${pkgdir}/usr/bin/ripowall-renderer"
    ln -s "/usr/lib/${pkgname}/ripowall_diagnostics.py"  "${pkgdir}/usr/bin/ripowall-diagnostics"
    ln -s "/usr/lib/${pkgname}/wallpaper_engine_launcher.py" "${pkgdir}/usr/bin/ripowall-we"

    # Extensión de GNOME Shell (se activa por usuario: gnome-extensions enable ripowall@ripotech.cl)
    install -Dm644 extension/ripowall@ripotech.cl/* \
        -t "${pkgdir}/usr/share/gnome-shell/extensions/ripowall@ripotech.cl"

    # Daemon (servicio de usuario) y acceso directo
    # (el servicio apunta a ~/.local/bin para install.sh; instalado como paquete, el daemon está en /usr/bin)
    sed 's|%h/.local/bin/|/usr/bin/|' hidamari-daemon.service | \
        install -Dm644 /dev/stdin "${pkgdir}/usr/lib/systemd/user/hidamari-daemon.service"
    install -Dm644 cl.ripotech.RipoWall.desktop "${pkgdir}/usr/share/applications/cl.ripotech.RipoWall.desktop"

    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
