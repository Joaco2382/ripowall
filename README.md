# RipoWall

**Wallpaper Engine wallpapers on GNOME (Linux): videos, web wallpapers, presets and scenes, animated on every monitor.**

[Español](README.es.md)

RipoWall takes the wallpapers you subscribe to in the Steam Workshop of
[Wallpaper Engine](https://store.steampowered.com/app/431960/Wallpaper_Engine/) and plays them as your GNOME desktop
background. A small GNOME Shell extension puts RipoWall's own player behind the desktop: no Wine/Proton window, nothing
in Alt+Tab or the overview, and it pauses when a window covers the screen.

## What it does

- **All Wallpaper Engine types:**
  - **video** (MP4 from the Workshop);
  - **web** wallpapers (HTML, with the Wallpaper Engine web API: user properties, pause);
  - **presets** (a web wallpaper or scene with someone's custom settings and images);
  - **scenes**, drawn with [linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine) plus RipoWall's
    fixes (see [`engine/`](engine/README.md)): about 200 of 204 scenes tested look like their Workshop preview.
- **Multi-monitor:** a different wallpaper per monitor, any resolution and aspect ratio (cropped to fill, never
  stretched). Plugging or unplugging a monitor keeps the others as they were.
- **Pauses by itself** when a maximized or fullscreen window covers a monitor (no CPU/GPU spent on what you can't see).
- **GTK4/libadwaita app:** gallery with search, per-monitor assignment, automatic rotation, mute/volume, and a
  Workshop browser to find and subscribe to new wallpapers.
- **Runs on its own:** a user service watches the Workshop folder (new subscriptions show up), rotates wallpapers and
  follows monitor changes. If the player crashes, the extension restarts it.
- **`ripowall-diagnostics`** checks everything (extension, player, video codec, Workshop, Wayland) and tells you how
  to fix what's missing.

## Requirements

- **GNOME 45 to 51 in a Wayland session.** GNOME on X11 is not supported (the extension tells you so).
  Other desktops (KDE, Hyprland…) are not supported.
- **Wallpaper Engine on Steam.** RipoWall plays the wallpapers you are subscribed to. You need to own Wallpaper
  Engine, and its assets are needed for scenes.
- **H.264 video codec in GStreamer** (almost every Workshop video is H.264). Arch, Debian and Ubuntu include it with
  the packages the installer adds. **Fedora doesn't ship it**: the installer adds OpenH264 from Fedora's own repository.
- For scenes: the scene engine (installed by `install.sh`, see below) and a GPU with OpenGL 3.3.

## Tested on

Every version below was tested in a clean container: extension, player, video playback, multi-monitor, crash
recovery, and enable/disable (`scripts/probar-gnome-docker.sh`, `scripts/probar-instalador-docker.sh`).

| Distribution | GNOME | Result |
|---|---|---|
| Fedora 39 | 45 | ✅ (needs the H.264 codec) |
| Ubuntu 24.04 LTS | 46 | ✅ |
| Fedora 41 | 47 | ✅ (needs the H.264 codec) |
| Debian 13 · Fedora 42 | 48 | ✅ (Fedora: needs the H.264 codec) |
| Fedora 43 | 49 | ✅ (needs the H.264 codec) |
| Ubuntu 26.04 · Fedora 44 | 50 | ✅ (Fedora: needs the H.264 codec) |
| Arch / CachyOS | 51 | ✅ (also used daily on real hardware) |

Not supported: GNOME 44 and older (Ubuntu 22.04, Debian 12), X11 sessions, other desktops.

## Install

```bash
git clone https://github.com/Joaco2382/ripowall.git
cd ripowall
./install.sh          # option [1]: dependencies + scene engine + RipoWall
```

Then **log out and back in** (GNOME loads new extensions at login) and open **RipoWall** from your apps
(or run `ripowall-gui`).

- **Arch Linux:** there is a `PKGBUILD` in the repository (`makepkg -si`) and another one for the patched scene
  engine in `engine/`.
- **Scene engine:** on Arch, `install.sh` builds and installs the package `linux-wallpaperengine-ripowall`
  (scenes verified). On other distributions it compiles the engine into `~/.local` (it needs the build dependencies
  listed in [linux-wallpaperengine's README](https://github.com/Almamu/linux-wallpaperengine)). **On Ubuntu and
  Debian the engine builds, but scenes don't render yet:** their GLFW and GLEW packages are built for X11 only
  (`libglfw3-wayland` fixes GLFW, GLEW is still pending). Without the engine, videos, web wallpapers and presets still
  work; scenes are just not offered.

## Usage

1. Subscribe to wallpapers in the Steam Workshop (from Steam, from Wallpaper Engine, or from RipoWall's Workshop
   browser). Steam downloads them.
2. Open RipoWall, pick a monitor on the left and click a wallpaper.

| Command | What it does |
|---|---|
| `ripowall-gui` | Opens the app |
| `ripowall-diagnostics` | Checks the whole setup and suggests fixes |
| `systemctl --user status hidamari-daemon` | Status of the background service |
| `journalctl --user -b \| grep ripowall` | Extension and player log |

## Known limitations

- Scenes are verified on Arch-based systems; on Ubuntu/Debian they don't render yet (see Install).
- 4 of the 204 scenes tested still render differently from their preview: features missing in the engine (child
  particles, `motionblur` accumulation, one particle fog). Details in [`engine/README.md`](engine/README.md).
- Web wallpapers with audio visualizers show up, but their bars don't move yet: system audio is not passed to them.
- The app's interface is in Spanish for now.
- Wallpaper Engine "application" wallpapers (executables) are not supported.

## How it works

```
Steam Workshop ──► ~/.local/share/Steam/steamapps/workshop/content/431960/<id>/
                                   │
        hidamari_core (catalog, config) ◄── ripowall-gui (GTK4) · hidamari-daemon (rotation, hotplug)
                                   │ ~/.config/ripowall/config.json
                                   ▼
        ripowall-renderer: one fullscreen window per monitor
           video: GStreamer · web: WebKit (sandboxed to the wallpaper's folder) · scene: preview + engine
                                   │ D-Bus (pause, mute, volume, scenes)
                                   ▼
        GNOME Shell extension ripowall@ripotech.cl
           launches the player (and linux-wallpaperengine for scenes) as privileged Wayland clients,
           keeps their windows hidden and puts a live clone of each one inside the desktop background
```

Security: web wallpapers are loaded from a private `ripowall-fondo://` scheme that only serves files from that
wallpaper's folder, so a Workshop page can't read your other files.

## Development

```bash
python3 -m unittest discover -s tests            # unit + WebKit isolation + gjs tests
scripts/probar-gnome-docker.sh ubuntu-24.04      # extension + player on another GNOME version (Docker)
MONITORES="1920x1080 1280x1024" scripts/probar-gnome-docker.sh arch   # several monitors
scripts/probar-instalador-docker.sh fedora-44    # install.sh end to end
```

CI runs a secret scan (ggshield) and the test suite with real GTK4/WebKit on every push.

## Credits and license

- Scenes are rendered by [linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine) (GPL-3.0) by Almamu
  and contributors; RipoWall builds it at a fixed commit with its own patches (`engine/patches/`).
- The idea of showing a client window as the GNOME background with a live clone comes from
  [Hanabi](https://github.com/jeffshee/gnome-ext-hanabi); RipoWall's extension is its own code.
- RipoWall is not affiliated with Wallpaper Engine or Valve. You need your own copy of Wallpaper Engine, and the
  wallpapers belong to their authors.

RipoWall is free software under the [GNU GPL v3](LICENSE). Made by [RipoTech](https://ripotech.cl).
