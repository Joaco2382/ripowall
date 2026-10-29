# RipoWall

**La forma mas facil de usar Wallpaper Engine en Linux.**

RipoWall integra Wallpaper Engine (Steam/Proton) + Hidamari en una experiencia plug-and-play para Linux GNOME con GUI nativa GTK4/Adwaita.

## Caracteristicas

- Navegador integrado del Steam Workshop (WebView nativo WebKit 6.0) -- busca y suscribite a wallpapers sin salir de la app
- Galeria visual de wallpapers animados (~225+ MP4 del Steam Workshop)
- Multi-monitor real -- wallpaper independiente por cada pantalla
- Rotacion automatica cada 10 minutos (configurable)
- Busqueda integrada por nombre en tiempo real
- Click derecho para eliminar wallpapers directamente desde la GUI
- Lanzador de Wallpaper Engine -- abre el Workshop de Steam con un click
- Hotplug de monitores -- detecta pantallas nuevas al instante
- Sonido muteado permanentemente (los wallpapers no emiten audio)
- Daemon systemd -- inicia con tu sesion, siempre corriendo
- Portable -- funciona en Arch, Ubuntu, Fedora, openSUSE

## Requisitos

- Linux con GNOME (Wayland o X11)
- Steam + Wallpaper Engine (para descargar wallpapers del Workshop)
- Hidamari (reproductor de video como fondo de escritorio)

## Instalacion rapida

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

Desde la GUI: click en cualquier wallpaper para asignarlo al monitor seleccionado. Click derecho para eliminar. Boton de wallpaper en la barra superior para abrir el Steam Workshop.

## Arquitectura

```
                         ┌─────────────────────────────────────┐
                         │        Steam Workshop               │
                         │  (WebKit WebView en hidamari-gui)   │
                         │  steamcommunity.com/app/431960      │
                         └──────────────┬──────────────────────┘
                                        │ Subscribe (POST API)
                                        ▼
                         ┌─────────────────────────────────────┐
                         │      Steam Cliente (Proton)         │
                         │  Descarga MP4 del Workshop          │
                         │  ~/.local/share/Steam/steamapps/    │
                         │  workshop/content/431960/            │
                         └──────────────┬──────────────────────┘
                                        │
                                        ▼
                         ┌─────────────────────────────────────┐
                         │         hidamari_core.py            │
                         │  - Escanea archivos MP4              │
                         │  - Crea symlinks planos              │
                         │  - Config DBus + Mutter              │
                         │  - API compartida daemon/GUI         │
                         └──────────────┬──────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │                   │                   │
                    ▼                   ▼                   ▼
        ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
        │  hidamari-daemon │  │   hidamari-gui   │  │ wallp. engine    │
        │  (systemd user)  │  │ (GTK4 + Adwaita) │  │ launcher.py      │
        │                  │  │                  │  │                  │
        │ - Rotacion cada  │  │ - Galeria visual │  │ - Lanza WE via   │
        │   10 min          │  │ - Sidebar        │  │   Steam/Proton   │
        │ - Hotplug         │  │   monitores      │  │ - Keep-alive     │
        │ - Workshop        │  │ - WorkshopBrowser│  │ - Auto-deteccion │
        │   watcher         │  │   WebView        │  │   Proton         │
        └──────────────────┘  └──────────────────┘  └──────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              │ DBus
                              ▼
                    ┌──────────────────┐
                    │    Hidamari       │
                    │  Reproduce video  │
                    │  como fondo       │
                    │  escritorio GNOME │
                    └──────────────────┘
```

### Stack tecnologico

| Componente | Tecnologia |
|------------|-----------|
| Lenguaje | Python 3.11+ |
| GUI | GTK4 + libadwaita (100% programatica, sin XML/Glade) |
| WebView | WebKitGTK 6.0 (navegador Steam Workshop integrado) |
| DBus | pydbus + gdbus (Mutter DisplayConfig + Hidamari) |
| Systemd | Servicios user para daemon y rotacion |
| Proton | CachyOS SLR (o cualquier Proton compatible) |

## WorkshopBrowser -- Navegador integrado del Steam Workshop

RipoWall incluye un navegador WebKit nativo que carga el Steam Workshop sin necesidad de abrir Wallpaper Engine via Proton/Wine. Esto permite buscar, filtrar y suscribirse a wallpapers directamente desde la app, con cookies persistentes (la sesion de Steam se mantiene entre usos).

**Flujo de suscripcion:**

1. Abris la GUI de RipoWall, click en el icono de Steam Workshop
2. Se abre un dialogo con `steamcommunity.com/app/431960/workshop/` en WebKit
3. Si no hay sesion, Steam te pide login (te logueas una vez)
4. Navegas, buscas, filtras wallpapers y haces click en **Subscribe**
5. Steam cliente detecta la suscripcion y descarga los archivos MP4
6. El daemon de RipoWall detecta los nuevos wallpapers y aparecen en la galeria

**Ventajas sobre el launcher via Proton:**

- Cero overhead de Wine/Proton/CEF -- solo WebKit nativo
- No requiere que Wallpaper Engine este corriendo
- Las cookies persisten entre sesiones (WebKit data storage)
- Los enlaces `steam://` se interceptan y redirigen a `xdg-open`
- Incluye boton de fallback para abrir en navegador externo

### Seccion WebView

La integracion WebView usa WebKitGTK 6.0 (`webkitgtk-6.0` / `libwebkitgtk-6.0-dev` / `webkitgtk6.0-devel` segun distro) con la siguiente configuracion:

- **User-Agent:** Safari 17.0 en Linux (evita deteccion de navegador no soportado)
- **JavaScript:** habilitado, sin acceso al portapapeles del sistema
- **Developer extras:** deshabilitados (seguridad)
- **URI interception:** `steam://` URIs se capturan con `decide-policy` y se pasan a `xdg-open`
- **Progress bar:** integrada en el dialogo (GTK `ProgressBar`)

## Wallpaper Engine Launcher

RipoWall incluye `wallpaper_engine_launcher.py` que resuelve problemas comunes al ejecutar Wallpaper Engine en Linux/Proton:

- **Steam auth**: lanza siempre via Steam para heredar los pipes de autenticacion
- **CEF crash en Wayland**: aplica flags `--no-sandbox`, `--disable-gpu-sandbox`
- **UI que no abre**: detecta si `wallpaperui.exe` crasheo y lo reinicia automaticamente
- **Proton auto-detect**: encuentra la mejor version de Proton disponible (CachyOS > GE > Experimental > Default)
- **Modo monitor**: keep-alive que reinicia la UI si se cae

## RipoTech

RipoWall es un producto de [RipoTech](https://ripotech.cl) -- soluciones de software de alto rendimiento.

Creado por Joaquin Espinosa ([@Joaco2382](https://github.com/Joaco2382)).

## Licencia

GPL v3.0 -- ver [LICENSE](LICENSE)
