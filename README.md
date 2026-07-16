# RipoWall

**La forma más fácil de usar Wallpaper Engine en Linux.**

RipoWall integra Wallpaper Engine (Steam/Proton) + Hidamari en una experiencia plug-and-play para Linux GNOME con GUI nativa GTK4/Adwaita.

## Características

- 🖼️ **Galería visual** de wallpapers animados (~225+ MP4 del Steam Workshop)
- 🖥️ **Multi-monitor real** — wallpaper independiente por cada pantalla
- 🔄 **Rotación automática** cada 10 minutos (configurable)
- 🔍 **Búsqueda integrada** por nombre en tiempo real
- 🗑️ **Click derecho para eliminar** wallpapers directamente desde la GUI
- 🎮 **Lanzador de Wallpaper Engine** — abre el Workshop de Steam con un click
- 🔌 **Hotplug de monitores** — detecta pantallas nuevas al instante
- 🤫 **Sonido muteado** permanentemente (los wallpapers no emiten audio)
- 🚀 **Daemon systemd** — inicia con tu sesión, siempre corriendo
- 🌐 **Portable** — funciona en Arch, Ubuntu, Fedora, openSUSE

## Requisitos

- Linux con GNOME (Wayland o X11)
- Steam + Wallpaper Engine (para descargar wallpapers del Workshop)
- Hidamari (reproductor de video como fondo de escritorio)

## Instalación rápida

```bash
curl -fsSL https://ripotech.cl/ripowall/install.sh | bash
```

O manualmente:

```bash
git clone https://github.com/Joaco2382/ripowall.git
cd ripowall
./install.sh
```

### Arch Linux (AUR)

```bash
paru -S ripowall
```

## Uso

```bash
# Abrir la GUI de RipoWall
hidamari-gui

# Lanzar Wallpaper Engine (Steam Workshop)
ripowall-we --browse

# Estado de Wallpaper Engine
ripowall-we --status

# Detener Wallpaper Engine
ripowall-we --kill

# Monitor keep-alive (reinicia la UI si crashea)
ripowall-we --monitor
```

Desde la GUI: click en cualquier wallpaper para asignarlo al monitor seleccionado. Click derecho para eliminar. Botón de wallpaper en la barra superior para abrir el Steam Workshop.

## Arquitectura

```
Steam Workshop → Wallpaper Engine (Proton) → descarga MP4
                                                   ↓
                                          ~/Videos/Hidamari/ (symlinks)
                                                   ↓
                              Hidamari → reproduce como fondo real en GNOME
                                                   ↓
                              ┌──────────────────────┼──────────────────────┐
                              │                      │                      │
                        hidamari_core.py      hidamari-daemon        hidamari-gui
                        (módulo compartido)   (systemd user)         (GTK4 + Adwaita)
```

## Wallpaper Engine Launcher

RipoWall incluye `wallpaper_engine_launcher.py` que resuelve problemas comunes al ejecutar Wallpaper Engine en Linux/Proton:

- **Steam auth**: lanza siempre vía Steam para heredar los pipes de autenticación
- **CEF crash en Wayland**: aplica flags `--no-sandbox`, `--disable-gpu-sandbox`
- **UI que no abre**: detecta si `wallpaperui.exe` crasheó y lo reinicia automáticamente
- **Proton auto-detect**: encuentra la mejor versión de Proton disponible (CachyOS > GE > Experimental > Default)
- **Modo monitor**: keep-alive que reinicia la UI si se cae

## RipoTech

RipoWall es un producto de [RipoTech](https://ripotech.cl) — soluciones de software de alto rendimiento.

Creado por Joaquín Espinosa ([@Joaco2382](https://github.com/Joaco2382)).

## Licencia

GPL v3.0 — ver [LICENSE](LICENSE)
