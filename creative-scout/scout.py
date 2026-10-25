"""Busca creativos publicitarios en Meta Ad Library, Pinterest y TikTok Creative Center.

Uso:
    python scout.py                       # usa config.json
    python scout.py -q "calza levanta cola" -f meta pinterest
    python scout.py --videos 15           # descarga los 15 mejores videos (por defecto 10)
    python scout.py --visible             # abre el navegador a la vista (útil si pide login/captcha)

Genera salida/AAAA-MM-DD_HHMM/ con resultados.json, reporte.html, imágenes y videos.
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
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def item(fuente, q, **kw):
    base = {"fuente": fuente, "busqueda": q, "titulo": "", "url": "", "marca": "", "copy": "",
            "dias_activo": None, "variantes": 1, "es_video": False, "video": "", "miniatura": "",
            "destino": "", "metricas": {}}
    base.update(kw)
    return base


def scroll(page, veces):
    for _ in range(veces):
        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(1500)


# ---------- Meta Ad Library ----------
# La página trae los anuncios como JSON dentro del HTML ("collated_results"). Es más estable
# que leer la pantalla y trae los links directos a imágenes y videos.
def _json_arrays(texto, clave):
    dec = json.JSONDecoder()
    i = texto.find(clave)
    while i != -1:
        try:
            arr, _ = dec.raw_decode(texto, i + len(clave))
            yield arr
        except ValueError:
            pass
        i = texto.find(clave, i + 1)


def _media_meta(snap):
    videos, imagenes = [], []
    for fuente in [snap] + list(snap.get("cards") or []):
        for v in (fuente.get("videos") or []):
            videos.append((v.get("video_hd_url") or v.get("video_sd_url") or "",
                           v.get("video_preview_image_url") or ""))
        if fuente.get("video_hd_url") or fuente.get("video_sd_url"):
            videos.append((fuente.get("video_hd_url") or fuente.get("video_sd_url"),
                           fuente.get("video_preview_image_url") or ""))
        for im in (fuente.get("images") or []):
            imagenes.append(im.get("original_image_url") or im.get("resized_image_url") or "")
        if fuente is not snap and (fuente.get("original_image_url") or fuente.get("resized_image_url")):
            imagenes.append(fuente.get("original_image_url") or fuente.get("resized_image_url"))
    return [v for v in videos if v[0]], [i for i in imagenes if i]


def buscar_meta(page, q, pais, maxn, scrolls):
    respuestas = []

    def capturar(r):
        if "graphql" in r.url:
            try:
                t = r.text()
            except Exception:
                return
            if "collated_results" in t:
                respuestas.append(t)

    page.on("response", capturar)
    try:
        url = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
               f"&country={pais}&media_type=all&search_type=keyword_unordered"
               f"&q={urllib.parse.quote(q)}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        scroll(page, scrolls)
        textos = [page.content()] + respuestas
    finally:
        page.remove_listener("response", capturar)
    if not any("collated_results" in t for t in textos):
        # Meta corta a los que buscan mucho sin sesión: devuelve "No ads match" aunque haya anuncios.
        raise RuntimeError("Meta no devolvió resultados. Si antes sí traía, es un bloqueo temporal "
                           "por muchas búsquedas: esperá un rato o corré el buscador desde tu compu")

    hoy = dt.datetime.now().timestamp()
    res, vistos = [], set()
    for t in textos:
        for grupo in _json_arrays(t, '"collated_results":'):
            for ad in grupo if isinstance(grupo, list) else []:
                aid = ad.get("ad_archive_id")
                if not aid or aid in vistos:
                    continue
                vistos.add(aid)
                snap = ad.get("snapshot") or {}
                videos, imagenes = _media_meta(snap)
                cuerpo = (snap.get("body") or {}).get("text") or ""
                if not cuerpo and snap.get("cards"):
                    cuerpo = snap["cards"][0].get("body") or ""
                inicio = ad.get("start_date")
                res.append(item(
                    "meta", q,
                    titulo=snap.get("title") or snap.get("link_description") or "",
                    url=f"https://www.facebook.com/ads/library/?id={aid}",
                    marca=ad.get("page_name") or snap.get("page_name") or "",
                    copy=cuerpo,
                    dias_activo=int((hoy - inicio) // 86400) if inicio else None,
                    variantes=ad.get("collation_count") or 1,
                    es_video=bool(videos),
                    video=videos[0][0] if videos else "",
                    miniatura=(videos[0][1] if videos else "") or (imagenes[0] if imagenes else ""),
                    destino=snap.get("link_url") or "",
                    metricas={"formato": snap.get("display_format"), "cta": snap.get("cta_text"),
                              "carrusel": len(snap.get("cards") or [])},
                ))
                if len(res) >= maxn:
                    return res
    return res


# ---------- Pinterest ----------
# Sin sesión Pinterest muestra un cartel de login, pero igual carga los resultados por su API
# interna (BaseSearchResource); se leen de ahí.
def buscar_pinterest(page, q, pais, maxn, scrolls):
    pins = []

    def capturar(r):
        if "BaseSearchResource" in r.url:
            try:
                pins.extend(((r.json().get("resource_response") or {}).get("data") or {}).get("results") or [])
            except Exception:
                pass

    page.on("response", capturar)
    try:
        page.goto(f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(q)}&rs=typed",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        scroll(page, scrolls)
    finally:
        page.remove_listener("response", capturar)

    res, vistos = [], set()
    for p in pins:
        pid = p.get("id")
        if not pid or pid in vistos or p.get("type") not in (None, "pin"):
            continue
        vistos.add(pid)
        imgs = p.get("images") or {}
        mayor = max(imgs.values(), key=lambda i: i.get("width") or 0, default={})
        img = (imgs.get("orig") or imgs.get("736x") or mayor).get("url", "")
        vlist = (p.get("videos") or {}).get("video_list") or {}
        video = next((v.get("url") for v in vlist.values() if (v.get("url") or "").endswith(".mp4")), "")
        pinner = p.get("pinner") or {}
        stats = (p.get("aggregated_pin_data") or {}).get("aggregated_stats") or {}
        res.append(item(
            "pinterest", q,
            titulo=p.get("grid_title") or p.get("title") or "",
            # Sin sesión los ids vienen cifrados ("e1_..."): no hay link al pin, sí a la búsqueda.
            url=(f"https://www.pinterest.com/pin/{pid}/" if pid.isdigit()
                 else f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(q)}"),
            marca=pinner.get("full_name") or pinner.get("username") or "",
            copy=(p.get("description") or "").strip(),
            es_video=bool(vlist),
            video=video,
            miniatura=img,
            destino=p.get("link") or "",
            metricas={"guardados": stats.get("saves") or p.get("repin_count"),
                      "promocionado": bool(p.get("is_promoted"))},
        ))
        if len(res) >= maxn:
            break
    return res


# ---------- TikTok Creative Center (Top Ads) ----------
def buscar_tiktok(page, q, pais, maxn, scrolls):
    listas = []

    def capturar(r):
        if "top_ads/v2/list" in r.url and "keyword=" in r.url:
            try:
                listas.extend((r.json().get("data") or {}).get("materials") or [])
            except Exception:
                pass

    page.on("response", capturar)
    try:
        page.goto("https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en"
                  f"?period=180&region={pais}", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        # Cerrar el cartel de bienvenida que tapa el buscador.
        page.keyboard.press("Escape")
        page.evaluate("document.querySelectorAll('.byted-modal-wrapper,.byted-modal-mask,"
                      "[class*=Popup_modal]').forEach(e => e.remove())")
        caja = page.locator('input[placeholder="Search by brand or product keywords"]:visible').first
        try:
            caja.wait_for(timeout=20000)
        except Exception:
            raise RuntimeError("no se encontró el buscador de TikTok Creative Center") from None
        caja.fill(q, force=True)
        caja.press("Enter")
        page.wait_for_timeout(6000)
        scroll(page, min(scrolls, 3))
    finally:
        page.remove_listener("response", capturar)

    res, vistos = [], set()
    for m in listas:
        if m.get("id") in vistos:
            continue
        vistos.add(m.get("id"))
        vi = m.get("video_info") or {}
        urls = vi.get("video_url") or {}
        res.append(item(
            "tiktok", q,
            titulo=m.get("ad_title") or "",
            url=f"https://ads.tiktok.com/business/creativecenter/topads/{m.get('id')}/pc/en",
            marca=m.get("brand_name") or "",
            copy=m.get("ad_title") or "",
            es_video=True,
            video=urls.get("720p") or next(iter(urls.values()), ""),
            miniatura=vi.get("cover") or "",
            metricas={"likes": m.get("like"), "ctr": m.get("ctr"),
                      "duracion_s": round(vi.get("duration") or 0)},
        ))
        if len(res) >= maxn:
            break
    return res


FUENTES = {"meta": buscar_meta, "pinterest": buscar_pinterest, "tiktok": buscar_tiktok}


def descargar(url, carpeta, ext):
    # Las URLs de Meta y TikTok vencen en horas o días, por eso se guarda una copia local.
    if not url or url.startswith("data:"):
        return ""
    nombre = hashlib.md5(url.split("?")[0].encode()).hexdigest()[:16] + ext
    destino = carpeta / nombre
    if not destino.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                destino.write_bytes(r.read())
        except Exception:
            return ""
    return f"{carpeta.name}/{nombre}"


def relevante(it, terminos):
    # Pinterest sin sesión no trae texto, así que no se puede filtrar.
    if not terminos or it["fuente"] == "pinterest":
        return True
    texto = " ".join([it["titulo"], it["copy"], it["marca"], it["destino"]]).lower()
    return any(re.search(r"\b" + re.escape(t.lower()), texto) for t in terminos)


def puntaje(it):
    # Meta: días activo y variantes (si alguien paga un anuncio hace semanas, le funciona).
    # Pinterest: guardados. TikTok: likes.
    m = it["metricas"]
    if it["fuente"] == "meta":
        return (it["dias_activo"] or 0) + 15 * (it["variantes"] - 1)
    if it["fuente"] == "pinterest":
        return (m.get("guardados") or 0) / 50
    return (m.get("likes") or 0) / 2000


def reporte_html(items, errores, destino):
    tarjetas = []
    for it in items:
        datos = []
        if it["dias_activo"] is not None:
            datos.append(f"{it['dias_activo']} días activo")
        if it["variantes"] > 1:
            datos.append(f"{it['variantes']} variantes")
        for k, v in it["metricas"].items():
            if v not in (None, "", [], False, 0):
                datos.append(f"{k}: {v}")
        if it.get("video_local"):
            media = (f'<video src="{html.escape(it["video_local"])}" poster="{html.escape(it.get("local", ""))}"'
                     ' controls preload="none" playsinline></video>')
        elif it.get("local"):
            media = f'<img src="{html.escape(it["local"])}" loading="lazy">'
        else:
            media = '<div class="sin">sin imagen</div>'
        destino_link = (f' · <a href="{html.escape(it["destino"])}" target="_blank">destino</a>'
                        if it["destino"] else "")
        tarjetas.append(f"""
