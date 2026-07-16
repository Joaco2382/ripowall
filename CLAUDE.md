# CLAUDE.md — RipoWall

Proyecto RipoWall v3.1: launcher de Wallpaper Engine para Linux + GUI nativa GTK4 de gestion de wallpapers animados.

## Stack

- **Lenguaje:** Python 3.11+
- **GUI:** GTK4 + libadwaita (sin Glade/XML, todo programatico)
- **WebView:** WebKitGTK 6.0 (`webkitgtk-6.0`) para WorkshopBrowser integrado
- **DBus:** pydbus + gdbus para Mutter DisplayConfig y Hidamari
- **Systemd:** servicios user para daemon y rotacion
- **Proton:** CachyOS SLR (o cualquier Proton compatible)

## Arquitectura v3.1

```
wallpaper_engine_launcher.py  ← Lanza WE via Steam/Proton (portable, auto-detecta todo)
hidamari_core.py              ← Modulo compartido: catalogo, monitores, DBus, config, WE API
hidamari-daemon               ← Servicio systemd: rotacion cada 10 min, hotplug, Workshop watcher
hidamari-gui                  ← App GTK4 + Adwaita: galeria GridView, sidebar monitores, busqueda, WorkshopBrowser WebView
```

### Componentes de la GUI (hidamari-gui)

| Clase / Seccion | Proposito |
|----------------|-----------|
| `RipoWallApp` | Punto de entrada, Gtk.Application |
| `RipoWallWindow` | Ventana principal: sidebar, galeria, barra de herramientas |
| `WorkshopBrowser(Adw.Dialog)` | WebView nativo del Steam Workshop (busca y subscribe sin Proton) |
| `MonitorRow` | Sidebar: icono y nombre del monitor, asignacion actual |

### Flujo de suscripcion WorkshopBrowser

```
WorkshopBrowser (WebKit 6.0) → steamcommunity.com/app/431960/workshop/
        │
        ├─ Usuario navega, busca, filtra
        ├─ Click en Subscribe → POST a API web de Steam Community
        │
        ▼
Steam cliente detecta suscripcion → descarga MP4
        │
        ▼
hidamari-daemon (watcher) detecta nuevos archivos
        │
        ▼
hidamari_core: get_all_wallpapers() → symlinks planos en ~/Videos/Hidamari/
        │
        ▼
Hidamari reproduce como fondo de escritorio GNOME
```

## Flujo general

```
Steam Workshop (WebView o app WE) → MP4 en workshop/content/431960/
                                         ↓
                            hidamari_core: get_all_wallpapers()
                                         ↓
                            ~/Videos/Hidamari/ (symlinks planos)
                                         ↓
                            Hidamari → reproduce en escritorio GNOME
                                         ↓
                            RipoWall GUI ← DBus → asigna/quita/controla
```

## WorkshopBrowser — Detalles tecnicos

- **WebView:** `WebKit.WebView()` nativo con GTK4, embebido en `Adw.Dialog`
- **URL:** `https://steamcommunity.com/app/431960/workshop/`
- **User-Agent:** Safari 17.0 en Linux x86_64 (evita bloqueos de navegador)
- **Seguridad:** Sin acceso al portapapeles (`javascript_can_access_clipboard = False`), developer extras deshabilitados
- **URI interception:** `decide-policy` captura `steam://` URIs → `xdg-open`
- **Cookies:** Persisten en el data storage de WebKit (sesion de Steam se mantiene)
- **Progress bar:** `Gtk.ProgressBar` sincronizada con `estimated-load-progress`
- **Fallback:** Boton en headerbar para abrir en navegador externo (`xdg-open`)
- **Ventaja clave:** Cero dependencia de Proton/Wine/CEF para buscar y suscribirse a wallpapers

## WebKitGTK 6.0 — Paquetes por distro

| Distro | Paquete |
|--------|---------|
| Arch | `webkitgtk-6.0` |
| Ubuntu/Debian | `libwebkitgtk-6.0-dev` |
| Fedora | `webkitgtk6.0-devel` |
| openSUSE | `webkitgtk6.0-devel` |

> La GUI requiere WebKitGTK 6.0 para el WorkshopBrowser. Si no esta disponible, la app funciona igual pero sin el navegador integrado (el boton del Workshop abrira el launcher de Proton como fallback).

## Paths clave (TODO portable, no hardcodeados)

| Que | Ruta |
|-----|------|
| Workshop WE | `~/.local/share/Steam/steamapps/workshop/content/431960/` |
| Config Hidamari | `~/.config/hidamari/config.json` |
| Symlinks planos | `$(xdg-user-dir VIDEOS)/Hidamari/` |
| Scripts RipoWall | `~/.local/bin/` |
| Systemd user | `~/.config/systemd/user/` |

## Convenciones de codigo

- Python: type hints en funciones publicas, docstrings en modulo y funciones exportadas
- Sin hardcodear paths (usar `Path.home()`, `xdg-user-dir`, deteccion runtime)
- `hidamari_core.py` no importa GTK (es compartido entre daemon y GUI)
- La GUI usa `threading` para operaciones bloqueantes + `GLib.idle_add` para UI updates
- La GUI es un solo archivo sin plantillas XML
- WebKit import: `import gi; gi.require_version('WebKit', '6.0'); from gi.repository import WebKit`

## Systemd services

| Servicio | Proposito | Activacion |
|----------|----------|-----------|
| `hidamari-daemon.service` | Daemon principal: rotacion, hotplug, watcher | `graphical-session.target` |
| `hidamari-rotate.service` | One-shot: ejecuta `hidamari-daemon --once` | Activado por timer |
| `hidamari-rotate.timer` | Timer cada 10 min | `timers.target` |

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
./hidamari-daemon --no-rotate     # sin rotacion automatica

# Systemd
systemctl --user status hidamari-daemon
journalctl --user -u hidamari-daemon -f
```

## Diagnostico

```bash
# Diagnostico completo del sistema
python3 ripowall_diagnostics.py
```

## Instalacion dev

```bash
./install.sh  # opcion 3 (solo scripts)
```

## Version

**v3.1.0** — Julio 2026
