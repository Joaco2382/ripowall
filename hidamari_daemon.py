#!/usr/bin/env python3
"""
Hidamari Daemon — Wallpapers inteligentes multi-monitor.
Usa hidamari_core para toda la lógica compartida.

Servicio systemd:
  systemctl --user enable --now hidamari-daemon.service
"""

import os
import random
import select
import signal
import subprocess
import sys
import time

# hidamari_core.py se importa desde la carpeta real del script (repo, ~/.local/bin o /usr/bin)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # hidamari_core.py va junto al script

from hidamari_core import (
    get_all_wallpapers,
    get_connected_monitors,
    get_display_layout,
    get_rotate_minutes,
    load_config,
    load_settings,
    save_settings,
    save_config,
    sanitize_hidamari_config,
    reload_config,
    pick_random_wallpapers,
    rebuild_flat_folder,
)

# Usar rutas del core (portable, multi-distro)
WORKSHOP = os.path.expanduser("~/.local/share/Steam/steamapps/workshop/content/431960")
CONFIG = os.path.expanduser("~/.config/hidamari/config.json")

running = True


def log(msg):
    print(f"[hidamari] {msg}", flush=True)


def shutdown(sig, frame):
    global running
    log("Apagando...")
    running = False


def clean_monitors(config):
    """Elimina del data_source los monitores que ya no están conectados.
    Siempre mantiene 'Default'. Recuerda el wallpaper de cada uno para devolvérselo
    si se vuelve a conectar (ajustes de RipoWall: monitores_recordados)."""
    monitors = get_connected_monitors()
    active_conns = {m.connector for m in monitors}
    active_conns.add("Default")

    ds = config.get("data_source", {})
    removed = {}
    for key in list(ds.keys()):
        if key not in active_conns:
            removed[key] = ds.pop(key)

    if removed:
        log(f"Monitores huérfanos eliminados: {list(removed)}")
        settings = load_settings()
        settings.setdefault("monitores_recordados", {}).update(removed)
        if not save_settings(settings):
            log("No se pudo recordar el wallpaper de los monitores desconectados")


def missing_monitors(config, wallpapers):
    """Monitores conectados que no tienen un wallpaper valido asignado."""
    ds = config.get("data_source", {})
    valid_paths = {w.path for w in wallpapers}
    return [m.connector for m in get_connected_monitors() if ds.get(m.connector) not in valid_paths]


def assign_wallpapers_to_config(config, wallpapers, only=None):
    """Asigna un wallpaper distinto a los monitores conectados y guarda config.

    only: conectores a los que asignar. None = todos (rotacion). Al conectar un
    monitor o arrancar sin rotacion se pasan solo los que no tienen wallpaper,
    para no pisar lo que el usuario eligio en los demas.
    """
    monitors = get_connected_monitors()
    clean_monitors(config)

    ds = config.setdefault("data_source", {})
    current_paths = set(ds.values())

    conns = [m.connector for m in monitors]
    targets = conns if only is None else [c for c in conns if c in only]

    assignment = {}
    if only is not None:
        # Un monitor que vuelve a conectarse recupera el wallpaper que tenia
        valid_paths = {w.path for w in wallpapers}
        remembered = load_settings().get("monitores_recordados", {})
        for conn in list(targets):
            if remembered.get(conn) in valid_paths:
                assignment[conn] = remembered[conn]
                targets.remove(conn)
    if targets:
        picked = pick_random_wallpapers(targets, wallpapers, current_paths)
        if not picked and wallpapers:
            picked = pick_random_wallpapers(targets, wallpapers)  # sin avoid
        assignment.update(picked)

    for conn, path in assignment.items():
        ds[conn] = path

    # Default = el del primer monitor (o uno al azar si no hay monitores ni Default)
    if conns and ds.get(conns[0]):
        ds["Default"] = ds[conns[0]]
    elif wallpapers and not ds.get("Default"):
        ds["Default"] = random.choice(wallpapers).path

    config["mode"] = "MODE_VIDEO"
    # El silencio lo decide el usuario (is_mute); no forzar volumen 0,
    # que deja el fundido de Hidamari colgado y pausar no hace nada.
    sanitize_hidamari_config(config)
    save_config(config)

    for mon, path in assignment.items():
        wp = next((w for w in wallpapers if w.path == path), None)
        name = wp.title if wp else os.path.basename(path)[:50]
        log(f"  {mon}: {name}")

    return config


def watch_workshop(config, known_count):
    """Detecta cambios en el Workshop y actualiza Default."""
    wallpapers = get_all_wallpapers()
    count = len(wallpapers)

    if count != known_count:
        if count < known_count:
            log(f"Se eliminaron {known_count - count} wallpapers")
        elif count > known_count and wallpapers:
            log(f"Nuevo wallpaper: {wallpapers[0].title}")

        rebuild_flat_folder()

        if wallpapers and wallpapers[0].path != config.get("data_source", {}).get("Default", ""):
            config["data_source"]["Default"] = wallpapers[0].path
            save_config(config)
            reload_config()

    return count


