#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valoracion.py — calcula el precio de mercado de cada coche comparándolo
con el resto de anuncios equivalentes recogidos en la misma pasada.

Idea: no usamos ninguna tasación externa (no hay API fiable gratis).
Hacemos lo que hace un profesional: agrupamos por marca+modelo, año parecido
y km parecidos, y sacamos la MEDIANA de precios de los comparables.
Luego decimos cuánto está cada coche por debajo (o por encima) de esa mediana.
"""

import statistics
import unicodedata
from difflib import SequenceMatcher


def _n(s: str) -> str:
    """minúsculas y sin acentos (Citroën == Citroen, León == Leon)."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()

# Margen de comparación
YEAR_TOLERANCE = 1          # años arriba/abajo que consideramos "el mismo"
KM_TOLERANCE = 50000        # km arriba/abajo que consideramos "parecido"
MIN_COMPS = 2               # nº mínimo de comparables para fiarnos de la mediana
# (2 permite valorar modelos con pocos anuncios, como Mini R53 o Scirocco;
#  aun así exige estar por debajo del margen para avisar)


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def son_comparables(coche: dict, otro: dict) -> bool:
    """¿'otro' sirve como comparable de 'coche'?"""
    if coche["id"] == otro["id"]:
        return False
    # Marca debe coincidir (sin acentos ni mayúsculas)
    if not coche.get("make") or not otro.get("make"):
        return False
    if _n(coche["make"]) != _n(otro["make"]):
        return False
    # Modelo: igual o muy parecido (Golf vs Golf Plus se aceptan)
    m1, m2 = _n(coche.get("model") or ""), _n(otro.get("model") or "")
    if m1 and m2 and _similar(m1, m2) < 0.6:
        return False
    # Año dentro de tolerancia
    if coche.get("year") and otro.get("year"):
        if abs(int(coche["year"]) - int(otro["year"])) > YEAR_TOLERANCE:
            return False
    # Km dentro de tolerancia
    if coche.get("km") and otro.get("km"):
        if abs(int(coche["km"]) - int(otro["km"])) > KM_TOLERANCE:
            return False
    return True


def valorar(coche: dict, universo: list[dict]) -> dict:
    """
    Devuelve el coche con campos añadidos:
      precio_medio, n_comparables, dif_pct (negativo = chollo), fiable (bool)
    """
    comps = [o for o in universo if son_comparables(coche, o) and o.get("price")]
    precios = [o["price"] for o in comps]

    if len(precios) < MIN_COMPS or not coche.get("price"):
        coche["precio_medio"] = statistics.median(precios) if precios else None
        coche["n_comparables"] = len(precios)
        coche["dif_pct"] = None
        coche["fiable"] = False
        return coche

    mediana = statistics.median(precios)
    dif_pct = round((coche["price"] - mediana) / mediana * 100, 1)
    coche["precio_medio"] = round(mediana)
    coche["n_comparables"] = len(precios)
    coche["dif_pct"] = dif_pct          # ej. -18.0 => 18% por debajo del mercado
    coche["fiable"] = True
    return coche


# --- prueba rápida con datos sintéticos (no toca internet) -------------------
if __name__ == "__main__":
    universo = [
        {"id": "1", "make": "Volkswagen", "model": "Golf", "year": 2014, "km": 120000, "price": 9500},
        {"id": "2", "make": "Volkswagen", "model": "Golf", "year": 2013, "km": 140000, "price": 9000},
        {"id": "3", "make": "Volkswagen", "model": "Golf", "year": 2015, "km": 110000, "price": 10500},
        {"id": "4", "make": "Volkswagen", "model": "Golf", "year": 2014, "km": 130000, "price": 9800},
        {"id": "5", "make": "Volkswagen", "model": "Golf", "year": 2014, "km": 125000, "price": 7200},  # chollo
        {"id": "6", "make": "Seat", "model": "Ibiza", "year": 2014, "km": 100000, "price": 6000},
    ]
    chollo = valorar(dict(universo[4]), universo)
    print("Chollo Golf:", chollo["price"], "€ | medio:", chollo["precio_medio"],
          "€ |", chollo["dif_pct"], "% | comps:", chollo["n_comparables"],
          "| fiable:", chollo["fiable"])
    assert chollo["dif_pct"] < 0, "debería estar por debajo de mercado"
    print("OK valoración")