<div class="card {it['fuente']}">
  {media}
  <div class="info"><b>{html.escape(it['fuente'].upper())}</b>{' · VIDEO' if it['es_video'] else ''}
  · {html.escape(it['marca'] or it['titulo'][:60])}
  <small>{html.escape(' · '.join(datos))}</small>
  <p>{html.escape(it['copy'][:260])}</p>
  <small><a href="{html.escape(it['url'])}" target="_blank">ver original</a>{destino_link}
  · búsqueda: {html.escape(it['busqueda'])}</small></div>
</div>""")
    errs = "".join(f"<li>{html.escape(e)}</li>" for e in errores)
    destino.write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Creativos encontrados</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#faf7f8;color:#222}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}}
.card{{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px #0002;border-top:4px solid #999}}
.meta{{border-color:#1877f2}}.pinterest{{border-color:#e60023}}.tiktok{{border-color:#111}}
.card img,.card video{{width:100%;aspect-ratio:9/12;object-fit:cover;display:block;background:#000}}
.sin{{aspect-ratio:9/12;display:grid;place-items:center;background:#eee;color:#888}}
.info{{padding:10px;font-size:13px}}small{{display:block;color:#666;margin-top:4px}}
p{{margin:6px 0;max-height:6.5em;overflow:hidden;white-space:pre-line}}
</style>
<h1>Creativos encontrados ({len(items)})</h1>
<p>Ordenados por señal de rendimiento: en Meta, días activo y variantes; en Pinterest, guardados;
en TikTok, likes. Un anuncio que lleva semanas activo casi seguro le funciona a esa marca.</p>
{f'<details><summary>Errores ({len(errores)})</summary><ul>{errs}</ul></details>' if errores else ''}
<div class="grid">{''.join(tarjetas)}</div>""", encoding="utf-8")


