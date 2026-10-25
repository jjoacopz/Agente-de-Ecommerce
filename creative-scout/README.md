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
python creative-scout/scout.py --visible                        # ver el navegador (captcha o login)
```

Resultado en `creative-scout/salida/<fecha>/`:
- `reporte.html`: galería con miniaturas. Cada tarjeta abre el anuncio original.
- `resultados.json`: los datos crudos.

Los anuncios de Meta salen ordenados por **días activo**: si un anuncio lleva semanas corriendo,
casi seguro le está funcionando a esa marca.

Las palabras clave, el país y las fuentes se cambian en `config.json`.

## Límites

- Meta, Pinterest y TikTok cambian sus páginas seguido. Si una fuente devuelve 0 resultados,
  probá con `--visible` para ver qué pasa (captcha, login o cambio de diseño).
- Pinterest sin sesión muestra menos pines.
- Instagram y TikTok orgánico piden login para buscar, por eso el agente los busca con búsqueda web.
- En sesiones de Claude Code en la nube hay que permitir estos dominios en el acceso a red
  del entorno: `facebook.com`, `*.fbcdn.net`, `pinterest.com`, `*.pinimg.com`,
  `ads.tiktok.com`, `*.tiktokcdn.com`, `instagram.com`.
