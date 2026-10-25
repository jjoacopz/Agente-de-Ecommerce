"""Busca creativos publicitarios en Meta Ad Library, Pinterest y TikTok Creative Center.

Uso:
    python scout.py                       # usa config.json
    python scout.py -q "calza levanta cola" -f meta pinterest
    python scout.py --visible             # abre el navegador a la vista (útil si pide login/captcha)

Genera salida/AAAA-MM-DD_HHMM/ con resultados.json, reporte.html y las imágenes descargadas.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MESES = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def scroll(page, veces):
    for _ in range(veces):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1500)


def dias_activo(texto):
    # "Started running on Oct 3, 2026" (la página se abre en inglés para que el formato sea estable)
    m = re.search(r"Started running on (\w{3})\w* (\d{1,2}), (\d{4})", texto or "")
    if not m or m.group(1).lower() not in MESES:
        return None
    inicio = dt.date(int(m.group(3)), MESES[m.group(1).lower()], int(m.group(2)))
    return (dt.date.today() - inicio).days


# ---------- Meta Ad Library ----------
META_JS = r"""
(max) => {
  const out = [], vistos = new Set();
  const marcas = [...document.querySelectorAll('span, div')]
    .filter(e => e.childElementCount === 0 && /^Library ID:/.test(e.textContent.trim()));
  for (const m of marcas) {
    const id = (m.textContent.match(/\d{6,}/) || [])[0];
    if (!id || vistos.has(id)) continue;
    // Subir hasta la tarjeta: el ancestro más grande que contiene un solo "Library ID".
    let card = m, el = m;
    while (el.parentElement) {
      el = el.parentElement;
      if ((el.innerText.match(/Library ID:/g) || []).length > 1) break;
      card = el;
    }
    vistos.add(id);
    const imgs = [...card.querySelectorAll('img')]
      .filter(i => i.naturalWidth >= 150 || i.width >= 150).map(i => i.src);
    const vids = [...card.querySelectorAll('video')].map(v => ({src: v.src, poster: v.poster}));
    const pageLink = [...card.querySelectorAll('a[href*="facebook.com/"]')]
      .find(a => a.innerText.trim() && !a.href.includes('/ads/library'));
    out.push({
      id,
      texto: card.innerText.slice(0, 1500),
      anunciante: pageLink ? pageLink.innerText.trim() : '',
      anunciante_url: pageLink ? pageLink.href : '',
      imagenes: imgs,
      videos: vids,
    });
    if (out.length >= max) break;
  }
  return out;
}
"""


def buscar_meta(page, q, pais, maxn, scrolls):
    url = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
           f"&country={pais}&media_type=all&search_type=keyword_unordered"
           f"&q={urllib.parse.quote(q)}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    scroll(page, scrolls)
    res = []
    for a in page.evaluate(META_JS, maxn):
        texto = a.pop("texto")
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        # El copy del anuncio suele venir después de la línea "Sponsored".
        copy = ""
        if "Sponsored" in lineas:
            copy = " ".join(lineas[lineas.index("Sponsored") + 1:])[:600]
        variantes = re.search(r"(\d+) ads? use this creative", texto)
        res.append({
            "fuente": "meta",
            "busqueda": q,
            "titulo": a["anunciante"] or "Anuncio Meta",
            "url": f"https://www.facebook.com/ads/library/?id={a['id']}",
            "anunciante_url": a["anunciante_url"],
            "copy": copy,
            "dias_activo": dias_activo(texto),
            "variantes": int(variantes.group(1)) if variantes else 1,
            "es_video": bool(a["videos"]),
            "media": [v["src"] for v in a["videos"] if v["src"]],
            "miniatura": next((v["poster"] for v in a["videos"] if v["poster"]),
                              a["imagenes"][0] if a["imagenes"] else ""),
        })
    return res


# ---------- Pinterest ----------
PIN_JS = r"""
(max) => {
  const out = [], vistos = new Set();
  for (const a of document.querySelectorAll('a[href*="/pin/"]')) {
    const img = a.querySelector('img');
    if (!img || vistos.has(a.href)) continue;
    vistos.add(a.href);
    const srcs = (img.srcset || '').split(',').map(s => s.trim().split(' ')[0]).filter(Boolean);
    out.push({url: a.href, img: srcs.pop() || img.src, alt: img.alt || ''});
    if (out.length >= max) break;
  }
  return out;
}
"""


def buscar_pinterest(page, q, pais, maxn, scrolls):
    page.goto(f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(q)}",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    scroll(page, scrolls)
    return [{
        "fuente": "pinterest",
        "busqueda": q,
        "titulo": p["alt"][:120] or "Pin",
        "url": p["url"],
        "copy": p["alt"],
        "dias_activo": None,
        "variantes": 1,
        "es_video": False,
        "media": [],
        "miniatura": p["img"],
    } for p in page.evaluate(PIN_JS, maxn)]


# ---------- TikTok Creative Center (Top Ads) ----------
TT_JS = r"""
(max) => {
  const out = [], vistos = new Set();
  for (const a of document.querySelectorAll('a[href*="/topads/"]')) {
    if (vistos.has(a.href) || !/\d{6,}/.test(a.href)) continue;
    vistos.add(a.href);
    const v = a.querySelector('video'), i = a.querySelector('img');
    out.push({url: a.href, texto: a.innerText.slice(0, 400),
              poster: v ? v.poster : (i ? i.src : ''), video: v ? v.src : ''});
    if (out.length >= max) break;
  }
  return out;
}
"""


def buscar_tiktok(page, q, pais, maxn, scrolls):
    page.goto("https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en"
              f"?period=30&region={pais}&sort_by=like",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    caja = page.locator('input[placeholder*="earch"]').first
    if caja.count():
        caja.fill(q)
        caja.press("Enter")
        page.wait_for_timeout(5000)
    scroll(page, scrolls)
    return [{
        "fuente": "tiktok",
        "busqueda": q,
        "titulo": (t["texto"].splitlines() or ["Top Ad TikTok"])[0][:120],
        "url": t["url"],
        "copy": t["texto"],
        "dias_activo": None,
        "variantes": 1,
        "es_video": True,
        "media": [t["video"]] if t["video"] else [],
        "miniatura": t["poster"],
    } for t in page.evaluate(TT_JS, maxn)]


FUENTES = {"meta": buscar_meta, "pinterest": buscar_pinterest, "tiktok": buscar_tiktok}


def descargar(ctx, url, carpeta):
    # Las URLs de Meta/TikTok vencen en horas, por eso se guarda una copia local.
    if not url or url.startswith("data:"):
        return ""
    nombre = hashlib.md5(url.encode()).hexdigest()[:16] + ".jpg"
    destino = carpeta / nombre
    if not destino.exists():
        try:
            r = ctx.request.get(url, timeout=30000)
            if not r.ok:
                return ""
            destino.write_bytes(r.body())
        except Exception:
            return ""
    return f"img/{nombre}"


def reporte_html(items, errores, destino):
    tarjetas = []
    for it in items:
        meta = []
        if it["dias_activo"] is not None:
            meta.append(f"{it['dias_activo']} días activo")
        if it["variantes"] > 1:
            meta.append(f"{it['variantes']} variantes")
        if it["es_video"]:
            meta.append("video")
        img = (f'<img src="{html.escape(it["local"])}" loading="lazy">' if it.get("local")
               else '<div class="sin">sin imagen</div>')
        tarjetas.append(f"""
