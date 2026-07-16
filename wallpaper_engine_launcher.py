#!/usr/bin/env python3
"""
RipoWall — Wallpaper Engine Launcher para Linux (portable).

Lanza Wallpaper Engine (Steam/Proton) de forma confiable en cualquier distro Linux,
resolviendo problemas de autenticacion Steam, crashes de CEF en Wayland,
y la inconsistencia al abrir la UI.

No tiene paths hardcodeados. Todo se detecta en runtime.

Modos:
  CLI:  python wallpaper_engine_launcher.py [--browse] [--status] [--kill] [--monitor]
  API:  from wallpaper_engine_launcher import launch, is_running, kill, status

Problemas que resuelve:
  1. Steam auth inconsistente → lanza SIEMPRE via Steam para heredar pipes de auth.
  2. CEF crash en Wayland → --no-sandbox, deteccion de display server.
  3. UI que no abre → monitorea y reinicia wallpaperui.exe si el servicio ya arranco.
  4. Proton no encontrado → auto-deteccion de versiones disponibles.
  5. Paths hardcodeados → todo se detecta: Steam, Proton, locale, display server.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ── Deteccion de entorno ────────────────────────────────────────────────────

HOME = Path.home()
XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME", str(HOME / ".local" / "share"))
XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config"))


def _find_steam_dir() -> str | None:
    """Detecta el directorio de instalacion de Steam."""
    candidates = [
        os.path.join(XDG_DATA_HOME, "Steam"),
        os.path.join(str(HOME), ".steam", "steam"),
        os.path.join(str(HOME), ".steam", "root"),
        os.path.join(str(HOME), ".var", "app", "com.valvesoftware.Steam", "data", "Steam"),
        os.path.join(str(HOME), "snap", "steam", "common", ".local", "share", "Steam"),
    ]
    for c in candidates:
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, "ubuntu12_32", "steam")):
            return c
    # Ultimo intento: leer symlink ~/.steam/steam
    link = os.path.join(str(HOME), ".steam", "steam")
    if os.path.islink(link):
        real = os.path.realpath(link)
        if os.path.isdir(real):
            return real
    return None


def _find_steam_exe() -> str | None:
    """Encuentra el ejecutable de Steam."""
    steam_dir = _find_steam_dir()
    if steam_dir:
        steam_exe = os.path.join(steam_dir, "ubuntu12_32", "steam")
        if os.path.isfile(steam_exe):
            return steam_exe
    # Buscar en PATH
    return shutil.which("steam")


def _find_proton() -> str | None:
    """Auto-detecta la mejor version de Proton disponible.

    Busca en orden: GE-Proton, Proton CachyOS, Proton Experimental, Proton default.
    """
    steam_dir = _find_steam_dir()
    if not steam_dir:
        return None

    compat_tools = []

    # 1. Directorio de compatibilitytools.d del sistema
    system_tools = "/usr/share/steam/compatibilitytools.d"
    if os.path.isdir(system_tools):
        for d in sorted(os.listdir(system_tools)):
            dpath = os.path.join(system_tools, d)
            proton_bin = os.path.join(dpath, "proton")
            if os.path.isfile(proton_bin):
                # Preferir versiones que contengan "cachyos" o "ge"
                priority = 0
                name_lower = d.lower()
                if "ge" in name_lower:
                    priority = 3
                elif "cachyos" in name_lower:
                    priority = 2
                elif "experimental" in name_lower:
                    priority = 1
                compat_tools.append((priority, d, proton_bin))

    # 2. Directorio de compatibilitytools.d del usuario
    user_tools = os.path.join(steam_dir, "compatibilitytools.d")
    if os.path.isdir(user_tools):
        for d in sorted(os.listdir(user_tools)):
            dpath = os.path.join(user_tools, d)
            proton_bin = os.path.join(dpath, "proton")
            if os.path.isfile(proton_bin):
                priority = 2
                if "ge" in d.lower():
                    priority = 4
                elif "cachyos" in d.lower():
                    priority = 3
                compat_tools.append((priority, d, proton_bin))

    # 3. Proton built-in de Steam
    steam_proton = os.path.join(steam_dir, "steamapps", "common")
    if os.path.isdir(steam_proton):
        for d in sorted(os.listdir(steam_proton), reverse=True):
            if d.startswith("Proton"):
                proton_bin = os.path.join(steam_proton, d, "proton")
                if os.path.isfile(proton_bin):
                    priority = 1 if "experimental" in d.lower() else 0
                    compat_tools.append((priority, d, proton_bin))

    if not compat_tools:
        return None

    compat_tools.sort(key=lambda x: x[0], reverse=True)
    return compat_tools[0][2]


def _detect_display_server() -> str:
    """Detecta el servidor de display: 'wayland', 'x11', 'unknown'."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def _detect_locale() -> str:
    """Detecta el locale del usuario para Steam/Wallpaper Engine."""
    for var in ("LANGUAGE", "LANG", "LC_ALL", "LC_MESSAGES"):
        val = os.environ.get(var, "")
        if val:
            parts = val.split(".")[0].split("_")
            if len(parts) >= 2:
                return f"{parts[0].lower()}-{parts[1].lower()}"
            return f"{parts[0].lower()}"
    return "es-es"


