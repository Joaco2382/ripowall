#!/usr/bin/env python3
"""
RipoWall Diagnostics — Modulo de diagnostico y reparacion automatica.

Evalua el estado completo del stack RipoWall:
  - ENVIRONMENT: Steam, Proton, Wine prefix, display server, dependencias Python.
  - WALLPAPER_ENGINE: instalacion, config, faultyShutdown, safemode, procesos.
  - RIPOWALL: binarios, systemd services, daemon, GUI.
  - HIDAMARI: reproductor, DBus, config, symlinks.
  - WORKSHOP: contenido, symlinks planos.

Uso:
  python ripowall_diagnostics.py              # Diagnostico completo
  python ripowall_diagnostics.py --repair      # Diagnostico + reparacion
  python ripowall_diagnostics.py --json        # Salida JSON
  python ripowall_diagnostics.py --report      # Genera reporte Markdown + JSON
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATEGORIES = ["ENVIRONMENT", "WALLPAPER_ENGINE", "RIPOWALL", "HIDAMARI", "WORKSHOP"]
SEVERITY_ORDER: dict[str, int] = {"ok": 0, "warning": 1, "error": 2}

HOME = Path.home()
LOCAL_BIN = HOME / ".local" / "bin"
SYSTEMD_USER = HOME / ".config" / "systemd" / "user"
STEAM_ROOT = HOME / ".local" / "share" / "Steam"
STEAM_APPS = STEAM_ROOT / "steamapps" / "common"
WE_DIR = STEAM_APPS / "wallpaper_engine"
WE_PREFIX = STEAM_ROOT / "steamapps" / "compatdata" / "431960" / "pfx"
WORKSHOP_DIR = STEAM_ROOT / "steamapps" / "workshop" / "content" / "431960"
HIDAMARI_CONFIG = HOME / ".config" / "hidamari" / "config.json"
HIDAMARI_FLAT = HOME / "Videos" / "Hidamari"

SYSTEMD_SERVICES = {
    "hidamari-daemon.service": "enabled",
}
OBSOLETE_SERVICES = ["hidamari-rotate.service", "hidamari-rotate.timer"]
REQUIRED_BINARIES = [
    "hidamari-daemon", "hidamari-gui", "hidamari_core.py",
    "wallpaper_engine_launcher.py", "hidamari-sync", "hidamari-rotate",
]


@dataclass
class CheckResult:
    category: str
    name: str
    status: str  # "ok" | "warning" | "error"
    message: str
    fix_suggestion: str = ""
    detail: str = ""
    repaired: bool = False


@dataclass
class DiagnosticReport:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    hostname: str = field(default_factory=lambda: os.uname().nodename)
    results: list[CheckResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts = {"ok": 0, "warning": 0, "error": 0}
        for r in self.results:
            counts[r.status] += 1
        return counts

    @property
    def all_ok(self) -> bool:
        return all(r.status == "ok" for r in self.results)


# ── Utilidades seguras ─────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=str(e))


def _systemctl_user(cmd: list[str]) -> subprocess.CompletedProcess:
    return _run(["systemctl", "--user", *cmd], timeout=8)


def _grep_file(path: Path, pattern: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [line.rstrip() for line in fh if pattern in line]
    except (OSError, PermissionError):
        return []


def _pgrep(pattern: str) -> list[str]:
    result = _run(["pgrep", "-f", pattern])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()
    return []


def _connected_monitors() -> set[str]:
    result = _run(["xrandr"])
    monitors = set()
    for line in result.stdout.splitlines():
        if " connected" in line:
            monitors.add(line.split()[0])
    return monitors


# ── Checks: ENVIRONMENT ────────────────────────────────────────────────────

def check_steam_running(report: DiagnosticReport) -> None:
    pids = _pgrep("steam")
    if pids:
        report.results.append(CheckResult("ENVIRONMENT", "Steam running", "ok",
            f"Steam corriendo ({len(pids)} proceso(s))."))
    else:
        report.results.append(CheckResult("ENVIRONMENT", "Steam running", "error",
            "Steam no esta corriendo.", "Inicia Steam: steam &",
            "Wallpaper Engine y autenticacion Steam requieren el cliente corriendo."))


def check_proton_availability(report: DiagnosticReport) -> None:
    paths = [STEAM_ROOT / "compatibilitytools.d", Path("/usr/share/steam/compatibilitytools.d")]
    found = []
    for p in paths:
        if p.exists():
            try:
                found.extend([d.name for d in p.iterdir() if "proton" in d.name.lower()])
            except OSError:
                pass
    if found:
        report.results.append(CheckResult("ENVIRONMENT", "Proton availability", "ok",
            f"Proton detectado: {found[0]}.", detail=f"Versiones: {', '.join(found)}"))
    else:
        report.results.append(CheckResult("ENVIRONMENT", "Proton availability", "error",
            "No se encontro ningun Proton.", "Instala Proton via Steam Settings > Compatibility."))


def check_wine_prefix(report: DiagnosticReport) -> None:
    if not WE_PREFIX.exists():
        report.results.append(CheckResult("ENVIRONMENT", "Wine prefix", "error",
            "Wine prefix no existe.", "Ejecuta WE desde Steam al menos una vez.",
            f"Ruta esperada: {WE_PREFIX}"))
        return
    system32 = WE_PREFIX / "drive_c" / "windows" / "system32"
    try:
        dll_count = len(list(system32.glob("*.dll"))) if system32.exists() else 0
    except OSError:
        dll_count = 0
    if dll_count < 100:
        report.results.append(CheckResult("ENVIRONMENT", "Wine prefix", "warning",
            f"Prefix con solo {dll_count} DLLs — posiblemente incompleto.",
            "Relanza WE desde Steam para completar el prefix."))
    else:
        report.results.append(CheckResult("ENVIRONMENT", "Wine prefix", "ok",
            f"Wine prefix OK ({dll_count} DLLs en system32)."))


def check_display_server(report: DiagnosticReport) -> None:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    x11 = os.environ.get("DISPLAY", "")
    if session == "wayland" or wayland:
        report.results.append(CheckResult("ENVIRONMENT", "Display server", "ok",
            "Wayland (XWayland disponible).", detail=f"WAYLAND={wayland}, DISPLAY={x11}"))
    elif x11:
        report.results.append(CheckResult("ENVIRONMENT", "Display server", "ok",
            f"X11 ({x11})."))
    else:
        report.results.append(CheckResult("ENVIRONMENT", "Display server", "error",
            "No se detecto display server.", "Inicia sesion grafica antes de RipoWall."))


def check_python_deps(report: DiagnosticReport) -> None:
    deps = {}
    for mod, name, fix in [
        (("gi", "Gtk", "4.0"), "GTK4", "pip install pygobject"),
        (("pydbus",), "pydbus", "pip install pydbus"),
        (("vlc",), "libvlc (python-vlc)", "pip install python-vlc"),
    ]:
        try:
            if len(mod) == 3:
                import gi; gi.require_version(mod[1], mod[2])
            elif len(mod) == 1:
                __import__(mod[0])
            deps[name] = "OK"
        except Exception as e:
            deps[name] = str(e)
    failed = {k: v for k, v in deps.items() if v != "OK"}
    ok = sorted(k for k, v in deps.items() if v == "OK")
    if failed:
        report.results.append(CheckResult("ENVIRONMENT", "Python dependencies", "error",
            f"Faltantes: {', '.join(failed)}", fix_suggestion="python3 -m pip install pygobject pydbus python-vlc",
            detail=f"OK: {', '.join(ok)}" if ok else ""))
    else:
        report.results.append(CheckResult("ENVIRONMENT", "Python dependencies", "ok",
            f"Todas OK: {', '.join(ok)}."))


# ── Checks: WALLPAPER_ENGINE ───────────────────────────────────────────────

def check_we_installation(report: DiagnosticReport) -> None:
    if not WE_DIR.exists():
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE installation", "error",
            "Wallpaper Engine no instalado.", "Instala WE via Steam (AppID 431960)."))
        return
    missing = [f for f in ["wallpaper64.exe", "launcher.exe", "bin", "assets"] if not (WE_DIR / f).exists()]
    if missing:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE installation", "error",
            f"Instalacion incompleta: {', '.join(missing)}.",
            "Steam > Biblioteca > WE > Propiedades > Archivos locales > Verificar integridad."))
    else:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE installation", "ok",
            "Instalacion completa."))


def check_we_config(report: DiagnosticReport) -> None:
    cf = WE_DIR / "config.json"
    if not cf.exists():
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE config.json", "warning",
            "config.json no encontrado.", "Abre la UI de WE al menos una vez."))
        return
    try:
        data = json.loads(cf.read_text(encoding="utf-8"))
        safemode = data.get("steamuser", {}).get("general", {}).get("user", {}).get("safemode", False)
        if safemode:
            report.results.append(CheckResult("WALLPAPER_ENGINE", "WE safemode", "error",
                "safemode=true — wallpapers NUNCA renderizan.",
                "Abre WE > Settings > General > desmarca 'Start in safe mode', O usa ripowall-we kill + launch."))
        else:
            report.results.append(CheckResult("WALLPAPER_ENGINE", "WE safemode", "ok",
                "safemode=false — wallpapers renderizan."))
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE config.json", "ok",
            "config.json presente y valido."))
    except (json.JSONDecodeError, KeyError) as e:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE config.json", "error",
            f"config.json corrupto: {e}", "Elimina config.json y relanza WE."))


def check_we_faulty_shutdown(report: DiagnosticReport) -> None:
    user_reg = WE_PREFIX / "user.reg"
    if not user_reg.exists():
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE faulty shutdown", "warning",
            "user.reg no encontrado."))
        return
    lines = _grep_file(user_reg, "faultyShutdown")
    has_faulty = any('"faultyShutdown"' in ln and 'dword:00000001' in ln for ln in lines)
    if has_faulty:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE faulty shutdown", "warning",
            "faultyShutdown=1 — WE mostrara dialogo 'no se cerro bien' al iniciar.",
            "Cierra WE limpiamente desde Steam, o ejecuta ripowall-we kill (resetea el flag)."))
    else:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE faulty shutdown", "ok",
            "faultyShutdown limpio."))


def check_we_processes(report: DiagnosticReport) -> None:
    pids = _pgrep("wallpaper64\\.exe")
    if pids:
        ui_pids = _pgrep("wallpaperui\\.exe")
        ui_main = [p for p in ui_pids if p != pids[0]]
        ui_msg = f", UI: {'OK' if ui_main else 'cerrada'}"
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE processes", "ok",
            f"WE corriendo: wallpaper64.exe PID {pids[0]}{ui_msg}."))
    else:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "WE processes", "warning",
            "Wallpaper Engine no esta corriendo.", "ripowall-we --browse"))


def check_cef_networking(report: DiagnosticReport) -> None:
    try:
        logs = list(WE_DIR.rglob("chrome_debug.log"))
    except OSError:
        logs = []
    errors = {}
    for lp in logs[:10]:
        for line in _grep_file(lp, "ERROR"):
            if "SIO_ADDRESS_LIST_SORT" in line: errors["SIO_ADDRESS_LIST_SORT"] = True
            if "10042" in line: errors["WSAENOPROTOOPT"] = True
    if errors:
        report.results.append(CheckResult("WALLPAPER_ENGINE", "CEF/Wine networking", "ok",
            f"Limitaciones Wine no corregibles: {', '.join(errors)}.",
            detail="Wine no implementa ciertas funciones de red. El Workshop puede ser lento. No afecta wallpapers."))


# ── Checks: RIPOWALL ───────────────────────────────────────────────────────

def check_ripowall_binaries(report: DiagnosticReport) -> None:
    missing, perm_issues = [], []
    for fname in REQUIRED_BINARIES:
        p = LOCAL_BIN / fname
        if not p.exists():
            missing.append(fname)
        elif not os.access(p, os.X_OK):
            perm_issues.append(fname)
    if missing:
        report.results.append(CheckResult("RIPOWALL", "Binarios", "error",
            f"Faltantes: {', '.join(missing)}.", "Instala RipoWall: ./install.sh"))
        return
    if perm_issues:
        report.results.append(CheckResult("RIPOWALL", "Binarios", "warning",
            f"Permisos: {', '.join(perm_issues)}.", f"chmod +x {' '.join(perm_issues)}"))
    else:
        report.results.append(CheckResult("RIPOWALL", "Binarios", "ok",
            "Todos los binarios presentes y ejecutables."))


def check_ripowall_systemd(report: DiagnosticReport) -> None:
    issues, ok_list = [], []
    for svc, expected in SYSTEMD_SERVICES.items():
        en = _systemctl_user(["is-enabled", svc]).stdout.strip()
        act = _systemctl_user(["is-active", svc]).stdout.strip()
        if en != expected:
            issues.append(f"{svc} is-enabled={en} (esperado: {expected})")
        else:
            ok_list.append(f"{svc}={en}")
        if act != "active":
            issues.append(f"{svc} is-active={act}")
    if issues:
        report.results.append(CheckResult("RIPOWALL", "Systemd services", "error",
            "; ".join(issues), "systemctl --user enable --now hidamari-daemon",
            detail=f"OK: {', '.join(ok_list)}" if ok_list else ""))
    else:
        report.results.append(CheckResult("RIPOWALL", "Systemd services", "ok",
            "Todos los servicios habilitados y activos."))


def check_obsolete_services(report: DiagnosticReport) -> None:
    found = []
    for svc in OBSOLETE_SERVICES:
        path = SYSTEMD_USER / svc
        if path.exists():
            en = _systemctl_user(["is-enabled", svc]).stdout.strip()
            found.append(f"{svc} ({en})")
    if found:
        report.results.append(CheckResult("RIPOWALL", "Obsolete services", "warning",
            f"Servicios obsoletos: {'; '.join(found)}.",
            "El daemon maneja la rotacion. systemctl --user disable --now hidamari-rotate.timer",
            detail="Mantener ambos mecanismos puede causar conflictos de rotacion."))


def check_daemon_health(report: DiagnosticReport) -> None:
    pids = _pgrep("hidamari-daemon")
    if not pids:
        report.results.append(CheckResult("RIPOWALL", "Daemon health", "error",
            "hidamari-daemon no esta corriendo.", "systemctl --user restart hidamari-daemon"))
        return
    ps = _run(["ps", "-p", pids[0], "-o", "etime=,rss="])
    parts = ps.stdout.strip().split()
    etime = parts[0] if parts else "?"
    rss_mb = int(parts[1]) / 1024 if len(parts) > 1 else 0
    # Check sintaxis
    dp = LOCAL_BIN / "hidamari-daemon"
    compile_ok = dp.exists() and _run(["python3", "-c",
        f"import py_compile; py_compile.compile('{dp}', doraise=True)"]).returncode == 0
    msgs = [f"PID {pids[0]}", f"uptime {etime}", f"memoria {rss_mb:.1f}MB"]
    st, fix = "ok", ""
    if not compile_ok:
        st, fix = "error", "Corrige errores de sintaxis en hidamari-daemon."
        msgs.append("ERROR DE SINTAXIS")
    elif rss_mb > 200:
        st, fix = "warning", "Posible memory leak. Reinicia si supera 300MB."
    report.results.append(CheckResult("RIPOWALL", "Daemon health", st, ", ".join(msgs), fix_suggestion=fix))


def check_pre_deploy_syntax(report: DiagnosticReport) -> None:
    failed = []
    for script in [LOCAL_BIN / f for f in ["hidamari-daemon", "hidamari_core.py",
                   "wallpaper_engine_launcher.py", "hidamari-gui"]]:
        if not script.exists():
            continue
        r = _run(["python3", "-c",
            f"import py_compile; py_compile.compile('{script}', doraise=True)"])
        if r.returncode != 0:
            failed.append(f"{script.name}: {r.stderr.strip().split(chr(10))[-1]}")
    if failed:
        report.results.append(CheckResult("RIPOWALL", "Pre-deploy syntax", "error",
            f"Errores: {'; '.join(failed)}.", "Corrige antes de desplegar.",
            "Auditoria revelo crash loop por SyntaxError (nonlocal vs global)."))
    else:
        report.results.append(CheckResult("RIPOWALL", "Pre-deploy syntax", "ok",
            "Todos los scripts compilan."))


# ── Checks: HIDAMARI ──────────────────────────────────────────────────────

def check_hidamari_player(report: DiagnosticReport) -> None:
    pids = _pgrep("hidamari-server")
    if not pids:
        report.results.append(CheckResult("HIDAMARI", "Hidamari player", "error",
            "hidamari-server no esta corriendo.", "Lanza Hidamari: hidamari &"))
        return
    player_pids = _pgrep("hidamari-player")
    report.results.append(CheckResult("HIDAMARI", "Hidamari player", "ok",
        f"Hidamari corriendo: server PID {pids[0]}, {len(player_pids)} player(s)."))


def check_hidamari_dbus(report: DiagnosticReport) -> None:
    ping = _run(["gdbus", "call", "--session",
        "--dest", "io.github.jeffshee.Hidamari",
        "--object-path", "/io/github/jeffshee/Hidamari/server",
        "--method", "org.freedesktop.DBus.Peer.Ping"])
    if ping.returncode != 0:
        report.results.append(CheckResult("HIDAMARI", "DBus connectivity", "error",
            "No se puede contactar al server DBus de Hidamari.",
            "Reinicia Hidamari: pkill hidamari-server && hidamari &",
            detail=ping.stderr.strip()))
        return
    intro = _run(["gdbus", "introspect", "--session",
        "--dest", "io.github.jeffshee.Hidamari",
        "--object-path", "/io/github/jeffshee/Hidamari/server",
        "--recurse", "--xml"])
    has_reload = 'name="reload"' in intro.stdout
    has_video = 'name="video"' in intro.stdout
    if has_reload and has_video:
        report.results.append(CheckResult("HIDAMARI", "DBus connectivity", "ok",
            "DBus OK: reload() y video() expuestos."))
    else:
        missing = [m for m, h in [("reload", has_reload), ("video", has_video)] if not h]
        report.results.append(CheckResult("HIDAMARI", "DBus connectivity", "error",
            f"Metodos faltantes: {', '.join(missing)}.",
            "Actualiza Hidamari a la version mas reciente (AUR)."))


def check_reload_config_bug(report: DiagnosticReport) -> None:
    """BUG CRITICO: reload_config() llama a DBUS_PLAYER en vez de DBUS_SERVER."""
    cp = LOCAL_BIN / "hidamari_core.py"
    if not cp.exists():
        return
    try:
        content = cp.read_text(encoding="utf-8")
    except OSError:
        return
    # Detectar el patron de la funcion reload_config
    m = re.search(r'def reload_config\(\)[^:]*:(.*?)(?=\n(?:def |class |# ──))', content, re.DOTALL)
    if m:
        block = m.group(1)
        uses_player = "DBUS_PLAYER_BUS" in block and "DBUS_PLAYER_PATH" in block
        if uses_player:
            report.results.append(CheckResult("HIDAMARI", "reload_config DBus bug", "error",
                "BUG CRITICO: reload_config() llama a DBUS_PLAYER_BUS (INCORRECTO). "
                "El player NO tiene interfaz custom — reload_config jamas se aplica. "
                "Los cambios de wallpaper del daemon FALLAN SILENCIOSAMENTE.",
                "Cambia DBUS_PLAYER_BUS -> DBUS_SERVER_BUS y el metodo a server.reload. "
                "El server SI expone reload() en /io/github/jeffshee/Hidamari/server."))
        else:
            report.results.append(CheckResult("HIDAMARI", "reload_config DBus bug", "ok",
                "reload_config() usa el bus correcto (SERVER)."))


def check_hidamari_config(report: DiagnosticReport) -> None:
    if not HIDAMARI_CONFIG.exists():
        report.results.append(CheckResult("HIDAMARI", "config.json", "error",
            "config.json no encontrado.", "Lanza Hidamari para generar la config inicial.",
            f"Ruta: {HIDAMARI_CONFIG}"))
        return
    try:
        data = json.loads(HIDAMARI_CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.results.append(CheckResult("HIDAMARI", "config.json", "error",
            f"JSON invalido: {e}", "Restaura desde backup."))
        return
    ds = data.get("data_source", {})
    connected = _connected_monitors()
    orphans = set(ds.keys()) - connected - {"Default"}
    msgs = [f"mode={data.get('mode', '?')}", f"{len(ds)} fuentes"]
    st, fix = "ok", ""
    if orphans:
        st = "warning"
        fix = f"Elimina {', '.join(sorted(orphans))} de data_source. Pueden reaparecer por bug de Hidamari."
        msgs.append(f"Huerfanos: {', '.join(sorted(orphans))}")
    report.results.append(CheckResult("HIDAMARI", "config.json", st, ", ".join(msgs),
        fix_suggestion=fix, detail=f"Monitores: {', '.join(sorted(connected))}" if connected else ""))


# ── Checks: WORKSHOP ───────────────────────────────────────────────────────

def check_workshop_content(report: DiagnosticReport) -> None:
    if not WORKSHOP_DIR.exists():
        report.results.append(CheckResult("WORKSHOP", "Workshop content", "error",
            "Workshop no encontrado.", "Suscribete a wallpapers en Steam (AppID 431960)."))
        return
    try:
        count = len([d for d in WORKSHOP_DIR.iterdir() if d.is_dir()])
    except OSError:
        count = 0
    if count == 0:
        report.results.append(CheckResult("WORKSHOP", "Workshop content", "warning",
            "Sin wallpapers.", "Suscribete a wallpapers en Steam Workshop."))
    else:
        report.results.append(CheckResult("WORKSHOP", "Workshop content", "ok",
            f"{count} wallpapers disponibles."))


def check_flat_symlinks(report: DiagnosticReport) -> None:
    if not HIDAMARI_FLAT.exists():
        report.results.append(CheckResult("WORKSHOP", "Flat symlinks", "error",
            "~/Videos/Hidamari/ no existe.", "mkdir -p ~/Videos/Hidamari && ejecuta hidamari-sync"))
        return
    try:
        entries = list(HIDAMARI_FLAT.iterdir())
        symlinks = [e for e in entries if e.is_symlink()]
        broken = [e for e in symlinks if not e.exists()]
    except OSError:
        report.results.append(CheckResult("WORKSHOP", "Flat symlinks", "error",
            "No se puede acceder al directorio."))
        return
    msgs = [f"{len(symlinks)} symlinks"]
    st, fix = "ok", ""
    if broken:
        msgs.append(f"{len(broken)} rotos")
        st = "warning"
        fix = "Ejecuta hidamari-sync para regenerar symlinks rotos."
    report.results.append(CheckResult("WORKSHOP", "Flat symlinks", st, ", ".join(msgs), fix_suggestion=fix,
        detail=f"Directorio: {HIDAMARI_FLAT}"))


# ── Reparacion automatica ──────────────────────────────────────────────────

def repair_fixable(report: DiagnosticReport) -> int:
    repaired = 0
    # 1. chmod +x hidamari_core.py
    cp = LOCAL_BIN / "hidamari_core.py"
    if cp.exists():
        try:
            if not (cp.stat().st_mode & stat.S_IXUSR):
                cp.chmod(cp.stat().st_mode | stat.S_IXUSR)
                repaired += 1
                for r in report.results:
                    if r.name == "Binarios" and "Permisos" in r.message:
                        r.status, r.repaired = "ok", True
                        r.message += " [FIXED]"
        except OSError:
            pass
    # 2. Deshabilitar rotate timer
    for svc in OBSOLETE_SERVICES:
        if (SYSTEMD_USER / svc).exists():
            en = _systemctl_user(["is-enabled", svc]).stdout.strip()
            if en not in ("disabled", "static", ""):
                _systemctl_user(["disable", "--now", svc])
                repaired += 1
    # 3. Habilitar hidamari-daemon si no esta enabled
    for r in report.results:
        if r.name == "Systemd services" and r.status == "error":
            en = _systemctl_user(["enable", "--now", "hidamari-daemon.service"])
            if en.returncode == 0:
                r.status, r.repaired = "ok", True
                r.message += " [FIXED]"
                repaired += 1
    return repaired


# ── Orquestador ────────────────────────────────────────────────────────────

ALL_CHECKS = [
    check_steam_running, check_proton_availability, check_wine_prefix,
    check_display_server, check_python_deps,
    check_we_installation, check_we_config, check_we_faulty_shutdown,
    check_we_processes, check_cef_networking,
    check_ripowall_binaries, check_ripowall_systemd, check_obsolete_services,
    check_daemon_health, check_pre_deploy_syntax,
    check_hidamari_player, check_hidamari_dbus, check_reload_config_bug,
    check_hidamari_config,
    check_workshop_content, check_flat_symlinks,
]


def run_full_diagnostic(repair: bool = False) -> DiagnosticReport:
    report = DiagnosticReport()
    for fn in ALL_CHECKS:
        try:
            fn(report)
        except Exception as e:
            report.results.append(CheckResult("RIPOWALL", f"check_crash:{fn.__name__}",
                "error", f"Check interno fallo: {e}", detail=str(e)))
    report.results.sort(key=lambda r: (
        CATEGORIES.index(r.category) if r.category in CATEGORIES else 99,
        -SEVERITY_ORDER.get(r.status, 0)))
    if repair:
        count = repair_fixable(report)
        report.results.insert(0, CheckResult("RIPOWALL", "Auto-repair", "ok",
            f"{count} problema(s) reparado(s)." if count else "Nada que reparar."))
    return report


# ── Renderizado ────────────────────────────────────────────────────────────

def render_terminal(report: DiagnosticReport) -> str:
    G, Y, R, B, X, D = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m", "\033[2m"
    colors = {"ok": G, "warning": Y, "error": R}
    lines = [
        f"{B}RipoWall Diagnostics{X}",
        f"  {report.timestamp} | {report.hostname}",
        f"  {G}{report.summary['ok']} OK{X} | {Y}{report.summary['warning']} WARN{X} | {R}{report.summary['error']} ERR{X}",
        "=" * 60,
    ]
    cat = ""
    for r in report.results:
        if r.category != cat:
            cat = r.category
            lines.append(f"\n{B}[{cat}]{X}")
        icon = {"ok": " OK ", "warning": "WARN", "error": "ERR "}[r.status]
        c = colors[r.status]
        fixed = f" {G}[FIXED]{X}" if r.repaired else ""
        lines.append(f"  {c}[{icon}]{X} {r.name}{fixed}")
        if r.status != "ok":
            lines.append(f"  {D}{r.message}{X}")
            if r.fix_suggestion:
                lines.append(f"  {D}Fix: {r.fix_suggestion}{X}")
    lines.append(f"\n{'-' * 60}")
    if report.all_ok:
        lines.append(f"{G}{B}Todos los checks OK.{X}")
    else:
        lines.append(f"{R}{B}{report.summary['error']} errores, {report.summary['warning']} warnings{X} — ejecuta con --repair")
    return "\n".join(lines)


def render_json(report: DiagnosticReport) -> str:
    return json.dumps({
        "timestamp": report.timestamp, "hostname": report.hostname,
        "summary": report.summary, "all_ok": report.all_ok,
        "results": [{"category": r.category, "name": r.name, "status": r.status,
                      "message": r.message, "fix": r.fix_suggestion,
                      "detail": r.detail, "repaired": r.repaired} for r in report.results],
    }, indent=2, ensure_ascii=False)


def render_markdown(report: DiagnosticReport) -> str:
    lines = [
        f"# RipoWall Diagnostics Report",
        f"**{report.timestamp}** | {report.hostname}",
        f"**{report.summary['ok']} OK | {report.summary['warning']} Warnings | {report.summary['error']} Errors**",
        "", "---", "",
    ]
    cat = ""
    for r in report.results:
        if r.category != cat:
            cat = r.category
            lines.append(f"## {cat}")
            lines.append("")
        icon = {"ok": "OK", "warning": "WARN", "error": "ERR"}[r.status]
        badge = " [FIXED]" if r.repaired else ""
        lines.append(f"### [{icon}] {r.name}{badge}")
        lines.append(f"> {r.message}")
        if r.fix_suggestion:
            lines.append(f"**Fix:** {r.fix_suggestion}")
        lines.append("---")
    return "\n".join(lines)


def main():
    import argparse
    p = argparse.ArgumentParser(description="RipoWall Diagnostics")
    p.add_argument("--repair", action="store_true", help="Reparar automaticamente")
    p.add_argument("--json", action="store_true", help="Salida JSON")
    p.add_argument("--report", action="store_true", help="Generar archivos .md y .json")
    p.add_argument("--output-dir", default=".", help="Directorio para --report")
    args = p.parse_args()

    report = run_full_diagnostic(repair=args.repair)

    if args.report:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (out / f"ripowall_diag_{ts}.md").write_text(render_markdown(report))
        (out / f"ripowall_diag_{ts}.json").write_text(render_json(report))
        print(f"Reportes guardados en {out}/")

    if args.json:
        print(render_json(report))
    else:
        print(render_terminal(report))

    sys.exit(2 if report.summary["error"] > 0 else 1 if report.summary["warning"] > 0 else 0)


if __name__ == "__main__":
    main()
