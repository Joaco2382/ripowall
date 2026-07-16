# CLAUDE.md — RipoWall

Proyecto RipoWall: launcher de Wallpaper Engine para Linux + GUI nativa GTK4 de gestión de wallpapers animados.

## Stack
- **Lenguaje:** Python 3.11+
- **GUI:** GTK4 + libadwaita (sin Glade/XML, todo programático)
- **DBus:** gdbus para Mutter DisplayConfig y Hidamari
- **Systemd:** servicios user para daemon y rotación
- **Proton:** CachyOS SLR (o cualquier Proton compatible)

## Arquitectura

```
wallpaper_engine_launcher.py  ← Lanza WE via Steam/Proton (portable, auto-detecta todo)
hidamari_core.py              ← Módulo compartido: catálogo, monitores, DBus, config, WE API
hidamari-daemon               ← Servicio systemd: rotación, hotplug, Workshop watcher
hidamari-gui                  ← App GTK4: galería GridView, sidebar monitores, búsqueda
```

## Flujo

```
Steam Workshop → WE (Proton) → MP4 en workshop/content/431960/
                                     ↓
                        hidamari_core: get_all_wallpapers()
                                     ↓
                        ~/Videos/Hidamari/ (symlinks planos)
                                     ↓
                        Hidamari → reproduce en escritorio GNOME
                                     ↓
                        RipoWall GUI ← DBus → asigna/quita/controla
```

## Paths clave (TODO portable, no hardcodeados)

| Qué | Ruta |
|-----|------|
| Workshop WE | `~/.local/share/Steam/steamapps/workshop/content/431960/` |
| Config Hidamari | `~/.config/hidamari/config.json` |
| Symlinks planos | `$(xdg-user-dir VIDEOS)/Hidamari/` |
| Scripts RipoWall | `~/.local/bin/` |
| Systemd user | `~/.config/systemd/user/` |

## Convenciones de código

- Python: type hints en funciones públicas, docstrings en módulo y funciones exportadas
- Sin hardcodear paths (usar `Path.home()`, `xdg-user-dir`, detección runtime)
- `hidamari_core.py` no importa GTK (es compartido entre daemon y GUI)
- La GUI usa `threading` para operaciones bloqueantes + `GLib.idle_add` para UI updates
- La GUI es un solo archivo sin plantillas XML

## Comandos

```bash
# Test del core
python3 hidamari_core.py --test

# GUI
./hidamari-gui

# WE Launcher
python3 wallpaper_engine_launcher.py --status
python3 wallpaper_engine_launcher.py --browse
python3 wallpaper_engine_launcher.py --kill

# Daemon
./hidamari-daemon --once          # ejecutar una vez y salir
./hidamari-daemon --no-rotate     # sin rotación automática

# Systemd
systemctl --user status hidamari-daemon
journalctl --user -u hidamari-daemon -f
```

## Instalación dev

```bash
./install.sh  # opción 3 (solo scripts)
```
