"""
hidamari_core.py — Módulo compartido para RipoWall.
Sin dependencias GTK. Usado tanto por el daemon como por la GUI.

API:
  Catálogo:     get_all_wallpapers(), search_wallpapers()
  Monitores:    get_connected_monitors()
  Config:       load_config(), save_config()
  DBus:         assign_video_to_monitor(), pause_playback(), start_playback(), ...
  Rotación:     pick_random_wallpapers()
  Daemon:       get_daemon_status(), daemon_start(), daemon_stop(), daemon_logs()
  Flat folder:  rebuild_flat_folder()
  Wallpaper Engine: launch_wallpaper_engine(), get_we_status(), kill_wallpaper_engine()
"""  # noqa: D100

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ── Funciones de path (portables) ───────────────────────────────────────────

def _xdg_user_dir(name: str) -> str:
    """Obtiene un directorio XDG usando xdg-user-dir, con fallback."""
    try:
        r = subprocess.run(
            ["xdg-user-dir", name],
            capture_output=True, text=True, timeout=3
        )
        path = r.stdout.strip()
        if path and os.path.isdir(os.path.dirname(path) if not os.path.isdir(path) else path):
            # Si no existe, crearlo
            os.makedirs(path, exist_ok=True)
            return path
    except Exception:
        pass
    # Fallbacks segun locale
    fallbacks = {
        "VIDEOS": os.path.join(Path.home(), "Videos"),
        "DESKTOP": os.path.join(Path.home(), "Desktop"),
        "DOWNLOAD": os.path.join(Path.home(), "Downloads"),
    }
    return fallbacks.get(name, os.path.join(Path.home(), name.capitalize()))


