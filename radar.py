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


def cargar_cfg(path=CONFIG):
    path = Path(path)
    if not path.exists():
        log(f"Falta {path.name}. Copia el ejemplo y edítalo.")
        sys.exit(1)
    cfg = json.load(open(path, encoding="utf-8"))
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


# ---------------- memoria de precios (historial del mercado) ----------------
MERCADO = BASE / "mercado.json"
HISTORIAL_DIAS = 30


def cargar_mercado():
    if MERCADO.exists():
        try:
            return json.load(open(MERCADO, encoding="utf-8"))
        except Exception:
            return []
    return []


def guardar_mercado(m):
    json.dump(m, open(MERCADO, "w", encoding="utf-8"), ensure_ascii=False)


def actualizar_mercado(mercado, coches):
    """Mete los coches de hoy en el historial y poda los de hace más de 30 días."""
    from datetime import date, timedelta
    hoy = date.today().isoformat()
    por_id = {m["id"]: m for m in mercado}
    for c in coches:
        if not c.get("price"):
            continue
        por_id[c["id"]] = {
            "id": c["id"], "make": c.get("make"), "model": c.get("model"),
            "year": c.get("year"), "km": c.get("km"), "horas": c.get("horas"),
            "price": c.get("price"), "fecha": hoy,
        }
    limite = (date.today() - timedelta(days=HISTORIAL_DIAS)).isoformat()
    return [m for m in por_id.values() if m.get("fecha", hoy) >= limite]


# ---------------- notificaciones ----------------
def _etiqueta_coche(coche):
    """Cabecera que canta la oportunidad según lo barato que esté."""
    d = coche.get("dif_pct")
    if d is None:
        return "🚗 NUEVO"
    if d <= -20:
        return f"🔥🔥 GANGA URGENTE -{abs(d)}%"
    if d <= -12:
        return f"🔥 CHOLLO -{abs(d)}%"
    if d < 0:
        return f"✅ buen precio -{abs(d)}%"
    return "🚗 NUEVO"


