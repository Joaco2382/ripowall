# Maintainer: Joaquin Espinosa <104966815+Joaco2382@users.noreply.github.com>
# Contributor: RipoTech <hola@ripotech.cl>

pkgname=ripowall
pkgver=3.2.0
pkgrel=1
pkgdesc="Gestiona wallpapers animados en Linux integrando Wallpaper Engine (Steam/Proton) con Hidamari"
arch=('any')
url="https://ripotech.cl/ripowall"
license=('GPL-3.0-only')
depends=(
    'python'
    'python-pydbus'
    'python-vlc'
    'python-setproctitle'
    'python-gobject'
    'gtk4'
    'webkitgtk-6.0'
    'libadwaita'
    'vlc'
    'yt-dlp'
    'hidamari'
)
optdepends=(
    'steam: Descargar wallpapers del Workshop'
    'proton-cachyos-slr: Mejor compatibilidad Proton para Wallpaper Engine'
    'python-pillow: Thumbnails de wallpapers'
)
provides=("${pkgname}")
conflicts=("${pkgname}-git")
source=("${pkgname}-${pkgver}.tar.gz::https://github.com/Joaco2382/ripowall/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('SKIP')

package() {
    cd "${srcdir}/${pkgname}-${pkgver}"

    # Scripts principales
    install -Dm755 hidamari_core.py         "${pkgdir}/usr/bin/hidamari_core.py"
    install -Dm755 hidamari-daemon          "${pkgdir}/usr/bin/hidamari-daemon"
    install -Dm755 hidamari-gui             "${pkgdir}/usr/bin/hidamari-gui"
    install -Dm755 wallpaper_engine_launcher.py "${pkgdir}/usr/bin/wallpaper_engine_launcher.py"
    install -Dm755 workshop_api.py           "${pkgdir}/usr/bin/workshop_api.py"
    install -Dm755 ripowall_diagnostics.py  "${pkgdir}/usr/bin/ripowall_diagnostics.py"

    # Symlink ripowall-we
    ln -s /usr/bin/wallpaper_engine_launcher.py "${pkgdir}/usr/bin/ripowall-we"

    # Systemd user services
    install -Dm644 hidamari-daemon.service   "${pkgdir}/usr/lib/systemd/user/hidamari-daemon.service"
    install -Dm644 hidamari-rotate.service   "${pkgdir}/usr/lib/systemd/user/hidamari-rotate.service"
    install -Dm644 hidamari-rotate.timer     "${pkgdir}/usr/lib/systemd/user/hidamari-rotate.timer"

    # Desktop entry
    install -Dm644 ripowall.desktop         "${pkgdir}/usr/share/applications/ripowall.desktop"

    # Licencia
    install -Dm644 LICENSE                  "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
