#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
filtros.py — reglas de descarte ANTES de valorar.
"""

import unicodedata


def _norm(s: str) -> str:
    """minúsculas y sin acentos, para comparar 'Citroën' con 'citroen'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def es_modelo_bueno(coche: dict, cfg: dict) -> bool:
    """¿El coche es uno de los modelos que buscamos? Si la lista está vacía, pasa todo."""
    buenos = cfg.get("modelos_buenos", [])
    if not buenos:
        return True
    texto = _norm(f"{coche.get('make') or ''} {coche.get('model') or ''} "
                  f"{coche.get('title') or ''}")
    return any(_norm(b) in texto for b in buenos)


# Palabras que descartan un anuncio (se buscan en título y descripción)
NEGATIVOS_DEFECTO = [
    "accidentado", "accidente", "siniestro", "siniestrado", "para piezas",
    "despiece", "no arranca", "no funciona", "averiado", "avería grave",
    "golpe", "golpeado", "granizo", "pedrisco", "inundado", "quemado",
    "fundido", "junta de culata", "para exportar", "exportación",
    "sin itv", "sin papeles", "documentación", "embargo", "reservado",
    "vendido", "leer descripción", "leer anuncio",
]


def tiene_etiqueta(coche: dict, cfg: dict) -> bool:
    """
    ¿Tiene etiqueta medioambiental DGT? Aproximación por combustible+año.
    cfg trae: anio_min_gasolina (2000), anio_min_diesel (2006).
    Si no sabemos el combustible, exigimos año >= max(ambos) para ir seguros.
    """
    year = coche.get("year")
    if not year:
        return False  # sin año no podemos garantizar etiqueta
    year = int(year)
    fuel = (coche.get("fuel") or "").lower()

    min_gas = cfg.get("anio_min_gasolina", 2000)
    min_die = cfg.get("anio_min_diesel", 2006)

    if "diesel" in fuel or "diésel" in fuel or "gasoil" in fuel or "gasóleo" in fuel:
        return year >= min_die
    if "gasolina" in fuel or "glp" in fuel or "gpl" in fuel or "gas licuado" in fuel \
       or "autogas" in fuel or "autogás" in fuel or "gnc" in fuel \
       or "híbrido" in fuel or "hibrido" in fuel or "eléctrico" in fuel \
       or "electrico" in fuel:
        return year >= min_gas
    # Combustible desconocido -> exigimos el corte más restrictivo
    return year >= max(min_gas, min_die)


def pasa_filtros_duros(coche: dict, cfg: dict) -> tuple[bool, str]:
    """Devuelve (pasa, motivo_si_no_pasa)."""
    if not es_modelo_bueno(coche, cfg):
        return False, "modelo no buscado"

    precio = coche.get("price")
    if precio is None:
        return False, "sin precio"
    if precio < cfg.get("precio_min", 3000):
        return False, "precio por debajo del mínimo"
    if precio > cfg.get("precio_max", 12000):
        return False, "precio por encima del máximo"

    km = coche.get("km")
    if km is not None and km > cfg.get("km_max", 200000):
        return False, "demasiados km"

    if not tiene_etiqueta(coche, cfg):
        return False, "sin etiqueta medioambiental (combustible/año)"

    texto = ((coche.get("title") or "") + " " + (coche.get("description") or "")).lower()
    negativos = cfg.get("palabras_negativas", NEGATIVOS_DEFECTO)
    for mal in negativos:
        if mal.lower() in texto:
            return False, f"palabra negativa: '{mal}'"

    # Motores a evitar (correa en aceite, cadenas problematicas, etc.)
    texto_motor = ((coche.get("title") or "") + " "
                   + (coche.get("version") or "")).lower()
    for mal in cfg.get("motores_excluir", []):
        if mal.lower() in texto_motor:
            return False, f"motor a evitar: '{mal}'"

    # Radio: si el anuncio trae municipio y tenemos lista permitida, filtramos
    municipios = [m.lower() for m in cfg.get("municipios_30km", [])]
    if municipios and coche.get("city"):
        if coche["city"].lower() not in municipios:
            # No descartamos en duro (la ciudad puede venir rara); marcamos
            coche["fuera_radio_posible"] = True
    return True, ""


if __name__ == "__main__":
    cfg = {"anio_min_gasolina": 2000, "anio_min_diesel": 2006}
    pruebas = [
        ({"year": 2004, "fuel": "diesel"}, False),   # diésel viejo -> sin etiqueta
        ({"year": 2007, "fuel": "diesel"}, True),     # diésel con B
        ({"year": 2001, "fuel": "gasolina"}, True),   # gasolina con B
        ({"year": 1998, "fuel": "gasolina"}, False),  # gasolina sin etiqueta
        ({"year": 2010, "fuel": ""}, True),           # desconocido pero moderno
    ]
    for c, esperado in pruebas:
        r = tiene_etiqueta(c, cfg)
        print(c, "->", r, "OK" if r == esperado else "FALLO")
        assert r == esperado
    print("OK filtros de etiqueta")