def _find_steam_workshop() -> str:
    """Detecta el directorio del Workshop de Steam, portable entre distros."""
    candidates = [
        os.path.join(Path.home(), ".local/share/Steam/steamapps/workshop/content/431960"),
        os.path.join(Path.home(), ".steam/steam/steamapps/workshop/content/431960"),
        os.path.join(Path.home(), ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/workshop/content/431960"),
        os.path.join(Path.home(), "snap/steam/common/.local/share/Steam/steamapps/workshop/content/431960"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    # Si no existe ninguno, devolver el default para que falle gracefully
    return candidates[0]


# ── Constantes ──────────────────────────────────────────────────────────────

WORKSHOP = _find_steam_workshop()
CONFIG_PATH = os.path.join(Path.home(), ".config/hidamari/config.json")
FLAT_DIR = os.path.join(_xdg_user_dir("VIDEOS"), "Hidamari")
THUMB_CACHE = os.path.join(Path.home(), ".cache/hidamari-gui/thumbnails")

DBUS_SERVER_BUS = "io.github.jeffshee.Hidamari.server"
DBUS_SERVER_PATH = "/io/github/jeffshee/Hidamari/server"
DBUS_SERVER_IFACE = "io.github.jeffshee.hidamari.server"

DBUS_PLAYER_BUS = "io.github.jeffshee.Hidamari.player"
DBUS_PLAYER_PATH = "/io/github/jeffshee/Hidamari/player"
DBUS_PLAYER_IFACE = "io.github.jeffshee.hidamari.player"


# ── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class Wallpaper:
    title: str
    path: str
    size_mb: float = 0.0
    workshop_id: str = ""
    preview_path: str | None = None

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        return isinstance(other, Wallpaper) and self.path == other.path


@dataclass
class MonitorInfo:
    connector: str          # 'eDP-1', 'HDMI-1'
    description: str        # 'CSO 15.6"'
    serial: str             # '0x00000001'
    model: str = ""         # GDK model name
    width: int = 0
    height: int = 0
    current_wallpaper: str = ""  # path del video actual


# ── Catálogo de Wallpapers ─────────────────────────────────────────────────

def get_all_wallpapers() -> list[Wallpaper]:
    """Escanea el Workshop de Steam y devuelve todos los wallpapers MP4."""
    results = []
    if not os.path.isdir(WORKSHOP):
        print(f"[core] Workshop no encontrado en {WORKSHOP}. "
              "¿Steam instalado? ¿Wallpaper Engine suscrito?", flush=True)
        return results
    try:
        for folder in os.listdir(WORKSHOP):
            path = os.path.join(WORKSHOP, folder)
            if not os.path.isdir(path):
                continue
            mp4s = [f for f in os.listdir(path) if f.endswith('.mp4')]
            if not mp4s:
                continue
            title = folder
            preview = None
            pj = os.path.join(path, "project.json")
            if os.path.exists(pj):
                try:
                    with open(pj, encoding='utf-8', errors='replace') as f:
                        data = json.load(f)
                    title = data.get("title", folder)
                except Exception:
                    pass
            # Buscar preview
            for ext in ('.jpg', '.png', '.gif', '.webp'):
                prev = os.path.join(path, f"preview{ext}")
                if os.path.exists(prev):
                    preview = prev
                    break
            for mp4 in sorted(mp4s):
                full = os.path.join(path, mp4)
                try:
                    size_mb = os.path.getsize(full) / (1024 * 1024)
                except OSError:
                    size_mb = 0
                results.append(Wallpaper(
                    title=title,
                    path=full,
                    size_mb=round(size_mb, 1),
                    workshop_id=folder,
                    preview_path=preview,
                ))
    except OSError:
        pass
    return sorted(results, key=lambda w: w.title.lower())


def search_wallpapers(query: str, wallpapers: list[Wallpaper] | None = None) -> list[Wallpaper]:
    """Filtra wallpapers por título (case-insensitive)."""
    if wallpapers is None:
        wallpapers = get_all_wallpapers()
    q = query.lower().strip()
    if not q:
        return wallpapers
    return [w for w in wallpapers if q in w.title.lower()]


# ── Monitores ───────────────────────────────────────────────────────────────

def get_connected_monitors() -> list[MonitorInfo]:
    """Devuelve los monitores conectados vía Mutter DisplayConfig DBus."""
    try:
        r = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
             "--object-path", "/org/gnome/Mutter/DisplayConfig",
             "--method", "org.gnome.Mutter.DisplayConfig.GetCurrentState"],
            capture_output=True, text=True, timeout=5
        )
        monitors = []
        seen = set()
        # Parsear: ('eDP-1', 'CSO', 'SNF601BS1-3', '0x00000000')
        for match in re.finditer(
            r"\('([^']+)',\s*'([^']*)',\s*'([^']*)',\s*'(0x[0-9a-fA-F]+)'\)",
            r.stdout
        ):
            conn, desc, serial, _edid = match.groups()
            key = f"{conn}:{serial}"
            if key not in seen:
                seen.add(key)
                monitors.append(MonitorInfo(
                    connector=conn,
                    description=desc,
                    serial=serial,
                ))

        # Obtener modos (resolución) para cada monitor
        for m in monitors:
            # Buscar resolución (primer modo con is-current)
            mode_match = re.search(
                rf"\('{re.escape(m.connector)}'[^)]+\).*?\('([^']+)',\s*(\d+),\s*(\d+),",
                r.stdout
            )
            if mode_match:
                m.width = int(mode_match.group(2))
                m.height = int(mode_match.group(3))

        return monitors
    except Exception as e:
        print(f"[core] Error detectando monitores: {e}", flush=True)
        return []


def get_display_layout() -> tuple:
    """Firma del layout actual: (conector, x, y, escala) por monitor lógico + modos activos.

    Cambia cuando se modifica la escala o la resolución aunque los conectores
    sigan siendo los mismos. Hidamari no redimensiona su ventana en ese caso
    (bug en base_player._on_size_changed), así que hay que recargar el player.
    """
    try:
        r = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
             "--object-path", "/org/gnome/Mutter/DisplayConfig",
             "--method", "org.gnome.Mutter.DisplayConfig.GetCurrentState"],
            capture_output=True, text=True, timeout=5, check=True
        )
        logical = re.findall(
            r"\((-?\d+), (-?\d+), ([\d.]+), (?:uint32 )?\d+, (?:true|false), \[\('([^']+)'",
            r.stdout
        )
        modes = re.findall(
            r"\('(\d+x\d+@[\d.]+)', \d+, \d+, [\d.]+, [\d.]+, \[[^\]]*\], \{[^}]*'is-current': <true>",
            r.stdout
        )
        return (tuple(sorted(logical, key=lambda l: l[3])), tuple(sorted(modes)))
    except Exception as e:
        print(f"[core] Error leyendo layout de pantallas: {e}", flush=True)
        return ()


