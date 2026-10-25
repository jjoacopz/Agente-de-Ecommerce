# Creative Scout

Agente que busca creativos de la competencia en la **Biblioteca de anuncios de Meta**
(Facebook e Instagram), **Pinterest**, **TikTok Creative Center** y, por búsqueda web,
**reels de Instagram, TikTok y YouTube Shorts**. Arma una galería y un informe con
guiones adaptados a tu oferta.

## Uso con Claude Code (recomendado)

Abrí Claude Code en este repo y pedile, por ejemplo:

> Usá el agente creative-scout para buscar creativos de calzas levanta cola sin costura
> para promocionar 2x1: 2 calzas + 2 tops de regalo a $1790.

El agente (`.claude/agents/creative-scout.md`) corre el buscador, completa con búsqueda web,
elige los mejores y escribe `informe.md` con 5 guiones listos para grabar.

## Uso directo del buscador

```bash
pip install -r creative-scout/requirements.txt
python -m playwright install chromium
python creative-scout/scout.py                                  # palabras de config.json
python creative-scout/scout.py -q "calza seamless" "calzas 2x1" -f meta
python creative-scout/scout.py --videos 20                      # descargar los 20 mejores videos
python creative-scout/scout.py --visible                        # ver el navegador (captcha o login)
```

Resultado en `creative-scout/salida/<fecha>/`:
- `reporte.html`: galería con miniaturas y videos que se reproducen ahí mismo. Cada tarjeta
  tiene el link al anuncio original y a la página a la que lleva.
- `resultados.json`: los datos crudos.
- `img/` y `video/`: copias locales (los links de Meta y TikTok vencen en pocos días).

Orden: en Meta por **días activo** y cantidad de variantes (si un anuncio lleva semanas corriendo,
casi seguro le está funcionando a esa marca); en TikTok por likes.

En `config.json` se cambian las palabras clave, el país, las fuentes, cuántos videos bajar y
`terminos_relevantes`: los anuncios de Meta y TikTok que no mencionan ninguno se descartan.

## Límites

- Meta corta a quien hace muchas búsquedas seguidas sin sesión: devuelve "no hay anuncios".
  El buscador espera entre búsquedas y reintenta una vez; si igual falla, esperá un rato.
- Pinterest sin sesión solo entrega las imágenes, sin texto ni link al pin.
- TikTok Creative Center tiene pocos anuncios del rubro en Argentina.
- Meta, Pinterest y TikTok cambian sus páginas seguido. Si una fuente devuelve 0 resultados,
  probá con `--visible` para ver qué pasa (captcha, login o cambio de diseño).
- Instagram y TikTok orgánico piden login para buscar, por eso el agente los busca con búsqueda web.
- En sesiones de Claude Code en la nube hay que permitir estos dominios en el acceso a red
  del entorno: `facebook.com`, `*.fbcdn.net`, `pinterest.com`, `*.pinimg.com`,
  `ads.tiktok.com`, `*.tiktokcdn.com`, `instagram.com`.