def notif_whatsapp(coche, cfg):
    if not cfg.get("enabled"):
        return
    desc = (f"-{abs(coche['dif_pct'])}% bajo mercado"
            if coche.get("dif_pct") is not None else "sin valoración fiable")
    txt = (f"{_etiqueta_coche(coche)} · {coche['source']}\n{coche['title']}\n"
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
    txt = (f"<b>{_etiqueta_coche(coche)}</b> · {coche['source']}\n{coche['title']}\n"
           f"💶 <b>{coche['price']} €</b> ({desc})\n"
           f"Medio: {coche.get('precio_medio','?')} € · "
           f"{coche.get('year','?')} · {coche.get('km','?')} km\n{coche['url']}")
    try:
        requests.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                      data={"chat_id": cfg["chat_id"], "text": txt,
                            "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        log(f"  !! Telegram: {e}")


# ---------- notificaciones MOTOS DE AGUA (horas, % vs mercado, etiqueta) ----------
def _etiqueta_moto(item, margen):
    if item.get("sospechoso"):
        return "⚠️ SOSPECHOSO (¿timo/error?)"
    if item.get("dif_pct") is not None and item["dif_pct"] <= -abs(margen):
        return "🔥 GANGA"
    return "👀 nuevo"


def _desc_moto(item):
    if item.get("dif_pct") is not None:
        return f"-{abs(item['dif_pct'])}% vs mercado"
    return "sin valoración fiable (pocos comparables)"


def notif_whatsapp_moto(item, cfg, margen=10):
    if not cfg.get("enabled"):
        return
    horas = f"{item['horas']} h" if item.get("horas") else "h ?"
    txt = (f"🛥️ {_etiqueta_moto(item, margen)} · {item['source']}\n"
           f"{item['title']}\n"
           f"💶 {item['price']} € ({_desc_moto(item)})\n"
           f"Medio: {item.get('precio_medio','?')} € · "
           f"{item.get('year','?')} · {horas}\n{item['url']}")
    try:
        requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": cfg["phone"], "text": txt, "apikey": cfg["apikey"]},
                     timeout=20)
    except Exception as e:
        log(f"  !! WhatsApp: {e}")
    time.sleep(3)


def notif_telegram_moto(item, cfg, margen=10):
    if not cfg.get("enabled"):
        return
    horas = f"{item['horas']} h" if item.get("horas") else "h ?"
    txt = (f"🛥️ <b>{_etiqueta_moto(item, margen)}</b> · {item['source']}\n"
           f"{item['title']}\n"
           f"💶 <b>{item['price']} €</b> ({_desc_moto(item)})\n"
           f"Medio: {item.get('precio_medio','?')} € · "
           f"{item.get('year','?')} · {horas}\n{item['url']}")
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


def escribir_csv_moto(items, path):
    nuevo = not Path(path).exists()
    with open(path, "a", encoding="utf-8") as f:
        if nuevo:
            f.write("fecha;portal;titulo;precio;precio_medio;dif_%;fiable;"
                    "sospechoso;anio;horas;ciudad;url\n")
        for c in items:
            f.write(";".join([
                f"{datetime.now():%Y-%m-%d %H:%M}", c["source"],
                (c["title"] or "").replace(";", ","),
                str(c.get("price") or ""), str(c.get("precio_medio") or ""),
                str(c.get("dif_pct") if c.get("dif_pct") is not None else ""),
                "si" if c.get("fiable") else "no",
                "si" if c.get("sospechoso") else "no",
                str(c.get("year") or ""), str(c.get("horas") or ""),
                (c.get("city") or ""), c["url"],
            ]) + "\n")


# ---------------- pasada completa ----------------
def pasada(cfg, headful):
    vistos = cargar_vistos()
    n = cfg["notificaciones"]
    perfil = cfg.get("perfil", "coches")
    es_moto = (perfil == "motos")
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

    # 1) filtros duros — según el perfil (coches o motos de agua)
    candidatos = []
    descartes = {}
    for c in universo:
        if es_moto:
            ok, motivo = filtros.pasa_filtros_moto(c, cfg["busqueda"])
        else:
            ok, motivo = filtros.pasa_filtros_duros(c, cfg["busqueda"])
        if ok:
            candidatos.append(c)
        else:
            descartes[motivo] = descartes.get(motivo, 0) + 1
    log(f"Pasan filtros: {len(candidatos)}")
    if descartes:
        resumen = ", ".join(f"{m} ({v})" for m, v in
                            sorted(descartes.items(), key=lambda x: -x[1]))
        log(f"Descartados {sum(descartes.values())} -> {resumen}")

    # 1b) actualizar la MEMORIA DE PRECIOS con los coches de hoy
    mercado = cargar_mercado()
    mercado = actualizar_mercado(mercado, candidatos)
    guardar_mercado(mercado)
    log(f"Memoria de precios: {len(mercado)} anuncios acumulados "
        f"(últimos {HISTORIAL_DIAS} días)")

    # 2) valorar cada coche contra TODO el historial (no solo lo de hoy) y quedarnos con chollos
    chollos = []
    margen = cfg["busqueda"].get("margen_chollo_pct", 0)  # 0 = todo lo <= medio
    sosp = cfg["busqueda"].get("sospechoso_pct", 60)
    for c in candidatos:
        if es_moto:
            valoracion.valorar_moto(c, mercado, sosp)
        else:
            valoracion.valorar(c, mercado)
        if c["id"] in vistos:
            continue
        if c.get("dif_pct") is None:
            # sin comparables suficientes todavía: solo si se pide
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
            if es_moto:
                escribir_csv_moto(chollos, BASE / n["csv"].get("path", "chollos_motos.csv"))
            else:
                escribir_csv(chollos, BASE / n["csv"].get("path", "chollos.csv"))
        for c in chollos:
            if es_moto:
                notif_whatsapp_moto(c, n.get("whatsapp", {}), margen)
                notif_telegram_moto(c, n.get("telegram", {}), margen)
            else:
                notif_whatsapp(c, n.get("whatsapp", {}))
                notif_telegram(c, n.get("telegram", {}))
    log("Pasada terminada.\n")


def main():
    global VISTOS, MERCADO
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--config", default=str(CONFIG),
                    help="ruta al config (por defecto config.json = coches)")
    a = ap.parse_args()
    cfg = cargar_cfg(a.config)
    perfil = cfg.get("perfil", "coches")
    # Memoria separada por perfil para que coches y motos no se pisen.
    if perfil != "coches":
        VISTOS = BASE / f"vistos_{perfil}.json"
        MERCADO = BASE / f"mercado_{perfil}.json"
    log(f"=== Radar [{perfil}] arrancado ===")
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