# ── Constantes detectadas ───────────────────────────────────────────────────

WE_APPID = "431960"
STEAM_DIR = _find_steam_dir()
STEAM_EXE = _find_steam_exe()
PROTON_BIN = _find_proton()
DISPLAY_SERVER = _detect_display_server()
USER_LOCALE = _detect_locale()

# Directorios derivados
WE_DIR = os.path.join(STEAM_DIR, "steamapps", "common", "wallpaper_engine") if STEAM_DIR else ""
WE_BIN_DIR = os.path.join(WE_DIR, "bin")
WE_COMPATDATA = os.path.join(STEAM_DIR, "steamapps", "compatdata", WE_APPID) if STEAM_DIR else ""

# Nombres de ejecutables Wine
WE_SERVICE_EXE = "wallpaperservice64.exe"
WE_WALLPAPER_EXE = "wallpaper64.exe"
WE_UI_EXE = "wallpaperui.exe"
WE_LAUNCHER_EXE = "launcher.exe"


# ── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class WEStatus:
    steam_running: bool = False
    service_running: bool = False
    ui_running: bool = False
    service_pid: int = 0
    wallpaper_pid: int = 0
    ui_pid: int = 0
    last_error: str = ""
    steam_dir: str = ""
    proton_path: str = ""
    display_server: str = ""


# ── Utilidades de procesos ──────────────────────────────────────────────────

def _find_wine_process(exe_name: str) -> list[dict]:
    """Busca procesos Wine/Proton por nombre de ejecutable Windows."""
    results = []
    try:
        r = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.split('\n'):
            if exe_name.lower() in line.lower() and 'grep' not in line:
                parts = line.split()
                if len(parts) >= 11:
                    try:
                        results.append({'pid': int(parts[1]), 'cmd': ' '.join(parts[10:])})
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass
    return results


def is_steam_running() -> bool:
    """Verifica si Steam esta corriendo (proceso principal o webhelper)."""
    try:
        r = subprocess.run(["pgrep", "-x", "steam"], capture_output=True, text=True, timeout=3)
        return len(r.stdout.strip()) > 0
    except Exception:
        return False


def is_service_running() -> bool:
    return len(_find_wine_process(WE_WALLPAPER_EXE)) > 0


def is_ui_running() -> bool:
    procs = _find_wine_process(WE_UI_EXE)
    return any('--type=' not in p['cmd'] for p in procs)