def main():
    global running

    # None = leer el intervalo de ~/.config/ripowall/settings.json (lo cambia la GUI)
    cli_rotate_minutes = None
    do_rotate = True
    once = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--rotate-min" and i + 1 < len(args):
            cli_rotate_minutes = int(args[i + 1])
            i += 2
        elif args[i] == "--no-rotate":
            do_rotate = False
            i += 1
        elif args[i] == "--once":
            once = True
            do_rotate = False
            i += 1
        else:
            i += 1

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    wallpapers = get_all_wallpapers()
    log(f"Iniciado — {len(wallpapers)} wallpapers disponibles")

    if not wallpapers:
        log("No hay wallpapers. Suscribite a algunos en Steam.")
        if once:
            return
        while running:
            time.sleep(10)
            wallpapers = get_all_wallpapers()
            if wallpapers:
                log(f"¡{len(wallpapers)} wallpapers encontrados!")
                break
        if not running:
            return

    config = load_config()
    if not config:
        log("Error cargando config, usando defaults")
        config = {"data_source": {"Default": wallpapers[0].path}, "mode": "MODE_VIDEO"}
        save_config(config)

    def rotate_minutes():
        return cli_rotate_minutes if cli_rotate_minutes is not None else get_rotate_minutes()

    rebuild_flat_folder()  # limpia symlinks rotos de wallpapers borrados
    clean_monitors(config)
    if sanitize_hidamari_config(config):
        log("config.json de Hidamari reparada (fade_interval/audio_volume)")
        save_config(config)

    missing = missing_monitors(config, wallpapers)
    if (do_rotate and rotate_minutes() > 0) or once:
        log("Asignando wallpapers...")
        config = assign_wallpapers_to_config(config, wallpapers)
    elif missing:
        # Sin rotacion: solo los monitores sin wallpaper; el resto conserva el elegido
        log(f"Asignando wallpaper a monitores sin uno: {', '.join(missing)}")
        config = assign_wallpapers_to_config(config, wallpapers, only=missing)
    else:
        log("Rotación desactivada: se mantiene el wallpaper elegido")
    reload_config()

    if once:
        log("Listo (--once).")
        return

    known_count = len(wallpapers)
    last_rotate = time.time()
    # Para detectar cuando el usuario elige un wallpaper a mano desde la GUI
    last_ds = dict(load_config().get("data_source", {}))

    last_mins = rotate_minutes()
    if do_rotate:
        log(f"Rotación cada {last_mins} min" if last_mins else "Rotación desactivada")

    log("Vigilando cambios en Steam Workshop...")
    log("Conectá/desconectá monitores — se detecta solo.")

    # Hotplug watcher
    monitor_watcher = None
    try:
        monitor_watcher = subprocess.Popen(
            ["gdbus", "monitor", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
             "--object-path", "/org/gnome/Mutter/DisplayConfig"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )
    except Exception:
        log("No se pudo iniciar el watcher de hotplug")
    known_layout = get_display_layout()

    while running:
        try:
            time.sleep(3)

            # 1. Workshop
            wallpapers = get_all_wallpapers()
            if wallpapers:
                new_count = len(wallpapers)
                if new_count != known_count:
                    known_count = watch_workshop(config, known_count)
                    wallpapers = get_all_wallpapers()

            # 2. Hotplug
            if monitor_watcher and monitor_watcher.poll() is None:
                try:
                    ready, _, _ = select.select([monitor_watcher.stdout], [], [], 0)
                    if ready:
                        line = monitor_watcher.stdout.readline()
                        if line:
                            time.sleep(1)
                            current = get_connected_monitors()
                            ds = load_config().get("data_source", {})
                            current_conns = {m.connector for m in current}
                            known_conns = set(ds.keys()) - {"Default"}
                            if current_conns != known_conns:
                                log(f"Cambio de monitores: {len(current)} activos")
                                config = load_config()
                                # Solo los recien conectados reciben wallpaper nuevo; los
                                # desconectados los quita clean_monitors. Los demas no cambian.
                                config = assign_wallpapers_to_config(
                                    config, wallpapers, only=missing_monitors(config, wallpapers))
                                reload_config()
                            else:
                                layout = get_display_layout()
                                if layout and layout != known_layout:
                                    # Escala o resolución cambió: el player queda con la
                                    # ventana del tamaño viejo, hay que recrearlo.
                                    log("Cambio de escala/resolución — recargando player")
                                    reload_config()
                            known_layout = get_display_layout() or known_layout
                except Exception as e:
                    log(f"Error en watcher de monitores: {e}")

            # 3. Rotación
            ds_now = load_config().get("data_source", {})
            if ds_now and ds_now != last_ds:
                # Alguien (la GUI) cambió el wallpaper: el contador parte de cero
                # para que la rotación no le pise la elección enseguida.
                last_ds = dict(ds_now)
                last_rotate = time.time()
            mins = rotate_minutes()
            if do_rotate and mins != last_mins:
                # Cambiado desde la GUI (~/.config/ripowall/settings.json)
                log(f"Rotación cambiada: cada {mins} min" if mins else "Rotación cambiada: desactivada")
                last_mins = mins
            if do_rotate and mins > 0 and time.time() - last_rotate > mins * 60:
                log("Rotación...")
                config = load_config()
                config = assign_wallpapers_to_config(config, wallpapers)
                reload_config()
                last_rotate = time.time()
                last_ds = dict(config.get("data_source", {}))

        except Exception as e:
            log(f"Error: {e}")
            time.sleep(5)

    if monitor_watcher:
        try:
            monitor_watcher.terminate()
            monitor_watcher.wait(timeout=2)
        except Exception:
            monitor_watcher.kill()

    log("Daemon detenido.")


if __name__ == "__main__":
    main()
