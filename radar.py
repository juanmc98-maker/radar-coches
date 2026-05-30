#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
radar.py — orquestador. Ejecuta:
  1) busca en los portales activos
  2) aplica filtros duros (precio, km, etiqueta, negativos)
  3) valora cada coche vs comparables (precio medio de mercado)
  4) descarta los que estén POR ENCIMA del mercado
  5) ordena por mayor descuento y notifica (CSV + WhatsApp/Telegram opcional)

Uso:
  python radar.py --once       una pasada (recomendado para empezar)
  python radar.py              bucle continuo cada poll_interval_minutes
  python radar.py --headful    muestra el navegador (necesario si hay captcha)
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

import filtros
import portales
import apify_portales
import valoracion

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.json"
PROFILE = BASE / "navegador_perfil"
VISTOS = BASE / "vistos.json"


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def cargar_cfg():
    if not CONFIG.exists():
        log("Falta config.json. Copia config.example.json y edítalo.")
        sys.exit(1)
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    # Secretos en archivo aparte: NO se sube a GitHub y sobrevive a 'git pull',
    # asi las actualizaciones no borran el token ni el WhatsApp.
    secrets = BASE / "secrets.json"
    if secrets.exists():
        try:
            sec = json.load(open(secrets, encoding="utf-8"))
            if sec.get("apify_token"):
                cfg.setdefault("apify", {})["token"] = sec["apify_token"]
            if sec.get("wa_phone"):
                wa = cfg.setdefault("notificaciones", {}).setdefault("whatsapp", {})
                wa["phone"] = sec["wa_phone"]
                wa["apikey"] = sec.get("wa_key", wa.get("apikey", ""))
                wa["enabled"] = True
        except Exception as e:
            log(f"  !! No pude leer secrets.json: {e}")
    return cfg