def get_status() -> WEStatus:
    """Estado completo de Wallpaper Engine con info del entorno."""
    s = WEStatus()
    s.steam_running = is_steam_running()
    s.service_running = is_service_running()
    s.ui_running = is_ui_running()
    s.steam_dir = STEAM_DIR or ""
    s.proton_path = PROTON_BIN or ""
    s.display_server = DISPLAY_SERVER

    wp_procs = _find_wine_process(WE_WALLPAPER_EXE)
    if wp_procs:
        s.wallpaper_pid = wp_procs[0]['pid']

    ui_procs = _find_wine_process(WE_UI_EXE)
    main_uis = [p for p in ui_procs if '--type=' not in p['cmd']]
    if main_uis:
        s.ui_pid = main_uis[0]['pid']

    svc_procs = _find_wine_process(WE_SERVICE_EXE)
    if svc_procs:
        s.service_pid = svc_procs[0]['pid']

    return s


# ── Launch Logic ────────────────────────────────────────────────────────────

def _wait_for_process(exe_name: str, timeout: float = 30.0) -> bool:
    """Espera hasta que un proceso aparezca."""
    start = time.time()
    while time.time() - start < timeout:
        if len(_find_wine_process(exe_name)) > 0:
            return True
        time.sleep(0.5)
    return False


def _validate_environment() -> WEStatus:
    """Valida que el entorno este listo para lanzar WE. Retorna status con errores."""
    status = WEStatus()
    status.steam_dir = STEAM_DIR or ""
    status.proton_path = PROTON_BIN or ""
    status.display_server = DISPLAY_SERVER

    if not STEAM_EXE or not STEAM_DIR:
        status.last_error = (
            "Steam no encontrado. Instala Steam primero:\n"
            "  Arch: sudo pacman -S steam\n"
            "  Ubuntu/Debian: sudo apt install steam\n"
            "  Fedora: sudo dnf install steam"
        )
        return status

    if not os.path.isdir(WE_DIR):
        status.last_error = (
            "Wallpaper Engine no esta instalado.\n"
            "Compralo en Steam (AppID 431960) e instálalo antes de usar RipoWall."
        )
        return status

    if not PROTON_BIN:
        status.last_error = (
            "No se encontro Proton. Instala alguna version:\n"
            "  Arch: sudo pacman -S proton-cachyos-slr\n"
            "  O activa Proton Experimental en Steam."
        )
        return status

    status.steam_running = is_steam_running()
    return status


