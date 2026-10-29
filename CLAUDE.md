# CLAUDE.md — RipoWall

Proyecto RipoWall v3.2: launcher de Wallpaper Engine para Linux + GUI nativa GTK4 de gestion de wallpapers animados con Workshop nativo integrado.

## Stack

- **Lenguaje:** Python 3.11+
- **GUI:** GTK4 + libadwaita (sin Glade/XML, todo programatico)
- **WebView:** WebKitGTK 6.0 (`webkitgtk-6.0`) SOLO para SteamLoginDialog (login inicial)
- **Steam API:** `workshop_api.py` → Steam Web API (IPublishedFileService + ISteamRemoteStorage)
- **DBus:** pydbus + gdbus para Mutter DisplayConfig y Hidamari
- **Systemd:** servicios user para daemon y rotacion
- **Proton:** CachyOS SLR (o cualquier Proton compatible)

## Arquitectura v3.2

```
workshop_api.py                ← Steam Web API client: busqueda, detalles, subscribe/unsubscribe
wallpaper_engine_launcher.py  ← Lanza WE via Steam/Proton (portable, auto-detecta todo)
hidamari_core.py              ← Modulo compartido: catalogo, monitores, DBus, config, WE API
hidamari-daemon               ← Servicio systemd: rotacion cada 10 min, hotplug, Workshop watcher
hidamari-gui                  ← App GTK4 + Adwaita: galeria GridView, sidebar monitores, busqueda, WorkshopBrowser NATIVO
```

### Componentes de la GUI (hidamari-gui)

| Clase / Seccion | Proposito |
|----------------|-----------|
| `RipoWallApp` | Punto de entrada, Gtk.Application |
| `RipoWallWindow` | Ventana principal: sidebar, galeria, barra de herramientas |
| `WorkshopCard(GObject)` | Item del Workshop para GridView (publishedfileid, title, preview_path, stats, is_subscribed) |
| `WorkshopBrowser(Adw.Dialog)` | UI 100% GTK4 nativa: SearchBar, filtros, tags FlowBox, GridView, paginacion |
| `SteamLoginDialog(Adw.Dialog)` | WebView MINIMO solo para login de Steam (extrae cookie y cierra) |
| `MonitorRow` | Sidebar: icono y nombre del monitor, asignacion actual |

### Flujo del Workshop Nativo

```
WorkshopBrowser (UI GTK4 nativa)
        │
        ├─ SearchBar → workshop_api.search_workshop()
        ├─ SortDropdown → query_type (trending/popular/recent)
        ├─ TagChips → requiredtags
        ├─ GridView → WorkshopCard con thumbnails descargados via CDN
        ├─ Subscribe btn → workshop_api.subscribe(id) con cookie de sesion
        │
        ▼
Steam Web API (IPublishedFileService/QueryFiles/v1/)
        │  requiere API key en ~/.config/ripowall/steam_api_key
        ▼
Steam Community (sharedfiles/subscribe/)
        │  requiere cookie de sesion → SteamLoginDialog (WebView minimo)
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

## WorkshopBrowser — Detalles tecnicos (v3.2)

- **UI:** 100% GTK4 nativa: `Gtk.SearchEntry`, `Gtk.DropDown` (sort), `Gtk.FlowBox` (tags), `Gtk.GridView` (wallpapers)
- **API:** `workshop_api.py` consume Steam Web API (`IPublishedFileService/QueryFiles/v1/`, `ISteamRemoteStorage/GetPublishedFileDetails/v1/`)
- **API Key:** `~/.config/ripowall/steam_api_key` (gratis en https://steamcommunity.com/dev/apikey)
- **Previews:** Descargados del CDN de Steam via `workshop_api.download_preview()`, cache en `~/.cache/ripowall/workshop/`
- **Subscribe:** `POST` a `steamcommunity.com/sharedfiles/subscribe/` con cookie de sesion
- **Login:** `SteamLoginDialog` — WebView MINIMO solo para login de Steam, extrae cookie via `CookieManager.get_cookies()`, se cierra automaticamente
- **Paginacion:** Cursor-based (Steam API) + indicadores `[Prev] Pagina X de Y [Next]`
- **Threading:** API calls en `threading.Thread`, UI updates via `GLib.idle_add`

## SteamLoginDialog — Solo para extraer cookie de sesion

- **WebView:** `WebKit.WebView()` minimo, carga `steamcommunity.com/login/home/`
- **Cookie extraction:** `webview.get_network_session().get_cookie_manager().get_cookies()` async
- **Deteccion de login:** `load-changed == FINISHED` + URL sin "login" → extrae cookies
- **Seguridad:** Sin acceso al portapapeles, developer extras deshabilitados
- **Almacenamiento:** Cookie guardada en `~/.config/ripowall/steam_session` (0600)

## WebKitGTK 6.0 — Paquetes por distro

| Distro | Paquete |
|--------|---------|
| Arch | `webkitgtk-6.0` |
| Ubuntu/Debian | `libwebkitgtk-6.0-dev` |
| Fedora | `webkitgtk6.0-devel` |
| openSUSE | `webkitgtk6.0-devel` |

> La GUI requiere WebKitGTK 6.0 SOLO para el SteamLoginDialog (login inicial). Si no esta disponible, la app funciona igual pero sin posibilidad de suscribirse a wallpapers (solo busqueda y navegacion).

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

**v3.2.0** — Julio 2026

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **ripowall** (541 symbols, 1143 relationships, 48 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/ripowall/context` | Codebase overview, check index freshness |
| `gitnexus://repo/ripowall/clusters` | All functional areas |
| `gitnexus://repo/ripowall/processes` | All execution flows |
| `gitnexus://repo/ripowall/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
