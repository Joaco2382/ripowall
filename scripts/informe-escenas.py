#!/usr/bin/env python3
"""
Página de comparación de escenas: vista previa oficial vs captura de linux-wallpaperengine.

    scripts/informe-escenas.py <carpeta-medicion> [salida.html]

La carpeta de medición es la que deja scripts/capturar-escena.sh: resultados.txt (id|estado|código|ms)
y capturas/<id>.png + capturas/<id>.log. Las imágenes van incrustadas (miniaturas JPEG), así la página
es un solo archivo. Clasificación automática:
  bien      hay captura y no está vacía
  vacía     la captura es casi de un solo color (negra o en blanco): el motor no dibujó la escena
  sin-captura / se-cayó   el motor no llegó a capturar o terminó antes
"""

import base64
import html
import io
import json
import os
import re
import sys
from collections import Counter

from PIL import Image, ImageStat

WORKSHOP = os.path.expanduser("~/.local/share/Steam/steamapps/workshop/content/431960")
MINI = (320, 180)
# Avisos del motor que dicen qué falta (se agrupan sin los nombres de archivo)
AVISO = re.compile(r"(unsupported|not supported|cannot|can't|failed|error|unknown|not implemented|missing)", re.I)
# Ruido del entorno de medición (mutter sin pantalla): sale en todas las escenas y no dice nada de ellas
RUIDO = re.compile(r"No GLX display|platform does not support setting the window position|"
                   r"Fullscreen detection not supported", re.I)


def miniatura(ruta: str) -> str | None:
    try:
        img = Image.open(ruta)
        img.seek(0)  # primer cuadro si es GIF
        img = img.convert("RGB")
        img.thumbnail(MINI)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001 — una imagen rota no debe tumbar el informe
        print(f"no se pudo leer {ruta}: {e}", file=sys.stderr)
        return None


def vacia(ruta: str) -> bool:
    """Casi un solo color (desviación muy baja en los tres canales)."""
    st = ImageStat.Stat(Image.open(ruta).convert("RGB").resize((160, 90)))
    return max(st.stddev) < 6