def launch(browse: bool = True, timeout: float = 60.0) -> WEStatus:
    """Lanza Wallpaper Engine via Steam de forma confiable y portable.

    Args:
        browse: Abrir la UI de navegacion de wallpapers.
        timeout: Tiempo maximo de espera total en segundos.

    Returns:
        WEStatus con el estado final.
    """
    # 1. Validar entorno
    status = _validate_environment()
    if status.last_error:
        return status

    # 2. Steam debe estar corriendo
    if not status.steam_running:
        status.last_error = (
            "Steam no esta corriendo. Inicia Steam y volve a intentar."
        )
        return status

    # 3. Verificar si ya esta corriendo
    existing = get_status()
    if existing.service_running and existing.ui_running and browse:
        existing.last_error = ""
        return existing

    # 4. Lanzar via Steam (esto asegura Steam auth pipes)
    print("[RipoWall] Lanzando Wallpaper Engine via Steam...", flush=True)
    try:
        subprocess.Popen(
            [STEAM_EXE, f"steam://rungameid/{WE_APPID}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        status.last_error = f"Error al lanzar via Steam: {e}"
        return status

    # 5. Esperar al servicio
    print("[RipoWall] Esperando al servicio wallpaper64.exe...", flush=True)
    if not _wait_for_process(WE_WALLPAPER_EXE, timeout=min(timeout * 0.4, 20)):
        status.last_error = "El servicio de Wallpaper Engine no arranco."
        return status

    status = get_status()
    print(f"[RipoWall] Servicio iniciado (PID {status.wallpaper_pid})", flush=True)

    # 6. Si no necesitamos UI, terminar aca
    if not browse:
        return status

    # 7. Esperar la UI
    print("[RipoWall] Esperando la UI wallpaperui.exe...", flush=True)
    if _wait_for_process(WE_UI_EXE, timeout=min(timeout * 0.4, 25)):
        status = get_status()
        print(f"[RipoWall] UI iniciada (PID {status.ui_pid})", flush=True)
        return status

    # 8. La UI no aparecio: lanzarla manualmente con Proton
    print("[RipoWall] UI no detectada. Lanzando manualmente via Proton...", flush=True)
    return _launch_ui_direct(status)


def _launch_ui_direct(status: WEStatus) -> WEStatus:
    """Lanza wallpaperui.exe directamente via Proton con flags optimizados."""
    ui_path = os.path.join(WE_BIN_DIR, WE_UI_EXE)
    if not os.path.isfile(ui_path):
        status.last_error = f"Ejecutable no encontrado: {ui_path}"
        return status

    # Flags base
    ui_args = [
        PROTON_BIN, "run", ui_path,
        "-no-cef-sandbox",
        "-weuimain",
        "-window", "browsewallpapers",
        "-buildv", "20000800000042",
        "-skin", "dark",
        "-language", USER_LOCALE,
        "-steamlanguage", USER_LOCALE,
        "-monitordetection", "managed",
        "-disablefx",
        "-x64",
    ]

    # Flags extra para Wayland
    env = os.environ.copy()
    env["STEAM_COMPAT_DATA_PATH"] = WE_COMPATDATA
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = STEAM_DIR
    env["SteamAppId"] = WE_APPID
    env["SteamGameId"] = WE_APPID
    env["PROTON_NO_ESYNC"] = "1"

    if DISPLAY_SERVER == "wayland":
        env["PROTON_USE_WINED3D"] = "1"

    print(f"[RipoWall] Proton: {PROTON_BIN}", flush=True)
    print(f"[RipoWall] Display: {DISPLAY_SERVER}, Locale: {USER_LOCALE}", flush=True)

    try:
        subprocess.Popen(
            ui_args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        status.last_error = f"Error al lanzar UI: {e}"
        return status

    if _wait_for_process(WE_UI_EXE, timeout=15):
        return get_status()
    else:
        status = get_status()
        if status.service_running:
            status.last_error = "La UI no arranco pero el servicio SI esta activo."
        else:
            status.last_error = "La UI no arranco."
        return status


def restart_ui() -> WEStatus:
    """Reinicia solo la UI si el servicio esta corriendo."""
    status = get_status()
    if not status.service_running:
        status.last_error = "El servicio no esta corriendo. Usa launch() primero."
        return status

    # Matar UI
    for p in _find_wine_process(WE_UI_EXE):
        try:
            os.kill(p['pid'], signal.SIGTERM)
        except OSError:
            pass
    time.sleep(2)
    for p in _find_wine_process(WE_UI_EXE):
        try:
            os.kill(p['pid'], signal.SIGKILL)
        except OSError:
            pass
    time.sleep(1)

    return _launch_ui_direct(status)


def kill() -> WEStatus:
    """Detiene todos los procesos de Wallpaper Engine."""
    print("[RipoWall] Deteniendo Wallpaper Engine...", flush=True)
    for exe in [WE_UI_EXE, WE_WALLPAPER_EXE, WE_SERVICE_EXE, WE_LAUNCHER_EXE]:
        for p in _find_wine_process(exe):
            try:
                os.kill(p['pid'], signal.SIGTERM)
            except OSError:
                pass
    time.sleep(2)
    for exe in [WE_UI_EXE, WE_WALLPAPER_EXE, WE_SERVICE_EXE, WE_LAUNCHER_EXE]:
        for p in _find_wine_process(exe):
            try:
                os.kill(p['pid'], signal.SIGKILL)
            except OSError:
                pass
    return get_status()


# ── Monitor (keep-alive) ────────────────────────────────────────────────────

def monitor(interval: float = 5.0):
    """Modo demonio: monitorea WE y reinicia la UI si crashea."""
    running = True

    def _shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print("[RipoWall] Monitor de Wallpaper Engine iniciado (Ctrl+C para detener).", flush=True)

    while running:
        try:
            s = get_status()
            if not s.service_running:
                print("[RipoWall] Servicio detenido. Re-lanzando...", flush=True)
                launch(browse=True)
            elif not s.ui_running:
                print("[RipoWall] UI caida. Reiniciando...", flush=True)
                restart_ui()
            time.sleep(interval)
        except Exception as e:
            print(f"[RipoWall] Error en monitor: {e}", flush=True)
            time.sleep(interval)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="RipoWall — Wallpaper Engine Launcher")
    parser.add_argument("--browse", "-b", action="store_true", default=True,
                        help="Abrir UI de navegacion (default)")
    parser.add_argument("--no-browse", action="store_true",
                        help="Solo servicio de fondo")
    parser.add_argument("--status", "-s", action="store_true",
                        help="Mostrar estado actual")
    parser.add_argument("--kill", "-k", action="store_true",
                        help="Detener Wallpaper Engine")
    parser.add_argument("--restart-ui", action="store_true",
                        help="Reiniciar solo la UI")
    parser.add_argument("--monitor", "-m", action="store_true",
                        help="Modo monitor (keep-alive)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON (para --status)")

    args = parser.parse_args()

    if args.status:
        s = get_status()
        if args.json:
            print(json.dumps({
                "steam_running": s.steam_running,
                "service_running": s.service_running,
                "ui_running": s.ui_running,
                "service_pid": s.service_pid,
                "ui_pid": s.ui_pid,
                "steam_dir": s.steam_dir,
                "proton_path": s.proton_path,
                "display_server": s.display_server,
                "last_error": s.last_error,
            }, indent=2))
        else:
            print("═══ Wallpaper Engine Status ═══")
            print(f"  Steam:        {'✓ running' if s.steam_running else '✗ not running'}")
            print(f"  Servicio:     {'✓' if s.service_running else '✗'} (PID {s.service_pid})" if s.service_pid else f"  Servicio:     ✗")
            print(f"  UI:           {'✓' if s.ui_running else '✗'} (PID {s.ui_pid})" if s.ui_pid else f"  UI:           ✗")
            print(f"  Display:      {s.display_server}")
            print(f"  Proton:       {s.proton_path or 'NO DETECTADO'}")
            print(f"  Steam dir:    {s.steam_dir or 'NO DETECTADO'}")
            if s.last_error:
                print(f"  ⚠ {s.last_error}")
        return

    if args.kill:
        s = kill()
        print("✓ Wallpaper Engine detenido." if not s.service_running else "⚠ Algunos procesos no se detuvieron.")
        return

    if args.restart_ui:
        s = restart_ui()
        if s.ui_running:
            print(f"✓ UI reiniciada (PID {s.ui_pid})")
        else:
            print(f"✗ {s.last_error}")
            sys.exit(1)
        return

    if args.monitor:
        monitor()
        return

    # Default: launch
    print("RipoWall — Wallpaper Engine Launcher")
    print(f"  Proton:  {PROTON_BIN or 'NO DETECTADO'}")
    print(f"  Steam:   {STEAM_DIR or 'NO DETECTADO'}")
    print(f"  Display: {DISPLAY_SERVER}")
    print()

    s = launch(browse=not args.no_browse)
    if s.service_running:
        print("\n✓ Wallpaper Engine iniciado.")
        if s.ui_running:
            print(f"  UI: PID {s.ui_pid}")
    else:
        print(f"\n✗ {s.last_error}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