# ── Config ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Carga config.json con manejo de errores."""
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[core] Config no encontrada en {CONFIG_PATH}", flush=True)
        return {}
    except json.JSONDecodeError as e:
        print(f"[core] Config corrupta: {e}", flush=True)
        return {}


def save_config(config: dict) -> bool:
    """Guarda config.json de forma atómica (write-temp + rename)."""
    try:
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
        return True
    except OSError as e:
        print(f"[core] Error guardando config: {e}", flush=True)
        return False


def sanitize_hidamari_config(config: dict) -> bool:
    """Corrige valores de config.json que rompen a Hidamari. Retorna True si cambió algo.

    - fade_interval: segundos entre pasos del fundido de volumen (default 0.1).
      Versiones viejas de RipoWall guardaban ahí la rotación (600) y pausar
      tardaba 10 minutos en hacer efecto.
    - audio_volume: con 0 el fundido nunca termina (paso 0) y pausar no hace nada.
      El silencio se maneja con is_mute, no con el volumen.
    - pause_when_maximized: clave equivocada; Hidamari lee is_pause_when_maximized.
    """
    changed = False
    fade = config.get("fade_interval")
    if not isinstance(fade, (int, float)) or not 0 < fade <= 1:
        config["fade_interval"] = 0.1
        changed = True
    vol = config.get("audio_volume")
    if not isinstance(vol, (int, float)) or vol <= 0:
        config["audio_volume"] = 50
        changed = True
    if "pause_when_maximized" in config:
        config.setdefault("is_pause_when_maximized", config["pause_when_maximized"])
        del config["pause_when_maximized"]
        changed = True
    return changed


# ── Ajustes propios de RipoWall ─────────────────────────────────────────────

SETTINGS_PATH = os.path.join(Path.home(), ".config/ripowall/settings.json")
DEFAULT_ROTATE_MINUTES = 10


def load_settings() -> dict:
    """Ajustes de RipoWall (no de Hidamari): rotate_minutes (0 = sin rotación)."""
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[core] Error leyendo {SETTINGS_PATH}: {e}", flush=True)
        return {}


def save_settings(settings: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_PATH)
        return True
    except OSError as e:
        print(f"[core] Error guardando ajustes: {e}", flush=True)
        return False


def get_rotate_minutes() -> int:
    val = load_settings().get("rotate_minutes", DEFAULT_ROTATE_MINUTES)
    return val if isinstance(val, int) and val >= 0 else DEFAULT_ROTATE_MINUTES


def get_current_wallpapers() -> dict[str, str]:
    """Devuelve {monitor: path_video} desde config.json."""
    config = load_config()
    return config.get("data_source", {})


# ── DBus Client (Hidamari Server) ──────────────────────────────────────────

def _dbus_call(dest: str, path: str, iface: str, method: str) -> bool:
    """Llama a un metodo DBus. Retorna True si OK, False si error."""
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", dest,
             "--object-path", path, "--method", f"{iface}.{method}"],
            capture_output=True, timeout=5, check=True
        )
        return True
    except Exception:
        return False


def is_server_running() -> bool:
    """Verifica si el servidor de Hidamari está corriendo."""
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", "org.freedesktop.DBus.Peer.Ping"],
            capture_output=True, timeout=3, check=True
        )
        return True
    except Exception:
        return False


