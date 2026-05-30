#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portales.py — un adaptador por portal. Cada uno devuelve una lista de coches
NORMALIZADOS con los mismos campos:
  id, source, title, description, price, year, km, fuel, make, model, city, url

Wallapop: robusto (interceptamos su API interna).
Coches.net y Milanuncios: "best effort" — tienen anti-bot fuerte; pueden
fallar o pedir captcha. Si pasa, ver README (plan B con Apify).
"""

import re
import urllib.parse

# Marcas comunes para extraer marca/modelo del título cuando no viene estructurado
MARCAS = [
    "audi", "bmw", "citroen", "citroën", "dacia", "fiat", "ford", "honda",
    "hyundai", "kia", "lancia", "land rover", "lexus", "mazda", "mercedes",
    "mercedes-benz", "mini", "mitsubishi", "nissan", "opel", "peugeot",
    "renault", "seat", "skoda", "smart", "subaru", "suzuki", "toyota",
    "volkswagen", "vw", "volvo", "alfa romeo", "jeep", "chevrolet", "saab",
]
NORM_MARCA = {"vw": "volkswagen", "citroën": "citroen", "mercedes": "mercedes-benz"}


def extraer_marca_modelo(titulo: str) -> tuple[str | None, str | None]:
    t = (titulo or "").lower()
    for marca in sorted(MARCAS, key=len, reverse=True):
        if marca in t:
            canon = NORM_MARCA.get(marca, marca)
            resto = t.split(marca, 1)[1].strip()
            modelo = re.split(r"[\s,.-]+", resto)[0] if resto else None
            return canon.title(), (modelo.title() if modelo else None)
    return None, None


def num(texto) -> int | None:
    if texto is None:
        return None
    s = re.sub(r"[^\d]", "", str(texto))
    return int(s) if s else None


# ---------------------------------------------------------------------------
# WALLAPOP  (interceptando api.wallapop.com)
# ---------------------------------------------------------------------------
def buscar_wallapop(context, cfg: dict) -> list[dict]:
    params = {
        "category_ids": 100,
        "min_sale_price": cfg["precio_min"],
        "max_sale_price": cfg["precio_max"],
        "latitude": cfg["lat"], "longitude": cfg["lng"],
        "distance": int(cfg["radio_km"]) * 1000,
        "order_by": "newest",
        "max_km": cfg["km_max"],
    }
    url = "https://es.wallapop.com/search?" + urllib.parse.urlencode(params)
    capturados, page = [], context.new_page()

    def on_response(resp):
        try:
            if "api.wallapop.com" in resp.url and "search" in resp.url and resp.status == 200:
                data = resp.json()
                objs = (data.get("search_objects") or data.get("searchObjects")
                        or data.get("items") or [])
                for o in objs if isinstance(objs, list) else []:
                    core = o.get("content", o) if isinstance(o, dict) else o
                    item_id = core.get("id")
                    if not item_id:
                        continue
                    price = core.get("price")
                    if isinstance(price, dict):
                        price = price.get("amount") or price.get("cash")
                    attrs = core.get("attributes") or {}
                    slug = core.get("web_slug") or core.get("slug") or str(item_id)
                    title = core.get("title", "")
                    marca, modelo = extraer_marca_modelo(title)
                    loc = core.get("location") or {}
                    capturados.append({
                        "id": f"wallapop_{item_id}",
                        "source": "Wallapop",
                        "title": title,
                        "description": core.get("description", ""),
                        "price": num(price),
                        "year": num(core.get("year") or attrs.get("year")),
                        "km": num(core.get("km") or attrs.get("km")),
                        "fuel": (core.get("engine") or attrs.get("engine") or "").lower(),
                        "make": marca, "model": modelo,
                        "city": loc.get("city") or "",
                        "url": f"https://es.wallapop.com/item/{slug}",
                    })
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        _aceptar_cookies(page)
        page.wait_for_timeout(3500)
        for _ in range(3):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1800)
    except Exception as e:
        print(f"  !! Wallapop: {e}")
    finally:
        page.close()
    return _dedupe(capturados)


# ---------------------------------------------------------------------------
# COCHES.NET  (best effort — parseo del HTML/JSON embebido)
# ---------------------------------------------------------------------------
def buscar_cochesnet(context, cfg: dict) -> list[dict]:
    # Filtros básicos por URL; el radio/etiqueta se afinan luego en local
    url = (f"https://www.coches.net/segunda-mano/?"
           f"pr={cfg['precio_min']}_{cfg['precio_max']}"
           f"&km=0_{cfg['km_max']}&from=0&MakeIds=&pg=1&or=4")
    capturados, page = [], context.new_page()
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        _aceptar_cookies(page)
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 6000)
        page.wait_for_timeout(2500)
        # coches.net inserta datos en window.__INITIAL_PROPS__ / JSON-LD
        data = page.evaluate(
            """() => {
                try {
                  const scripts = [...document.querySelectorAll('script')];
                  for (const s of scripts) {
                    if (s.textContent.includes('"items"') && s.textContent.includes('price')) {
                      return s.textContent;
                    }
                  }
                } catch(e) {}
                return null;
            }"""
        )
        if data:
            capturados = _parsear_json_generico(data, "Coches.net",
                                                "https://www.coches.net")
    except Exception as e:
        print(f"  !! Coches.net: {e}")
    finally:
        page.close()
    return _dedupe(capturados)


# ---------------------------------------------------------------------------
# MILANUNCIOS  (best effort)
# ---------------------------------------------------------------------------
def buscar_milanuncios(context, cfg: dict) -> list[dict]:
    url = (f"https://www.milanuncios.com/coches-de-segunda-mano/?"
           f"desde={cfg['precio_min']}&hasta={cfg['precio_max']}"
           f"&kmhasta={cfg['km_max']}&orden=date")
    capturados, page = [], context.new_page()
    try:
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        _aceptar_cookies(page)
        page.wait_for_timeout(4000)
        page.mouse.wheel(0, 6000)
        page.wait_for_timeout(2500)
        data = page.evaluate(
            """() => {
                const el = document.querySelector('#__NEXT_DATA__');
                return el ? el.textContent : null;
            }"""
        )
        if data:
            capturados = _parsear_json_generico(data, "Milanuncios",
                                                "https://www.milanuncios.com")
    except Exception as e:
        print(f"  !! Milanuncios: {e}")
    finally:
        page.close()
    return _dedupe(capturados)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _aceptar_cookies(page):
    for sel in ['button:has-text("Aceptar")', '#onetrust-accept-btn-handler',
                'button:has-text("Acepto")', 'button:has-text("Accept")',
                'button[mode="primary"]']:
        try:
            b = page.locator(sel).first
            if b.is_visible(timeout=2500):
                b.click()
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def _parsear_json_generico(raw: str, source: str, base_url: str) -> list[dict]:
    """Busca recursivamente objetos que parezcan anuncios de coche."""
    import json
    out = []
    try:
        data = json.loads(raw)
    except Exception:
        return out

    def walk(node):
        if isinstance(node, dict):
            # heurística: tiene precio y (título o marca)
            if ("price" in node or "cash" in node) and \
               ("title" in node or "make" in node or "name" in node):
                title = node.get("title") or node.get("name") or ""
                price = node.get("price") or node.get("cash")
                if isinstance(price, dict):
                    price = price.get("amount") or price.get("cash")
                marca = node.get("make") or node.get("brand")
                modelo = node.get("model")
                if not marca:
                    marca, modelo = extraer_marca_modelo(title)
                _id = node.get("id") or node.get("adId") or title[:20]
                slug = node.get("url") or node.get("slug") or ""
                url = slug if str(slug).startswith("http") else f"{base_url}{slug}"
                if title or price:
                    out.append({
                        "id": f"{source.lower()}_{_id}",
                        "source": source,
                        "title": title,
                        "description": node.get("description", ""),
                        "price": num(price),
                        "year": num(node.get("year")),
                        "km": num(node.get("km") or node.get("kms") or node.get("mileage")),
                        "fuel": (node.get("fuel") or node.get("fuelType") or "").lower(),
                        "make": (str(marca).title() if marca else None),
                        "model": (str(modelo).title() if modelo else None),
                        "city": node.get("province") or node.get("city") or "",
                        "url": url,
                    })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    vistos, out = set(), []
    for it in items:
        if it["id"] not in vistos:
            vistos.add(it["id"])
            out.append(it)
    return out


ADAPTADORES = {
    "wallapop": buscar_wallapop,
    "cochesnet": buscar_cochesnet,
    "milanuncios": buscar_milanuncios,
}

if __name__ == "__main__":
    # prueba offline de extracción marca/modelo
    for t in ["Volkswagen Golf 1.6 TDI", "SEAT Ibiza 2014", "vw passat variant"]:
        print(t, "->", extraer_marca_modelo(t))