def cargar_vistos():
    if VISTOS.exists():
        try:
            return set(json.load(open(VISTOS, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def guardar_vistos(s):
    json.dump(sorted(s), open(VISTOS, "w", encoding="utf-8"))


# ---------------- notificaciones ----------------
def notif_whatsapp(coche, cfg):
    if not cfg.get("enabled"):
        return
    desc = (f"-{abs(coche['dif_pct'])}% bajo mercado"
            if coche.get("dif_pct") is not None else "sin valoración fiable")
    txt = (f"🚗 CHOLLO {coche['source']}\n{coche['title']}\n"
           f"💶 {coche['price']} € ({desc})\n"
           f"Medio: {coche.get('precio_medio','?')} € · "
           f"{coche.get('year','?')} · {coche.get('km','?')} km\n{coche['url']}")
    try:
        requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": cfg["phone"], "text": txt, "apikey": cfg["apikey"]},
                     timeout=20)
    except Exception as e:
        log(f"  !! WhatsApp: {e}")
    time.sleep(3)


def notif_telegram(coche, cfg):
    if not cfg.get("enabled"):
        return
    desc = (f"-{abs(coche['dif_pct'])}% bajo mercado"
            if coche.get("dif_pct") is not None else "sin valoración fiable")
    txt = (f"🚗 <b>{coche['source']}</b>\n{coche['title']}\n"
           f"💶 <b>{coche['price']} €</b> ({desc})\n"
           f"Medio: {coche.get('precio_medio','?')} € · "
           f"{coche.get('year','?')} · {coche.get('km','?')} km\n{coche['url']}")
    try:
        requests.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                      data={"chat_id": cfg["chat_id"], "text": txt,
                            "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        log(f"  !! Telegram: {e}")


def escribir_csv(coches, path):
    nuevo = not Path(path).exists()
    with open(path, "a", encoding="utf-8") as f:
        if nuevo:
            f.write("fecha;portal;titulo;precio;precio_medio;dif_%;fiable;"
                    "anio;km;combustible;ciudad;url\n")
        for c in coches:
            f.write(";".join([
                f"{datetime.now():%Y-%m-%d %H:%M}", c["source"],
                (c["title"] or "").replace(";", ","),
                str(c.get("price") or ""), str(c.get("precio_medio") or ""),
                str(c.get("dif_pct") if c.get("dif_pct") is not None else ""),
                "si" if c.get("fiable") else "no",
                str(c.get("year") or ""), str(c.get("km") or ""),
                (c.get("fuel") or ""), (c.get("city") or ""), c["url"],
            ]) + "\n")


# ---------------- pasada completa ----------------
def pasada(cfg, headful):
    vistos = cargar_vistos()
    n = cfg["notificaciones"]
    activos = [p for p, on in cfg["portales_activos"].items()
               if on and not str(p).startswith("_")]
    log(f"Portales activos: {', '.join(activos)}")

    crudos = []
    # --- MODO APIFY (recomendado en servidor): si hay apify activado, lo usamos ---
    apify_cfg = cfg.get("apify", {})
    if apify_cfg.get("enabled"):
        log("Buscando vía Apify...")
        try:
            crudos += apify_portales.buscar_apify(cfg["busqueda"], apify_cfg)
        except Exception as e:
            log(f"  !! Apify falló: {e}")
    else:
        # --- MODO NAVEGADOR (Playwright): solo funciona donde no haya bloqueo ---
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE), headless=not headful,
                locale="es-ES", timezone_id="Europe/Madrid",
                viewport={"width": 1366, "height": 900},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"))
            for portal in activos:
                log(f"Buscando en {portal}...")
                try:
                    res = portales.ADAPTADORES[portal](ctx, cfg["busqueda"])
                    log(f"  -> {len(res)} anuncios recibidos")
                    crudos += res
                except Exception as e:
                    log(f"  !! {portal} falló: {e}")
                time.sleep(4)
            ctx.close()

    # universo para valorar = TODO lo recogido (también lo ya visto sirve de comp)
    universo = portales._dedupe(crudos)
    log(f"Total bruto (deduplicado): {len(universo)}")

    # 1) filtros duros
    candidatos = []
    for c in universo:
        ok, motivo = filtros.pasa_filtros_duros(c, cfg["busqueda"])
        if ok:
            candidatos.append(c)
    log(f"Pasan filtros (precio/km/etiqueta/negativos): {len(candidatos)}")

    # 2) valorar contra el universo y quedarnos con chollos
    chollos = []
    margen = cfg["busqueda"].get("margen_chollo_pct", 0)  # 0 = todo lo <= medio
    for c in candidatos:
        valoracion.valorar(c, universo)
        if c["id"] in vistos:
            continue
        if c.get("dif_pct") is None:
            # sin comps fiables: lo guardamos solo si se pide
            if cfg["busqueda"].get("incluir_sin_valoracion", True):
                chollos.append(c)
        elif c["dif_pct"] <= -margen:   # por debajo del mercado
            chollos.append(c)
        # si está por encima -> descartado (no se añade)

    # marcar todos los candidatos como vistos (para no repetir avisos)
    for c in candidatos:
        vistos.add(c["id"])
    guardar_vistos(vistos)

    # 3) ordenar: mayor descuento primero (None al final)
    chollos.sort(key=lambda c: (c.get("dif_pct") is None, c.get("dif_pct") or 0))

    log(f"CHOLLOS NUEVOS: {len(chollos)}")
    for c in chollos:
        d = f"{c['dif_pct']}%" if c.get("dif_pct") is not None else "s/val"
        log(f"   [{c['source']}] {c['title'][:45]} | {c.get('price')}€ "
            f"(medio {c.get('precio_medio')}€, {d}) {c['url']}")

    # 4) notificar
    if chollos:
        if n.get("csv", {}).get("enabled", True):
            escribir_csv(chollos, BASE / n["csv"].get("path", "chollos.csv"))
        for c in chollos:
            notif_whatsapp(c, n.get("whatsapp", {}))
            notif_telegram(c, n.get("telegram", {}))
    log("Pasada terminada.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--headful", action="store_true")
    a = ap.parse_args()
    cfg = cargar_cfg()
    log("=== Radar de coches arrancado ===")
    if a.once:
        pasada(cfg, a.headful)
        return
    while True:
        try:
            pasada(cfg, a.headful)
        except KeyboardInterrupt:
            log("Parado."); break
        except Exception as e:
            log(f"ERROR: {e}")
        mins = cfg.get("poll_interval_minutes", 30)
        log(f"Durmiendo {mins} min...")
        time.sleep(mins * 60)


if __name__ == "__main__":
    main()