def main():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--query", nargs="+", help="palabras clave (reemplaza las de config.json)")
    ap.add_argument("-f", "--fuentes", nargs="+", choices=list(FUENTES))
    ap.add_argument("-p", "--pais", default=cfg["pais"])
    ap.add_argument("-n", "--max", type=int, default=cfg["max_por_busqueda"])
    ap.add_argument("--videos", type=int, default=cfg.get("videos_a_descargar", 10),
                    help="cuántos videos (los de mejor puntaje) descargar")
    ap.add_argument("--visible", action="store_true", help="mostrar el navegador")
    ap.add_argument("--salida", default=str(BASE / "salida"))
    args = ap.parse_args()

    queries = args.query or cfg["palabras_clave"]
    fuentes = args.fuentes or cfg["fuentes"]
    out = Path(args.salida) / dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    (out / "img").mkdir(parents=True, exist_ok=True)
    (out / "video").mkdir(exist_ok=True)

    items, errores = [], []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=not args.visible,
                                executable_path=os.environ.get("CHROMIUM_PATH") or None)
        for f in fuentes:
            for q in queries:
                # Una sesión nueva por búsqueda: Meta y TikTok se traban con sesiones reusadas.
                ctx = nav.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 1600})
                page = ctx.new_page()
                try:
                    if f == "meta":
                        page.wait_for_timeout(8000)  # espaciar las búsquedas para que Meta no corte
                    try:
                        encontrados = FUENTES[f](page, q, args.pais, args.max, cfg["scrolls"])
                    except RuntimeError:
                        if f != "meta":
                            raise
                        print(f"[{f}] {q!r}: sin resultados, reintento en 60 s", file=sys.stderr)
                        page.wait_for_timeout(60000)
                        encontrados = FUENTES[f](page, q, args.pais, args.max, cfg["scrolls"])
                    print(f"[{f}] {q!r}: {len(encontrados)}", file=sys.stderr)
                    items += encontrados
                except Exception as e:
                    errores.append(f"{f} / {q}: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
                    print(f"[{f}] {q!r}: ERROR {errores[-1]}", file=sys.stderr)
                finally:
                    ctx.close()

        # Sacar duplicados (el mismo anuncio aparece en varias búsquedas).
        unicos = {}
        for it in items:
            unicos.setdefault((it["url"], it["miniatura"] if it["fuente"] == "pinterest" else ""), it)
        antes = len(unicos)
        items = [it for it in unicos.values() if relevante(it, cfg.get("terminos_relevantes"))]
        print(f"{antes - len(items)} descartados por no ser del rubro", file=sys.stderr)
        items = sorted(items, key=puntaje, reverse=True)
        print(f"descargando {len(items)} miniaturas...", file=sys.stderr)
        for it in items:
            it["local"] = descargar(it["miniatura"], out / "img", ".jpg")
        con_video = [it for it in items if it["video"]][:args.videos]
        print(f"descargando {len(con_video)} videos...", file=sys.stderr)
        for it in con_video:
            it["video_local"] = descargar(it["video"], out / "video", ".mp4")
        nav.close()

    (out / "resultados.json").write_text(
        json.dumps({"fecha": dt.datetime.now().isoformat(), "pais": args.pais, "busquedas": queries,
                    "errores": errores, "creativos": items}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    reporte_html(items, errores, out / "reporte.html")
    print(out)


if __name__ == "__main__":
    main()