def assign_video_to_monitor(video_path: str, monitor: str) -> bool:
    """Asigna un video a un monitor vía DBus (sin tocar config.json).
    Usa el método video() del servidor de Hidamari.

    monitor: nombre del conector ('eDP-1', 'HDMI-1') o 'Default'.
    """
    # Método 1: Intentar vía server.video() (más limpio)
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", f"{DBUS_SERVER_IFACE}.video",
             video_path, monitor],
            capture_output=True, timeout=5, check=True
        )
        # Guardar config.json para persistencia tras reinicio
        config = load_config()
        if config:
            config.setdefault("data_source", {})[monitor] = video_path
            config["mode"] = "MODE_VIDEO"
            save_config(config)
        return True
    except Exception:
        pass

    # Método 2: Fallback — editar config.json + reload_config
    try:
        config = load_config()
        if not config:
            return False
        config.setdefault("data_source", {})[monitor] = video_path
        config["mode"] = "MODE_VIDEO"
        save_config(config)

        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", f"{DBUS_SERVER_IFACE}.reload"],
            capture_output=True, timeout=5, check=True
        )
        return True
    except Exception:
        return False


def pause_playback() -> bool:
    """Pausa la reproducción."""
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", f"{DBUS_SERVER_IFACE}.pause_playback"],
            capture_output=True, timeout=3, check=True
        )
        return True
    except Exception:
        return False


def start_playback() -> bool:
    """Reanuda la reproducción."""
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", f"{DBUS_SERVER_IFACE}.start_playback"],
            capture_output=True, timeout=3, check=True
        )
        return True
    except Exception:
        return False


def _set_server_bool(prop: str, value: bool) -> bool:
    val = "<true>" if value else "<false>"
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", "org.freedesktop.DBus.Properties.Set",
             DBUS_SERVER_IFACE, prop, val],
            capture_output=True, timeout=3, check=True
        )
        return True
    except Exception as e:
        print(f"[core] Error cambiando {prop}: {e}", flush=True)
        return False


def set_mute(muted: bool) -> bool:
    """Mutea/desmutea el audio."""
    return _set_server_bool("is_mute", muted)


def set_pause_when_maximized(enabled: bool) -> bool:
    """Pausar el video cuando hay una ventana maximizada o en pantalla completa."""
    return _set_server_bool("is_pause_when_maximized", enabled)


def set_volume(vol: int) -> bool:
    """Ajusta volumen (0-100)."""
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", "org.freedesktop.DBus.Properties.Set",
             DBUS_SERVER_IFACE, "volume", f"<int32 {vol}>"],
            capture_output=True, timeout=3, check=True
        )
        return True
    except Exception:
        return False


def _parse_gdbus_props(text: str) -> dict:
    """Parsea la salida de gdbus GetAll: ({'is_mute': <true>, 'volume': <0>, 'mode': <'MODE_VIDEO'>},)"""
    props = {}
    for key, val in re.findall(r"'(\w+)':\s*<([^>]*)>", text):
        if val in ("true", "false"):
            props[key] = val == "true"
        elif re.fullmatch(r"(?:int32\s+)?-?\d+", val):
            props[key] = int(val.split()[-1])
        else:
            props[key] = val.strip("'")
    return props


def get_server_properties() -> dict:
    """Obtiene todas las propiedades del servidor Hidamari."""
    try:
        r = subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", "org.freedesktop.DBus.Properties.GetAll",
             DBUS_SERVER_IFACE],
            capture_output=True, text=True, timeout=3, check=True
        )
        return _parse_gdbus_props(r.stdout)
    except Exception as e:
        print(f"[core] Error leyendo propiedades de Hidamari: {e}", flush=True)
        return {}


def reload_config() -> bool:
    """Recarga config.json en Hidamari via DBus server.

    IMPORTANTE: El server SI expone reload() en la interfaz hidamari.server.
    El player NO tiene interfaz custom — llamar a player.reload_config
    siempre fallaba silenciosamente (ServiceUnknown).
    """
    try:
        subprocess.run(
            ["gdbus", "call", "--session", "--dest", DBUS_SERVER_BUS,
             "--object-path", DBUS_SERVER_PATH,
             "--method", f"{DBUS_SERVER_IFACE}.reload"],
            capture_output=True, timeout=5, check=True
        )
        return True
    except Exception:
        return False


