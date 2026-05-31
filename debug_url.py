#!/usr/bin/env python3
"""Diagnóstico: lista los anuncios de Apify con el veredicto del filtro.
No toca el bot. Funciona con cualquier perfil:
   /opt/radar/venv/bin/python debug_url.py config_campers.json
   /opt/radar/venv/bin/python debug_url.py config_motos.json   (por defecto)
"""
import json, sys, requests, pathlib
import apify_portales as A
import filtros as F

BASE = pathlib.Path(__file__).resolve().parent
cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config_motos.json"
cfg = json.loads((BASE / cfg_path).read_text(encoding="utf-8"))
try:
    sec = json.loads((BASE / "secrets.json").read_text(encoding="utf-8"))
    if sec.get("apify_token"):
        cfg["apify"]["token"] = sec["apify_token"]
except Exception as e:
    print("(aviso) no pude leer secrets.json:", e)

perfil = cfg.get("perfil", "coches")
if perfil == "motos":
    normaliza, filtro = A._norm_wallapop_moto, F.pasa_filtros_moto
elif perfil == "campers":
    normaliza, filtro = A._norm_wallapop_camper, F.pasa_filtros_camper
else:
    normaliza, filtro = A._norm_item, F.pasa_filtros_duros

token = cfg["apify"]["token"]
actor = cfg["apify"]["actores"][0]
entrada = {k: v for k, v in actor.get("input", {}).items()
           if not str(k).startswith("_")}
busq = cfg["busqueda"]

url = (f"https://api.apify.com/v2/acts/{actor['actor']}"
       f"/run-sync-get-dataset-items?token={token}")
print(f"Perfil: {perfil}. Llamando a Apify (puede tardar 30-60s)...")
r = requests.post(url, json=entrada, timeout=300)
print("HTTP", r.status_code)
datos = r.json()
if isinstance(datos, dict):
    datos = datos.get("items", [])
print(f"Recibidos {len(datos)} anuncios.\n")

for i, raw in enumerate(datos):
    it = normaliza(raw, "Wallapop")
    if not it:
        print(f"{i+1:2}. (no normalizable)")
        continue
    ok, mot = filtro(it, busq)
    print(f"{i+1:2}. {str(it['title'])[:54]:56} {str(it.get('price'))+'EUR':>9}  -> "
          f"{'PASA' if ok else 'fuera: '+mot}")