def avisos(log: str) -> list[str]:
    try:
        lineas = open(log, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return []
    vistos = []
    for linea in lineas:
        if AVISO.search(linea) and not RUIDO.search(linea):
            # «Unsupported puppet model header MDLV0014 in models/x.mdl» -> «Unsupported puppet model header MDLV0014»
            tipo = re.sub(r"\s+(in|at|for|from)\s+\S+.*$", "", linea.strip())
            tipo = re.sub(r"\S+\.(mdl|tex|json|frag|vert|png|jpg|mp3|ogg)\b", "<archivo>", tipo)[:140]
            if tipo not in vistos:
                vistos.append(tipo)
    return vistos


def main() -> int:
    med = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else os.path.join(med, "escenas.html")
    filas = []
    for linea in open(os.path.join(med, "resultados.txt"), encoding="utf-8"):
        partes = linea.strip().split("|")
        if len(partes) != 4:
            continue
        wid, estado, codigo, ms = partes
        proj = {}
        try:
            proj = json.load(open(os.path.join(WORKSHOP, wid, "project.json"), encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{wid}: sin project.json ({e})", file=sys.stderr)
        cap = os.path.join(med, "capturas", f"{wid}.png")
        if estado == "captura-ok" and vacia(cap):
            estado = "vacía"
        filas.append({
            "id": wid, "estado": estado, "codigo": codigo, "ms": ms,
            "titulo": proj.get("title") or wid,
            "mature": str(proj.get("contentrating", "")).lower() == "mature",
            "previa": miniatura(os.path.join(WORKSHOP, wid, proj.get("preview", "preview.jpg"))),
            "captura": miniatura(cap) if os.path.isfile(cap) else None,
            "avisos": avisos(os.path.join(med, "capturas", f"{wid}.log")),
        })

    estados = Counter(f["estado"] for f in filas)
    tipos = Counter(a for f in filas for a in f["avisos"])
    total = len(filas)

    def img(b64, clase=""):
        return f'<img class="{clase}" src="data:image/jpeg;base64,{b64}">' if b64 else '<div class="nada">sin imagen</div>'

    tarjetas = []
    for f in filas:
        av = "".join(f"<li>{html.escape(a)}</li>" for a in f["avisos"][:6])
        blur = "mature" if f["mature"] else ""
        tarjetas.append(f"""
<article class="t {f['estado']}" data-estado="{f['estado']}" data-avisos="{1 if f['avisos'] else 0}">
  <h3>{html.escape(f['titulo'])}</h3>
  <div class="par"><figure>{img(f['previa'], blur)}<figcaption>Vista previa oficial</figcaption></figure>
  <figure>{img(f['captura'], blur)}<figcaption>Motor ({f['ms']})</figcaption></figure></div>
  <p class="estado">{f['estado']} · <a href="https://steamcommunity.com/sharedfiles/filedetails/?id={f['id']}">{f['id']}</a></p>
  {f'<ul>{av}</ul>' if av else ''}
</article>""")

    resumen_tipos = "".join(f"<tr><td>{n}</td><td>{html.escape(t)}</td></tr>" for t, n in tipos.most_common(15))
    chips = " · ".join(f"<b>{n}</b> {e}" for e, n in estados.most_common())
    pagina = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Escenas RipoWall</title>
<style>
:root{{--bg:#f6f6f4;--fg:#1d1d1b;--card:#fff;--muted:#6b6b66;--ok:#1a7f37;--bad:#c62828;--warn:#b26a00;--line:#e2e2dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecece8;--card:#1f1f1d;--muted:#a3a39c;--line:#33332f}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:16px}}
h1{{margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 16px}}
.filtros button{{margin:0 6px 8px 0;padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}}
.filtros button.on{{background:var(--fg);color:var(--bg)}}
table{{border-collapse:collapse;margin:8px 0 20px;max-width:100%}} td{{border-bottom:1px solid var(--line);padding:4px 10px;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,680px),1fr));gap:14px}}
.t{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;border-left:5px solid var(--ok)}}
.t.vacía,.t.se-cayó,.t.sin-captura{{border-left-color:var(--bad)}} .t h3{{margin:0 0 8px;font-size:15px}}
.par{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} figure{{margin:0}} img{{width:100%;border-radius:6px;display:block}}
img.mature{{filter:blur(18px);cursor:pointer}} figcaption,.estado{{color:var(--muted);font-size:12px}}
ul{{margin:6px 0 0;padding-left:18px;font-size:12px;color:var(--warn)}} .nada{{aspect-ratio:16/9;display:grid;place-items:center;background:var(--line);border-radius:6px;font-size:12px}}
a{{color:inherit}}
</style></head><body>
<h1>Tus escenas en linux-wallpaperengine</h1>
<p class="sub">{total} escenas medidas · {chips}</p>
<h2>Avisos más frecuentes del motor</h2>
<p class="sub">Qué funciones fallan y en cuántas escenas tuyas: lo de más arriba es lo primero que conviene arreglar.</p>
<table>{resumen_tipos or '<tr><td>sin avisos</td></tr>'}</table>
<div class="filtros">
<button class="on" data-f="todas">Todas</button><button data-f="problemas">Con problemas</button>
<button data-f="avisos">Con avisos</button><button data-f="bien">Bien</button></div>
<div class="grid">{''.join(tarjetas)}</div>
<script>
document.querySelectorAll('img.mature').forEach(i=>i.addEventListener('click',()=>i.classList.remove('mature')));
document.querySelectorAll('.filtros button').forEach(b=>b.addEventListener('click',()=>{{
  document.querySelectorAll('.filtros button').forEach(x=>x.classList.toggle('on',x===b));
  const f=b.dataset.f;
  document.querySelectorAll('.t').forEach(t=>{{
    const e=t.dataset.estado, mal=e!=='captura-ok';
    t.style.display=(f==='todas'||(f==='problemas'&&mal)||(f==='bien'&&!mal)||(f==='avisos'&&t.dataset.avisos==='1'))?'':'none';
  }});
}}));
</script></body></html>"""
    with open(salida, "w", encoding="utf-8") as fh:
        fh.write(pagina)
    print(f"{salida}: {total} escenas ({chips.replace('<b>', '').replace('</b>', '')})")
    for t, n in tipos.most_common(8):
        print(f"  {n:3d}  {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
