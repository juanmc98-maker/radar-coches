#!/usr/bin/env python3
"""Diagnóstico: enseña cómo viene el ENLACE de cada anuncio de moto en Apify.
No toca el bot. Uso:  /opt/radar/venv/bin/python debug_url.py
"""
import json, requests, pathlib

BASE = pathlib.Path(__file__).resolve().parent
cfg = json.loads((BASE / "config_motos.json").read_text(encoding="utf-8"))

# Mismo truco que el bot: el token real está en secrets.json
try:
    sec = json.loads((BASE / "secrets.json").read_text(encoding="utf-8"))
    if sec.get("apify_token"):
        cfg["apify"]["token"] = sec["apify_token"]
except Exception as e:
    print("(aviso) no pude leer secrets.json:", e)

token = cfg["apify"]["token"]
actor = cfg["apify"]["actores"][0]
entrada = {k: v for k, v in actor.get("input", {}).items()
           if not str(k).startswith("_")}

url = (f"https://api.apify.com/v2/acts/{actor['actor']}"
       f"/run-sync-get-dataset-items?token={token}")
print("Llamando a Apify (puede tardar 30-60s)...")
r = requests.post(url, json=entrada, timeout=300)
print("HTTP", r.status_code)
datos = r.json()
if isinstance(datos, dict):
    datos = datos.get("items", [])

print(f"Recibidos {len(datos)} anuncios.\n")

# Para los 3 primeros: enseñamos TODAS las claves y cualquier valor que
# huela a enlace / id / slug.
PISTAS = ("url", "slug", "link", "id", "web", "share", "permalink", "href")
for i, raw in enumerate(datos[:3]):
    print(f"===== ANUNCIO {i+1} =====")
    print("Título:", str(raw.get("title") or raw.get("name"))[:60])
    print("CLAVES disponibles:", list(raw.keys()))
    for k, v in raw.items():
        if any(p in k.lower() for p in PISTAS):
            sv = str(v)
            print(f"   · {k} = {sv[:120]}")
    print()
