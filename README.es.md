# RipoWall

**Los fondos de Wallpaper Engine en GNOME (Linux): videos, fondos web, presets y escenas, animados en cada monitor.**

[English](README.md)

RipoWall toma los fondos a los que te suscribes en el Workshop de Steam de
[Wallpaper Engine](https://store.steampowered.com/app/431960/Wallpaper_Engine/) y los pone como fondo de tu escritorio
GNOME. Una pequeña extensión de GNOME Shell pone el reproductor propio de RipoWall detrás del escritorio: sin ventanas de
Wine/Proton, sin aparecer en Alt+Tab ni en la vista de actividades, y se pausa cuando una ventana tapa la pantalla.

## Qué hace

- **Todos los tipos de Wallpaper Engine:**
  - **video** (MP4 del Workshop);
  - **web** (HTML, con la API web de Wallpaper Engine: propiedades de usuario y pausa);
  - **presets** (un fondo web o escena con los ajustes e imágenes de otra persona);
  - **escenas**, dibujadas con [linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine) más los
    arreglos de RipoWall (ver [`engine/`](engine/README.md)): unas 200 de 204 escenas probadas se ven como su vista
    previa del Workshop.
- **Varios monitores:** un fondo distinto por monitor, de cualquier resolución y proporción (se recorta para cubrir,
  nunca se deforma). Conectar o desconectar un monitor no cambia los demás.
- **Se pausa sola** cuando una ventana maximizada o a pantalla completa tapa un monitor (no gasta procesador ni gráfica
  en lo que no se ve).
- **App GTK4/libadwaita:** galería con búsqueda, asignación por monitor, rotación automática, silencio y volumen, y un
  navegador del Workshop para buscar y suscribirse a fondos nuevos.
- **Funciona sola:** un servicio de usuario vigila la carpeta del Workshop (las suscripciones nuevas aparecen solas),
  rota los fondos y sigue los cambios de monitores. Si el reproductor se cae, la extensión lo vuelve a levantar.
- **`ripowall-diagnostics`** revisa todo (extensión, reproductor, códec de video, Workshop, Wayland) y dice cómo
  arreglar lo que falte.

## Requisitos

- **GNOME 45 a 51 en una sesión Wayland.** GNOME en X11 no funciona (la extensión lo avisa). Otros escritorios (KDE,
  Hyprland…) no son compatibles.
- **Wallpaper Engine en Steam.** RipoWall reproduce los fondos a los que estás suscrito. Hay que tener Wallpaper Engine
  comprado, y sus recursos hacen falta para las escenas.
- **Códec de video H.264 en GStreamer** (casi todos los videos del Workshop son H.264). Arch, Debian y Ubuntu lo traen
  con los paquetes que agrega el instalador. **Fedora no lo trae**: el instalador agrega OpenH264 desde el repositorio
  oficial de Fedora.
- Para escenas: el motor de escenas (lo instala `install.sh`, ver abajo) y una tarjeta gráfica con OpenGL 3.3.

## Probado en

Cada versión de esta tabla se probó en un contenedor limpio: extensión, reproductor, video, varios monitores, caída
del reproductor y desactivar/activar (`scripts/probar-gnome-docker.sh`, `scripts/probar-instalador-docker.sh`).

| Distribución | GNOME | Resultado |
|---|---|---|
| Fedora 39 | 45 | ✅ (necesita el códec H.264) |
| Ubuntu 24.04 LTS | 46 | ✅ |
| Fedora 41 | 47 | ✅ (necesita el códec H.264) |
| Debian 13 · Fedora 42 | 48 | ✅ (Fedora: necesita el códec H.264) |
| Fedora 43 | 49 | ✅ (necesita el códec H.264) |
| Ubuntu 26.04 · Fedora 44 | 50 | ✅ (Fedora: necesita el códec H.264) |
| Arch / CachyOS | 51 | ✅ (además en uso diario en un equipo real) |

No compatibles: GNOME 44 o anterior (Ubuntu 22.04, Debian 12), sesiones X11 y otros escritorios.

## Instalación

```bash
git clone https://github.com/Joaco2382/ripowall.git
cd ripowall
./install.sh          # opción [1]: dependencias + motor de escenas + RipoWall
```

Después **cierra sesión y vuelve a entrar** (GNOME carga las extensiones nuevas al iniciar sesión) y abre **RipoWall**
desde tus aplicaciones (o con `ripowall-gui`).

- **Arch Linux:** hay un `PKGBUILD` en el repositorio (`makepkg -si`) y otro para el motor de escenas con los arreglos,
  en `engine/`.
- **Motor de escenas:** en Arch, `install.sh` construye e instala el paquete `linux-wallpaperengine-ripowall`
  (escenas comprobadas). En otras distribuciones compila el motor en `~/.local` (necesita las dependencias de
  compilación que lista [el README de linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine)).
  **En Ubuntu y Debian el motor compila, pero las escenas todavía no se dibujan:** sus paquetes de GLFW y GLEW vienen
  solo para X11 (`libglfw3-wayland` arregla GLFW; GLEW está pendiente). Sin el motor, los videos, los fondos web y los
  presets funcionan igual; solo no se ofrecen escenas.

## Uso

1. Suscríbete a fondos en el Workshop de Steam (desde Steam, desde Wallpaper Engine o desde el navegador del Workshop
   de RipoWall). Steam los descarga.
2. Abre RipoWall, elige un monitor a la izquierda y haz clic en un fondo.

| Comando | Qué hace |
|---|---|
| `ripowall-gui` | Abre la app |
| `ripowall-diagnostics` | Revisa toda la instalación y sugiere arreglos |
| `systemctl --user status hidamari-daemon` | Estado del servicio de fondo |
| `journalctl --user -b \| grep ripowall` | Registro de la extensión y el reproductor |

## Limitaciones conocidas

- Las escenas están comprobadas en sistemas basados en Arch; en Ubuntu/Debian todavía no se dibujan (ver Instalación).
- 4 de las 204 escenas probadas todavía se ven distintas de su vista previa: le faltan funciones al motor (partículas
  hijas, la acumulación de `motionblur` y una niebla de partículas). Detalle en [`engine/README.md`](engine/README.md).
- Los fondos web con visualizador de audio se ven, pero sus barras todavía no se mueven: no se les entrega el audio
  del sistema.
- La interfaz de la app está en español por ahora.
- Los fondos de tipo «aplicación» de Wallpaper Engine (ejecutables) no son compatibles.

## Cómo funciona

```
Workshop de Steam ──► ~/.local/share/Steam/steamapps/workshop/content/431960/<id>/
                                   │
        hidamari_core (catálogo, config) ◄── ripowall-gui (GTK4) · hidamari-daemon (rotación, monitores)
                                   │ ~/.config/ripowall/config.json
                                   ▼
        ripowall-renderer: una ventana a pantalla completa por monitor
           video: GStreamer · web: WebKit (limitado a la carpeta del fondo) · escena: vista previa + motor
                                   │ D-Bus (pausa, silencio, volumen, escenas)
                                   ▼
        extensión de GNOME Shell ripowall@ripotech.cl
           lanza el reproductor (y linux-wallpaperengine para las escenas) como clientes Wayland privilegiados,
           esconde sus ventanas y pone un clon en vivo de cada una dentro del fondo del escritorio
```

Seguridad: los fondos web se cargan desde un esquema propio, `ripowall-fondo://`, que solo entrega archivos de la
carpeta de ese fondo. Así una página del Workshop no puede leer tus otros archivos.

## Desarrollo

```bash
python3 -m unittest discover -s tests            # pruebas unitarias, aislamiento de WebKit y gjs
scripts/probar-gnome-docker.sh ubuntu-24.04      # extensión + reproductor en otra versión de GNOME (Docker)
MONITORES="1920x1080 1280x1024" scripts/probar-gnome-docker.sh arch   # varios monitores
scripts/probar-instalador-docker.sh fedora-44    # install.sh de punta a punta
```

El CI revisa secretos (ggshield) y corre la suite de pruebas con GTK4/WebKit reales en cada push.

## Créditos y licencia

- Las escenas las dibuja [linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine) (GPL-3.0), de Almamu
  y sus colaboradores; RipoWall lo compila en un commit fijo con sus propios parches (`engine/patches/`).
- La idea de mostrar la ventana de un cliente como fondo de GNOME con un clon en vivo viene de
  [Hanabi](https://github.com/jeffshee/gnome-ext-hanabi); la extensión de RipoWall es código propio.
- RipoWall no está afiliado a Wallpaper Engine ni a Valve. Necesitas tu propia copia de Wallpaper Engine, y los fondos
  son de sus autores.

RipoWall es software libre bajo la [GNU GPL v3](LICENSE). Hecho por [RipoTech](https://ripotech.cl).
