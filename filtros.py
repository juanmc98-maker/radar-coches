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


# ============================================================
#  PERFIL MOTOS DE AGUA (jet ski) — segundo radar
# ============================================================
import math

# Frases que SOLO existen en acuáticas: señal fuerte de moto de agua
_MOTO_AGUA_FUERTE = [
    "moto de agua", "moto acuatica", "motoacuatica", "jet ski", "jetski",
    "jet-ski", "seadoo", "sea-doo", "sea doo", "waverunner", "wave runner",
    "personal watercraft",
]
# Modelos acuáticos (refuerzan cuando van con marca acuática)
_MOTO_AGUA_MODELOS = [
    "gti", "gtx", "gtr", "rxp", "rxt", "spark", "wake", "fish pro", "fishpro",
    "gp1800", "gp 1800", "gp1300", "vx", "vxr", "vx cruiser", "vx deluxe",
    "vx limited", "fx", "fx cruiser", "fx svho", "fx ho", "ex deluxe",
    "ex sport", "superjet", "super jet", "jetblaster", "ultra 310",
    "ultra 300", "ultra lx", "stx", "sx-r", "aquatrax", "f-12", "r-12",
]
# Estilos de moto de CALLE (lista amplia, informativa)
_ESTILOS_CALLE = [
    "scooter", "naked", "sport", "sportbike", "trail", "custom", "enduro",
    "cruiser", "touring", "cafe racer", "ciclomotor", "quad", "atv",
    "supermotard", "trial", "scrambler",
]
# Estilos INEQUÍVOCAMENTE de calle: si motorbike_style trae uno de estos -> fuera.
# OJO: NO incluimos sport/cruiser/touring/custom porque las motos de agua usan
# esos mismos nombres de modelo (Yamaha VX Cruiser, Sea-Doo GTI Sport...).
_ESTILOS_SOLO_CALLE = [
    "scooter", "naked", "enduro", "ciclomotor", "quad", "atv",
    "supermotard", "trial", "scrambler", "cafe racer",
]
# Señales en el TEXTO de que es moto de carretera (no acuática)
_MARCADORES_CALLE_TXT = [
    "scooter", "xmax", "x max", "tmax", "t max", "pcx", "ciclomotor",
    "quad", "atv", "naked", "enduro", "trial", "cafe racer", "supermotard",
    "scrambler", "carnet a2", "carnet a1", "matricula",
]
# Accesorios / piezas sueltas (si el TÍTULO es esto y no hay marca/modelo -> fuera)
_ACCESORIOS = [
    "remolque", "carro", "funda", "tapa", "soporte", "recambio", "despiece",
    "piezas", "accesorio", "chaleco", "boya", "ancla", "manillar", "asiento",
    "tapizado", "helice", "rejilla", "turbina", "bujia", "intercooler",
    "estator", "filtro", "bateria", "cargador", "plataforma", "rampa",
    "toldo", "neopreno", "alarma",
]
# Pistas de ALQUILER (no compra a particular) -> fuera
_ALQUILER = [
    "alquiler", "alquilo", "se alquila", "alquilamos", "fianza", "/dia",
    "euro/dia", "por horas", "media jornada", "jornada completa", "ruta guiada",
    "excursion", "experiencia", "bautismo", "reserva tu", "reservas:",
]
# Señales de 2 tiempos (queremos SOLO 4T)
_DOS_TIEMPOS = ["2 tiempos", "dos tiempos", " 2t", "(2t)", "2-tiempos"]
# Vendedor profesional (queremos solo particulares)
_PRO = ["pro", "professional", "profesional", "comercial", "store", "shop", "concesionario"]
# Embarcaciones que NO son moto de agua (barcas, lanchas, neumáticas, RIB...)
_BARCA = [
    "barca", "neumatica", "neumática", "semirrigida", "semirrígida", "zodiac",
    "lancha", "embarcacion", "embarcación", "fueraborda", "fuera borda",
    "velero", "yate", "patin", "patín", "llaut", "llaüt", "pneumatica",
]


def _texto_moto(item: dict) -> str:
    return _norm(f"{item.get('title') or ''} {item.get('description') or ''}")


