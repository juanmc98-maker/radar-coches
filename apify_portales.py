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
        # Construimos el input: lo que traiga el config + los filtros de precio/km
        # Quitamos las claves de notas (empiezan por "_") para no mandarlas al actor
        entrada = {k: v for k, v in a.get("input", {}).items()
                   if not str(k).startswith("_")}
        # Muchos actores aceptan una searchUrl; si está en el config la respetamos
        print(f"  -> llamando a Apify ({source})...")
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
            print(f"  -> {source}: {len(datos)} resultados de Apify")
            for raw in datos:
                it = _norm_item(raw, source)
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