<a class="card {it['fuente']}" href="{html.escape(it['url'])}" target="_blank">
  {img}
  <div class="info"><b>{html.escape(it['fuente'].upper())}</b> · {html.escape(it['titulo'])}
  <small>{html.escape(' · '.join(meta))}</small>
  <p>{html.escape(it['copy'][:220])}</p>
  <small>busqueda: {html.escape(it['busqueda'])}</small></div>
</a>""")
    errs = "".join(f"<li>{html.escape(e)}</li>" for e in errores)
    destino.write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Creativos encontrados</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#faf7f8;color:#222}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}}
.card{{background:#fff;border-radius:12px;overflow:hidden;text-decoration:none;color:inherit;
box-shadow:0 1px 4px #0002;border-top:4px solid #999}}
.meta{{border-color:#1877f2}}.pinterest{{border-color:#e60023}}.tiktok{{border-color:#111}}
.card img{{width:100%;aspect-ratio:9/12;object-fit:cover;display:block}}
.sin{{aspect-ratio:9/12;display:grid;place-items:center;background:#eee;color:#888}}
.info{{padding:10px;font-size:13px}}small{{display:block;color:#666;margin-top:4px}}
p{{margin:6px 0;max-height:5.2em;overflow:hidden}}
</style>
<h1>Creativos encontrados ({len(items)})</h1>
<p>Meta ordenado por días activo: los que llevan más tiempo corriendo suelen ser los que mejor funcionan.</p>
{f'<details><summary>Errores ({len(errores)})</summary><ul>{errs}</ul></details>' if errores else ''}
<div class="grid">{''.join(tarjetas)}</div>""", encoding="utf-8")


def main():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--query", nargs="+", help="palabras clave (reemplaza las de config.json)")
    ap.add_argument("-f", "--fuentes", nargs="+", choices=list(FUENTES))
    ap.add_argument("-p", "--pais", default=cfg["pais"])
    ap.add_argument("-n", "--max", type=int, default=cfg["max_por_busqueda"])
    ap.add_argument("--visible", action="store_true", help="mostrar el navegador")
    ap.add_argument("--salida", default=str(BASE / "salida"))
    args = ap.parse_args()

    queries = args.query or cfg["palabras_clave"]
    fuentes = args.fuentes or cfg["fuentes"]
    out = Path(args.salida) / dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    (out / "img").mkdir(parents=True, exist_ok=True)

    items, errores = [], []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=not args.visible,
                                  executable_path=os.environ.get("CHROMIUM_PATH") or None)
        ctx = nav.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 1600})
        page = ctx.new_page()
        for f in fuentes:
            for q in queries:
                try:
                    encontrados = FUENTES[f](page, q, args.pais, args.max, cfg["scrolls"])
                    print(f"[{f}] {q!r}: {len(encontrados)}", file=sys.stderr)
                    items += encontrados
                except Exception as e:
                    errores.append(f"{f} / {q}: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
                    print(f"[{f}] {q!r}: ERROR {errores[-1]}", file=sys.stderr)

        # Sacar duplicados (el mismo anuncio aparece en varias búsquedas).
        unicos = {}
        for it in items:
            unicos.setdefault(it["url"], it)
        items = sorted(unicos.values(),
                       key=lambda i: (i["fuente"] != "meta", -(i["dias_activo"] or 0), -i["variantes"]))
        for it in items:
            it["local"] = descargar(ctx, it["miniatura"], out / "img")
        nav.close()

    (out / "resultados.json").write_text(
        json.dumps({"fecha": dt.datetime.now().isoformat(), "pais": args.pais, "busquedas": queries,
                    "errores": errores, "creativos": items}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    reporte_html(items, errores, out / "reporte.html")
    print(out)


if __name__ == "__main__":
    main()