def es_moto_agua(item: dict) -> bool:
    """True si el anuncio es claramente una moto de agua."""
    t = _texto_moto(item)
    if any(p in t for p in _MOTO_AGUA_FUERTE):
        return True
    marcas_acua = ["yamaha", "kawasaki", "honda", "polaris", "bombardier",
                   "sea doo", "sea-doo", "seadoo"]
    if any(m in t for m in marcas_acua) and any(x in t for x in _MOTO_AGUA_MODELOS):
        return True
    return False


def _es_accesorio(item: dict) -> bool:
    """Pieza/accesorio suelto: el título es un accesorio y no hay moto detrás."""
    titulo = _norm(item.get("title") or "")
    tiene_moto = item.get("make") or any(x in titulo for x in _MOTO_AGUA_MODELOS)
    if tiene_moto:
        return False
    return any(a in titulo for a in _ACCESORIOS)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def en_radio(item: dict, cfg: dict) -> bool:
    """Comprueba el radio desde Sabadell si el anuncio trae coordenadas.
    Sin coordenadas no descartamos (la URL de búsqueda ya acota la zona)."""
    lat, lng = item.get("lat"), item.get("lng")
    if lat is None or lng is None:
        return True
    lat0 = cfg.get("lat", 41.5483)
    lng0 = cfg.get("lng", 2.1075)
    radio = cfg.get("radio_km", 100)
    try:
        return haversine_km(lat0, lng0, float(lat), float(lng)) <= radio + 5
    except Exception:
        return True


def pasa_filtros_moto(item: dict, cfg: dict) -> tuple[bool, str]:
    """Filtros duros para motos de agua. Devuelve (pasa, motivo_si_no_pasa)."""
    if not es_moto_agua(item):
        return False, "no es moto de agua"

    # barca / lancha / neumática: es embarcación, no moto de agua
    titulo = _norm(item.get("title") or "")
    if any(b in titulo for b in _BARCA):
        return False, "es barca/embarcación"

    t = _texto_moto(item)

    # alquileres fuera
    for a in _ALQUILER:
        if a in t:
            return False, f"alquiler ('{a.strip()}')"

    # moto de calle (por estilo declarado o por modelo de carretera)
    estilo = _norm(item.get("motorbike_style") or "")
    if estilo and any(e in estilo for e in _ESTILOS_SOLO_CALLE):
        return False, f"moto de calle (estilo: {estilo})"
    if any(x in t for x in ["xmax", "x max", "tmax", "t max", "pcx", "scooter de"]):
        return False, "moto de calle (modelo)"

    # accesorio / pieza suelta
    if _es_accesorio(item):
        return False, "accesorio/pieza suelta"

    # 2 tiempos fuera (solo 4T)
    if cfg.get("solo_4_tiempos", True) and any(d in t for d in _DOS_TIEMPOS):
        return False, "2 tiempos"

    # vendedor profesional fuera (solo particulares)
    st = (item.get("seller_type") or "").lower()
    if st and any(p in st for p in _PRO):
        return False, "vendedor profesional"

    # precio
    precio = item.get("price")
    if precio is None:
        return False, "sin precio"
    if precio < cfg.get("precio_min", 1500):
        return False, "precio por debajo del minimo"
    if precio > cfg.get("precio_max", 15000):
        return False, "precio por encima del maximo"

    # zona
    if not en_radio(item, cfg):
        return False, "fuera de radio"

    return True, ""


