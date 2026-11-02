# CLAUDE.md — RipoWall

RipoWall: fondos animados de Wallpaper Engine (video, web, presets y escenas) en GNOME 45-51 sobre Wayland.
Para usuarios: `README.md` (inglés) y `README.es.md`.

## Stack

- **Python 3.11+**, GTK4 + libadwaita (todo programático, sin XML), WebKitGTK 6.0, GStreamer (Gtk.MediaFile)
- **Extensión de GNOME Shell** (GJS, ESM, GNOME 45+): `extension/ripowall@ripotech.cl/`
- **Motor de escenas:** linux-wallpaperengine en un commit fijo + parches propios (`engine/`)
- **Systemd user:** `hidamari-daemon.service` (rotación, monitores, Workshop)

## Arquitectura

```
hidamari_core.py        catálogo del Workshop (video/web/scene/preset), config ~/.config/ripowall/config.json,
                        control del reproductor por D-Bus. No importa GTK (lo comparten daemon y GUI).
hidamari_daemon.py      servicio: asigna/rota fondos, monitores conectados/desconectados, suscripciones nuevas
hidamari_gui.py         app GTK4: galería, monitores, rotación, navegador del Workshop (workshop_api.py)
ripowall_renderer.py    reproductor: una ventana por monitor, título «@ripowall!<conector>»; acciones D-Bus
                        (pausado, silencio, volumen, cubierto, recargar, escenas). Web: esquema ripowall-fondo://
                        que solo sirve la carpeta del fondo.
extension.js            lanza el reproductor y linux-wallpaperengine como Meta.WaylandClient, mantiene sus ventanas
                        minimizadas y fuera de Alt+Tab/actividades, pone un Clutter.Clone en el fondo de cada monitor
                        (asociado por conector) y pausa al tapar el monitor una ventana maximizada.
ripowall_diagnostics.py revisa la instalación (extensión, reproductor, códec H.264, Wayland, Workshop)
```

`hidamari-gui` y `hidamari-daemon` son enlaces a los `.py` (nombres históricos de cuando usaba Hidamari).

## Compatibilidad de la extensión

- GNOME 45-48: `Meta.WaylandClient.new()` + `spawnv()`; GNOME 49+: `new_subprocess()`. Se detecta en `ClienteWayland`.
- GNOME 50 quitó X11 (y `Meta.is_wayland_compositor`): usar APIs de Meta solo si existen.
- Después de cada cambio de la extensión, correr la matriz completa (abajo), no solo la versión de este PC.

## Pruebas

```bash
python3 -m unittest discover -s tests                     # (GDK_BACKEND=x11 si GTK se cuelga en la terminal)
scripts/probar-gnome-docker.sh <distro>                   # GNOME de otra distro en Docker (ver distros en el script)
MONITORES="1920x1080 1280x1024" PRUEBA=caida|ciclo scripts/probar-gnome-docker.sh <distro>
scripts/probar-instalador-docker.sh <distro>              # install.sh de punta a punta
scripts/probar-extension.sh                               # GNOME anidado en este PC
scripts/capturar-escena.sh <salida> <id>                  # captura de una escena con el motor
python3 ripowall_diagnostics.py                           # diagnóstico de la instalación real
```

CI (`.github/workflows/ci.yml`): ggshield + compila, ruff (E9,F) y la suite con xvfb, gjs y WebKit reales.

## Convenciones

- Type hints en funciones públicas y docstrings; sin rutas fijas (`Path.home()`, detección en runtime)
- Operaciones bloqueantes de la GUI en `threading` + `GLib.idle_add`
- Errores visibles: nada de `except: pass`; registrar y avisar en la GUI
- Pruebas que puedan fallar: cada arreglo con su prueba, comprobando que falla sin el arreglo

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