# ── Rotación ────────────────────────────────────────────────────────────────

def pick_random_wallpapers(
    monitors: list[str],
    wallpapers: list[Wallpaper] | None = None,
    avoid: set[str] | None = None,
) -> dict[str, str]:
    """Selecciona wallpaper aleatorio distinto por monitor.

    Args:
        monitors: lista de nombres de monitor (o conectores)
        wallpapers: catálogo (si es None, se carga del Workshop)
        avoid: paths a evitar (wallpapers ya asignados)

    Returns:
        {monitor_name: video_path}
    """
    if wallpapers is None:
        wallpapers = get_all_wallpapers()
    if not wallpapers:
        return {}
    if avoid is None:
        avoid = set()

    available = [w for w in wallpapers if w.path not in avoid]
    if len(available) < len(monitors):
        available = list(wallpapers)  # fallback: permitir repetidos
    random.shuffle(available)

    result = {}
    for i, mon in enumerate(monitors):
        result[mon] = available[i % len(available)].path

    return result


# ── Daemon (systemd user) ──────────────────────────────────────────────────

def get_daemon_status() -> str:
    """Estado de systemd: 'active', 'activating', 'inactive', 'failed', 'unknown'..."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "hidamari-daemon.service"],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def daemon_start() -> bool:
    """Inicia el daemon y lo deja habilitado para los proximos inicios de sesion."""
    try:
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "hidamari-daemon.service"],
            capture_output=True, timeout=10, check=True
        )
        return True
    except Exception as e:
        print(f"[core] Error iniciando el daemon: {e}", flush=True)
        return False


def daemon_stop() -> bool:
    """Detiene el daemon."""
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "hidamari-daemon.service"],
            capture_output=True, timeout=10, check=True
        )
        return True
    except Exception:
        return False


def daemon_restart() -> bool:
    """Reinicia el daemon."""
    try:
        subprocess.run(
            ["systemctl", "--user", "restart", "hidamari-daemon.service"],
            capture_output=True, timeout=15, check=True
        )
        return True
    except Exception:
        return False


def daemon_logs(lines: int = 50) -> list[str]:
    """Últimas N líneas de log del daemon."""
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", "hidamari-daemon.service",
             "--no-pager", "-n", str(lines), "-o", "cat"],
            capture_output=True, text=True, timeout=5
        )
        return [l for l in r.stdout.strip().split('\n') if l]
    except Exception:
        return ["Error obteniendo logs"]


# ── Flat Folder ─────────────────────────────────────────────────────────────

def rebuild_flat_folder() -> int:
    """Regenera symlinks en ~/Vídeos/Hidamari/. Retorna cantidad creada."""
    os.makedirs(FLAT_DIR, exist_ok=True)
    wallpapers = get_all_wallpapers()
    current_paths = {w.path for w in wallpapers}

    # Limpiar symlinks rotos
    try:
        for f in os.listdir(FLAT_DIR):
            p = os.path.join(FLAT_DIR, f)
            if os.path.islink(p):
                if not os.path.exists(p) or os.path.realpath(p) not in current_paths:
                    os.unlink(p)
    except OSError:
        pass

    # Crear symlinks
    existing_dsts = set()
    try:
        for f in os.listdir(FLAT_DIR):
            p = os.path.join(FLAT_DIR, f)
            if os.path.islink(p) and os.path.exists(p):
                existing_dsts.add(os.path.realpath(p))
    except OSError:
        pass

    count = 0
    for wp in wallpapers:
        if wp.path in existing_dsts:
            count += 1
            continue
        safe = (wp.title.replace("/", "-").replace(":", " -")
                .replace("?", "").replace("*", "").replace('"', "'")[:120])
        ext = os.path.splitext(wp.path)[1]
        dst = os.path.join(FLAT_DIR, f"{safe}{ext}")
        if os.path.exists(dst):
            base = os.path.join(FLAT_DIR, safe)
            n = 2
            while os.path.exists(f"{base}_{n}{ext}"):
                n += 1
            dst = f"{base}_{n}{ext}"
        # Limpiar symlink roto si existe
        if os.path.islink(dst):
            try:
                os.unlink(dst)
            except OSError:
                pass
        try:
            os.symlink(wp.path, dst)
            count += 1
        except OSError:
            pass
    return count


# ── Delete / Unsubscribe ─────────────────────────────────────────────────────

def delete_wallpaper_files(workshop_id: str) -> bool:
    """Mueve la carpeta del workshop a la papelera (~/.local/share/Trash/files/).

    Args:
        workshop_id: ID del workshop (nombre de la carpeta dentro de WORKSHOP)

    Returns:
        True si se movio exitosamente.
    """
    workshop_folder = os.path.join(WORKSHOP, workshop_id)
    if not os.path.isdir(workshop_folder):
        return False

    trash_files = os.path.expanduser("~/.local/share/Trash/files")
    trash_info = os.path.expanduser("~/.local/share/Trash/info")
    os.makedirs(trash_files, exist_ok=True)
    os.makedirs(trash_info, exist_ok=True)

    trash_dst = os.path.join(trash_files, workshop_id)

    # Si ya existe en la papelera, borrarlo antes
    if os.path.exists(trash_dst):
        shutil.rmtree(trash_dst)

    try:
        os.rename(workshop_folder, trash_dst)
    except OSError:
        shutil.move(workshop_folder, trash_dst)

    # Crear archivo .trashinfo (especificacion FreeDesktop)
    info_path = os.path.join(trash_info, f"{workshop_id}.trashinfo")
    try:
        with open(info_path, "w") as f:
            f.write("[Trash Info]\n")
            f.write(f"Path={workshop_folder}\n")
            f.write(f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    except OSError:
        pass

    # Limpiar thumbnails cacheados
    thumb_path = os.path.join(THUMB_CACHE, f"{workshop_id}.png")
    if os.path.exists(thumb_path):
        try:
            os.remove(thumb_path)
        except OSError:
            pass

    return True


def try_unsubscribe(workshop_id: str) -> bool:
    """Intenta desuscribir un wallpaper del Workshop de Steam.

    1. Intenta usar steamcmd si esta disponible.
    2. Fallback: intenta editar el archivo .acf de suscripciones.

    Args:
        workshop_id: ID del workshop item.

    Returns:
        True si se desuscribio o no habia forma de hacerlo (no es error bloqueante).
    """
    # Metodo 1: steamcmd
    steamcmd = None
    for candidate in ("steamcmd", "/usr/bin/steamcmd",
                       os.path.expanduser("~/.local/bin/steamcmd")):
        if shutil.which(candidate):
            steamcmd = candidate
            break

    if steamcmd:
        try:
            subprocess.run(
                [steamcmd, "+login", "anonymous",
                 "+workshop_download_item", "431960", workshop_id,
                 "+workshop_unsubscribe", "431960", workshop_id,
                 "+quit"],
                capture_output=True, timeout=30,
            )
            return True
        except Exception:
            pass

    # Metodo 2: editar archivo .acf de suscripciones
    acf_path = os.path.expanduser(
        "~/.local/share/Steam/steamapps/workshop/appworkshop_431960.acf"
    )
    if not os.path.exists(acf_path):
        return True  # no hay archivo, no hay problema

    try:
        with open(acf_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Formato Valve KeyValues. Buscar el bloque del workshop_id y eliminarlo.
        pattern = (
            r'"' + re.escape(workshop_id) + r'"\s*\n'
            r'\s*\{\s*\n'
            r'(?:\s*"[^"]*"\s*"[^"]*"\s*\n)*'
            r'\s*\}\s*\n?'
        )
        new_content = re.sub(pattern, "", content)

        if new_content != content:
            with open(acf_path, "w", encoding="utf-8") as f:
                f.write(new_content)
    except Exception:
        pass

    return True


# ── Wallpaper Engine Launcher (delega en wallpaper_engine_launcher) ────────

_WE_LAUNCHER = None


def _get_we_launcher():
    """Importa el modulo de launcher de WE, con fallback si no esta disponible."""
    global _WE_LAUNCHER
    if _WE_LAUNCHER is None:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import wallpaper_engine_launcher as wel
            _WE_LAUNCHER = wel
        except ImportError:
            _WE_LAUNCHER = False
    return _WE_LAUNCHER if _WE_LAUNCHER is not False else None


def we_pre_launch_cleanup() -> dict:
    """Limpia flags de crash/safe mode de WE antes de lanzar.

    Evita el dialogo 'no se cerro correctamente' y asegura que
    los wallpapers rendericen (safemode=false).
    """
    wel = _get_we_launcher()
    if not wel:
        return {'error': 'Modulo wallpaper_engine_launcher no disponible'}
    return wel.pre_launch_cleanup()


def we_reset_faulty_shutdown() -> bool:
    """Resetea el flag faultyShutdown en el registro de Wine."""
    wel = _get_we_launcher()
    if not wel:
        return False
    return wel.reset_faulty_shutdown()


def launch_wallpaper_engine(browse: bool = True) -> dict:
    """Lanza Wallpaper Engine via Steam/Proton de forma confiable.

    Args:
        browse: Si True, abre la UI de navegacion del Workshop.

    Returns:
        dict con {'ok': bool, 'service_running': bool, 'ui_running': bool,
                  'error': str}
    """
    wel = _get_we_launcher()
    if not wel:
        return {'ok': False, 'error': 'Modulo wallpaper_engine_launcher no disponible'}

    try:
        status = wel.launch(browse=browse)
        return {
            'ok': status.service_running,
            'service_running': status.service_running,
            'ui_running': status.ui_running,
            'service_pid': status.wallpaper_pid,
            'ui_pid': status.ui_pid,
            'error': status.last_error,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def get_we_status() -> dict:
    """Obtiene el estado actual de Wallpaper Engine.

    Returns:
        dict con 'steam_running', 'service_running', 'ui_running', 'proton_path', etc.
    """
    wel = _get_we_launcher()
    if not wel:
        return {'steam_running': False, 'error': 'launcher no disponible'}

    try:
        s = wel.get_status()
        return {
            'steam_running': s.steam_running,
            'service_running': s.service_running,
            'ui_running': s.ui_running,
            'service_pid': s.wallpaper_pid,
            'ui_pid': s.ui_pid,
            'proton_path': s.proton_path,
            'display_server': s.display_server,
            'error': s.last_error,
        }
    except Exception as e:
        return {'steam_running': False, 'error': str(e)}


def kill_wallpaper_engine() -> dict:
    """Detiene todos los procesos de Wallpaper Engine.

    Returns:
        dict con {'ok': bool, 'error': str}
    """
    wel = _get_we_launcher()
    if not wel:
        return {'ok': False, 'error': 'Modulo wallpaper_engine_launcher no disponible'}

    try:
        s = wel.kill()
        return {
            'ok': not s.service_running,
            'service_running': s.service_running,
            'error': s.last_error,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def restart_we_ui() -> dict:
    """Reinicia solo la UI de Wallpaper Engine (si el servicio esta corriendo).

    Returns:
        dict con {'ok': bool, 'ui_running': bool, 'error': str}
    """
    wel = _get_we_launcher()
    if not wel:
        return {'ok': False, 'error': 'Modulo wallpaper_engine_launcher no disponible'}

    try:
        s = wel.restart_ui()
        return {
            'ok': s.ui_running,
            'ui_running': s.ui_running,
            'ui_pid': s.ui_pid,
            'error': s.last_error,
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── CLI rápido ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        wps = get_all_wallpapers()
        print(f"Wallpapers: {len(wps)}")
        for w in wps[:3]:
            print(f"  {w.title[:60]} ({w.size_mb} MB)")
        monitors = get_connected_monitors()
        print(f"Monitores: {len(monitors)}")
        for m in monitors:
            print(f"  {m.connector} — {m.description} ({m.width}x{m.height})")
        print(f"Hidamari server: {'OK' if is_server_running() else 'NO'}")
        print(f"Daemon: {get_daemon_status()}")