# ============================  CAMPERS / AUTOCARAVANAS  ============================
# Palabras de AUTOCARAVANA/camper inequívocas (vehículo seguro)
_CAMPER_FUERTE = [
    "autocaravana", "auto caravana", "motorhome", "motor home",
    "camperizada", "camperizado", "camperizacion", "perfilada",
    "capuchina", "integral",
]
# Palabras ambiguas: "camper" es tb marca de ZAPATOS y de MUEBLES; los modelos
# (california, etc.) sin contexto no bastan. Exigen señal de vehículo.
_CAMPER_DEBIL = [
    "camper", "furgo camper", "furgoneta camper", "furgon camper",
    "camper van", "campervan", "california", "marco polo", "westfalia",
]
# Señales de que detrás hay un VEHÍCULO (marca base / chasis / modelo)
_VEHICULO_BASE = [
    "fiat", "citroen", "peugeot", "ford", "mercedes", "renault",
    "volkswagen", "iveco", "ducato", "jumper", "boxer", "transit",
    "sprinter", "crafter", "master", "daily", "transporter", "trafic",
    "hymer", "adria", "benimar", "knaus", "challenger", "chausson",
    "rapido", "pilote", "burstner", "dethleffs", "carthago", "weinsberg",
    "possl", "mclouis", "elnagh", "roller team", "sunlight", "dreamer",
]
# Palabras de aseo/baño interior
_BANO_PALABRAS = ["bano", "aseo", "wc", "inodoro", "cassette", "sanitario", "lavabo"]
# Accesorios/piezas de camper (si el título es esto y no hay camper detrás -> fuera)
_CAMPER_ACCESORIOS = [
    "toldo", "claraboya", "portabicis", "porta bicis", "estor", "mosquitera",
    "calefaccion", "calefactor", "nevera", "placa solar", "placas solares",
    "deposito", "escalon", "estribera", "funda", "soporte", "recambio",
    "despiece", "piezas", "rueda", "neumatico", "espejo", "tapiceria",
    "asiento", "ventana", "bomba de agua", "mueble", "armario", "colchon",
    "matalas", "matalàs", "cable", "inversor", "sandalia", "zapato",
    "zapatilla", "bota",
]
# Estructuras que NO son vehículo camper (no se conducen): bungalows, casas móviles
_NO_CAMPER_ESTRUCTURA = [
    "bungalow", "mobil home", "mobilhome", "mobile home", "mobil-home",
    "casa movil", "casa prefabricada", "prefabricada", "modulo habitable",
]


def es_camper(item: dict) -> bool:
    """True si el anuncio es una camper / autocaravana (vehículo, no zapatos/muebles)."""
    t = _texto_moto(item)
    if any(p in t for p in _CAMPER_FUERTE):
        return True
    # "camper" y modelos ambiguos: solo si hay señal clara de vehículo
    if any(p in t for p in _CAMPER_DEBIL):
        if item.get("year") or item.get("km") or any(b in t for b in _VEHICULO_BASE):
            return True
    return False


def tiene_bano_ducha(item: dict) -> bool:
    """Exige baño interior CON ducha (la ducha exterior sola no cuenta)."""
    t = _texto_moto(item)
    if "bano completo" in t or "aseo completo" in t or "bano con ducha" in t:
        return True
    tiene_ducha = "ducha" in t
    solo_ducha_ext = ("ducha exterior" in t) and (t.count("ducha") == 1)
    tiene_bano = any(b in t for b in _BANO_PALABRAS)
    return tiene_ducha and tiene_bano and not solo_ducha_ext


def _es_accesorio_camper(item: dict) -> bool:
    titulo = _norm(item.get("title") or "")
    if any(p in titulo for p in (_CAMPER_FUERTE + _CAMPER_DEBIL)):
        return False  # el título ya menciona camper/autocaravana
    return any(a in titulo for a in _CAMPER_ACCESORIOS)


def pasa_filtros_camper(item: dict, cfg: dict) -> tuple[bool, str]:
    """Filtros duros para campers/autocaravanas con baño y ducha."""
    if not es_camper(item):
        return False, "no es camper/autocaravana"

    # bungalow / casa móvil / prefabricada: no es un vehículo
    titulo = _norm(item.get("title") or "")
    if any(x in titulo for x in _NO_CAMPER_ESTRUCTURA):
        return False, "es bungalow/casa movil (no vehiculo)"

    t = _texto_moto(item)

    # alquiler fuera
    for a in _ALQUILER:
        if a in t:
            return False, f"alquiler ('{a.strip()}')"

    # accesorio / pieza suelta
    if _es_accesorio_camper(item):
        return False, "accesorio/pieza suelta"

    # tiene que llevar baño + ducha (requisito de Juan)
    if not tiene_bano_ducha(item):
        return False, "sin bano/ducha"

    # vendedor profesional fuera (solo particulares)
    st = (item.get("seller_type") or "").lower()
    if st and any(p in st for p in _PRO):
        return False, "vendedor profesional"

    # precio
    precio = item.get("price")
    if precio is None:
        return False, "sin precio"
    if precio < cfg.get("precio_min", 6000):
        return False, "precio por debajo del minimo"
    if precio > cfg.get("precio_max", 25000):
        return False, "precio por encima del maximo"

    # zona
    if not en_radio(item, cfg):
        return False, "fuera de radio"

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
