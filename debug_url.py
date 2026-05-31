#!/usr/bin/env python3
"""Diagnóstico: lista los anuncios que devuelve Apify y el veredicto del filtro.
No toca el bot. Uso:  /opt/radar/venv/bin/python debug_url.py
"""
import json, requests, pathlib
import apify_portales as A
import filtros as F

BASE = pathlib.Path(__file__).resolve().parent
cfg = json.loads((BASE / "config_motos.json").read_text(encoding="utf-8"))
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
busq = cfg["busqueda"]

url = (f"https://api.apify.com/v2/acts/{actor['actor']}"
       f"/run-sync-get-dataset-items?token={token}")
print("Llamando a Apify (puede tardar 30-60s)...")
r = requests.post(url, json=entrada, timeout=300)
print("HTTP", r.status_code)
datos = r.json()
if isinstance(datos, dict):
    datos = datos.get("items", [])
print(f"Recibidos {len(datos)} anuncios.\n")

for i, raw in enumerate(datos):
    it = A._norm_wallapop_moto(raw, "Wallapop")
    if not it:
        print(f"{i+1:2}. (no normalizable)")
        continue
    es_agua = F.es_moto_agua(it)
    ok, mot = F.pasa_filtros_moto(it, busq)
    veredicto = "PASA" if ok else f"fuera: {mot}"
    print(f"{i+1:2}. [{'ACUA' if es_agua else 'no  '}] {str(it['title'])[:50]:52} "
          f"{str(it.get('price'))+'€':>8}  -> {veredicto}")
