#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apify_portales.py — busca coches usando los actores de Apify (de pago, céntimos
por búsqueda). Apify ya tiene resueltos los bloqueos de los portales, así que
desde el servidor SÍ devuelve resultados.

Reutiliza extraer_marca_modelo y num del módulo 'portales'.
La config de Apify (token y actores) va en config.json -> "apify".
"""

import re
import requests
from portales import extraer_marca_modelo, num, _dedupe


def _norm_item(raw: dict, source: str) -> dict | None:
    """Normaliza un anuncio de Apify a nuestro formato estándar."""
    # Los actores devuelven campos con nombres variados; probamos varios
    title = (raw.get("title") or raw.get("name") or raw.get("titulo") or "").strip()
    if not title and not raw.get("price"):
        return None

    price = (raw.get("price") or raw.get("precio") or raw.get("cash")
             or raw.get("salePrice") or raw.get("sale_price"))
    if isinstance(price, dict):
        price = price.get("amount") or price.get("cash")

    url = (raw.get("url") or raw.get("link") or raw.get("itemUrl")
           or raw.get("web_slug") or "")
    if url and not str(url).startswith("http"):
        url = f"https://es.wallapop.com/item/{url}"

    item_id = (raw.get("id") or raw.get("itemId") or raw.get("adId")
               or url or title[:25])

    marca = raw.get("brand") or raw.get("make") or raw.get("marca")
    modelo = raw.get("model") or raw.get("modelo")
    if not marca:
        marca, modelo = extraer_marca_modelo(title)

    loc = raw.get("location") or {}
    if isinstance(loc, dict):
        city = loc.get("city") or loc.get("name") or ""
    else:
        city = str(loc)
    if not city:
        # rastriq/wallapop-cars-scraper trae "region" (p.ej. "Cataluña")
        city = (raw.get("city") or raw.get("province")
                or raw.get("region") or "")

    fuel = (raw.get("fuel") or raw.get("fuelType") or raw.get("engine")
            or raw.get("combustible") or "")

    return {
        "id": f"{source.lower()}_{item_id}",
        "source": source,
        "title": title,
        "description": raw.get("description") or raw.get("descripcion") or "",
        "price": num(price),
        "year": num(raw.get("year") or raw.get("anyo") or raw.get("ano")),
        "km": num(raw.get("km") or raw.get("kms") or raw.get("mileage")
                  or raw.get("kilometers")),
        "fuel": str(fuel).lower(),
        "make": (str(marca).title() if marca else None),
        "model": (str(modelo).title() if modelo else None),
        "city": city,
        "url": url or "https://es.wallapop.com",
        "seller_type": raw.get("seller_type") or raw.get("sellerType") or "",
        "version": raw.get("version") or "",
    }


# ============================================================
#  PERFIL MOTOS DE AGUA — el actor fayoussef NO rellena marca/modelo/año/horas
#  en acuáticas, así que lo sacamos del TEXTO del anuncio.
# ============================================================
def _isnum(x) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


# Marcas acuáticas (clave en minúsculas -> nombre bonito)
_MARCAS_MOTO = {
    "sea-doo": "Sea-Doo", "seadoo": "Sea-Doo", "sea doo": "Sea-Doo",
    "bombardier": "Sea-Doo",
    "yamaha": "Yamaha", "waverunner": "Yamaha", "wave runner": "Yamaha",
    "kawasaki": "Kawasaki", "honda": "Honda", "polaris": "Polaris",
}
# Modelos acuáticos, de MÁS específico a menos (se coge el primero que aparezca)
_MODELOS_MOTO = [
    "gti se", "gti limited", "gti 130", "gti 155", "gti 90", "gti",
    "gtx limited", "gtx 300", "gtx", "gtr",
    "rxp-x", "rxp", "rxt-x", "rxt",
    "spark trixx", "spark 3up", "spark 2up", "spark",
    "wake pro", "wake 170", "wake", "fish pro", "fishpro", "explorer pro",
    "fx svho", "fx cruiser ho", "fx cruiser", "fx ho", "fx",
    "vx cruiser ho", "vx cruiser", "vx deluxe", "vx limited", "vx-c", "vx",
    "ex deluxe", "ex sport", "ex limited", "ex",
    "gp1800r", "gp1800", "gp 1800", "superjet", "super jet", "jetblaster",
    "ultra 310lx", "ultra 310", "ultra 300", "ultra lx", "ultra",
    "stx-15f", "stx 160", "stx160", "stx", "sx-r", "sxr", "aquatrax",
]
_RE_HORAS_A = re.compile(r"(\d{1,4})\s*(?:horas?|hrs?|h)\b", re.I)
_RE_HORAS_B = re.compile(r"horas?\s*[:\-]?\s*(\d{1,4})", re.I)
_RE_ANYO = re.compile(r"\b(19[8-9]\d|20[0-2]\d)\b")


def _marca_modelo_moto(texto: str):
    t = (texto or "").lower()
    marca = None
    for k in sorted(_MARCAS_MOTO, key=len, reverse=True):
        if k in t:
            marca = _MARCAS_MOTO[k]
            break
    modelo = None
    for m in _MODELOS_MOTO:
        if m in t:
            modelo = m.upper()
            break
    return marca, modelo


def _extraer_horas(texto: str):
    for rx in (_RE_HORAS_A, _RE_HORAS_B):
        m = rx.search(texto or "")
        if m:
            try:
                h = int(m.group(1))
                if 0 < h <= 5000:
                    return h
            except Exception:
                pass
    return None


def _extraer_anyo(texto: str):
    mejor = None
    for m in _RE_ANYO.finditer(texto or ""):
        y = int(m.group(1))
        if 1985 <= y <= 2026:
            mejor = y if mejor is None else max(mejor, y)
    return mejor


def _norm_wallapop_moto(raw: dict, source: str) -> dict | None:
    """Normaliza un anuncio de moto de agua (actor fayoussef/wallapop-scraper)."""
    title = (raw.get("title") or raw.get("name") or raw.get("titulo") or "").strip()
    price = (raw.get("price") or raw.get("precio") or raw.get("salePrice")
             or raw.get("sale_price") or raw.get("cash"))
    if isinstance(price, dict):
        price = price.get("amount") or price.get("cash")
    if not title and price is None:
        return None

    url = (raw.get("url") or raw.get("link") or raw.get("itemUrl")
           or raw.get("web_slug") or "")
    if url and not str(url).startswith("http"):
        url = f"https://es.wallapop.com/item/{url}"
    item_id = (raw.get("id") or raw.get("itemId") or raw.get("adId")
               or url or title[:25])

    desc = raw.get("description") or raw.get("descripcion") or ""
    texto = f"{title} {desc}"

    marca, modelo = _marca_modelo_moto(texto)
    horas = _extraer_horas(texto)
    anyo = num(raw.get("year")) or _extraer_anyo(texto)

    loc = raw.get("location") or {}
    city, lat, lng = "", None, None
    if isinstance(loc, dict):
        city = loc.get("city") or loc.get("name") or ""
        lat = loc.get("latitude") or loc.get("lat")
        lng = loc.get("longitude") or loc.get("lng") or loc.get("lon")
    else:
        city = str(loc)
    if lat is None:
        lat = raw.get("latitude") or raw.get("lat")
    if lng is None:
        lng = raw.get("longitude") or raw.get("lng")
    if not city:
        city = raw.get("city") or raw.get("province") or raw.get("region") or ""

    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    seller = (raw.get("seller_type") or raw.get("sellerType")
              or user.get("type") or "")

    return {
        "id": f"{source.lower()}_{item_id}",
        "source": source,
        "title": title,
        "description": desc,
        "price": num(price),
        "year": anyo,
        "horas": horas,
        "km": num(raw.get("km") or raw.get("kms")),
        "make": marca,
        "model": (modelo.title() if modelo else None),
        "city": city,
        "lat": (float(lat) if _isnum(lat) else None),
        "lng": (float(lng) if _isnum(lng) else None),
        "url": url or "https://es.wallapop.com",
        "seller_type": str(seller).lower(),
        "motorbike_style": (raw.get("motorbike_style")
                            or raw.get("motorbikeStyle") or ""),
        "version": "",
        "perfil": "moto",
    }


def buscar_apify(cfg_busqueda: dict, cfg_apify: dict) -> list[dict]:
    """
    Llama a cada actor de Apify configurado y devuelve los anuncios normalizados.
    cfg_apify = {
      "token": "apify_api_xxx",
      "actores": [
        {"source":"Wallapop", "actor":"autoclient~wallapop-spain-scraper",
         "input": { ... lo que pida el actor ... }}
      ]
    }
    """
    token = cfg_apify.get("token")
    if not token:
        print("  !! Falta el token de Apify en config.json")
        return []

    todos = []
    for a in cfg_apify.get("actores", []):
        source = a.get("source", "Apify")
        actor = a.get("actor")
        if not actor:
            continue
        # Normalizador: motos de agua sacan datos del texto; coches van estándar
        normaliza = (_norm_wallapop_moto
                     if a.get("formato") == "wallapop_moto" else _norm_item)
        # Construimos el input: lo que traiga el config + los filtros de precio/km
        # Quitamos las claves de notas (empiezan por "_") para no mandarlas al actor
        entrada = {k: v for k, v in a.get("input", {}).items()
                   if not str(k).startswith("_")}
        # Muchos actores aceptan una searchUrl; si está en el config la respetamos
        kw = entrada.get("keywords", "")
        etiqueta = a.get("modelo") or kw or source
        print(f"  -> buscando: {etiqueta}...")
        url = (f"https://api.apify.com/v2/acts/{actor}"
               f"/run-sync-get-dataset-items?token={token}")
        try:
            r = requests.post(url, json=entrada, timeout=300)
            if r.status_code not in (200, 201):
                print(f"  !! {source}: Apify devolvió {r.status_code} {r.text[:200]}")
                continue
            datos = r.json()
            if not isinstance(datos, list):
                datos = datos.get("items", []) if isinstance(datos, dict) else []
            print(f"  -> {etiqueta}: {len(datos)} encontrados")
            for raw in datos:
                it = normaliza(raw, source)
                if it:
                    todos.append(it)
        except Exception as e:
            print(f"  !! {source}: error llamando a Apify: {e}")

    return _dedupe(todos)


if __name__ == "__main__":
    # prueba sin red: normalización
    ejemplo = {"title": "Volkswagen Golf 1.6 TDI", "price": 7200, "year": 2014,
               "km": 125000, "fuel": "diesel", "url": "abc123",
               "location": {"city": "Sabadell"}}
    print(_norm_item(ejemplo, "Wallapop"))
