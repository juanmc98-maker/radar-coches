# 🚗 Radar de Coches — Wallapop · Coches.net · Milanuncios

Busca coches en los tres portales, filtra por tus criterios, **tasa cada uno
contra el mercado** y te avisa solo de los que están **en precio medio o por
debajo**, ordenados de mayor chollo a menor.

---

## Qué hace, paso a paso

1. Busca coches de **3.000–12.000 €**, **< 200.000 km**, **30 km de Sabadell**.
2. Exige **etiqueta medioambiental**: gasolina ≥2000, diésel ≥2006 (configurable).
3. Descarta accidentados, para piezas, siniestros, etc.
4. Calcula el **precio medio de mercado** de cada coche comparándolo con los
   demás anuncios equivalentes (misma marca/modelo, año ±1, km parecidos).
5. Te dice el **% por debajo** del mercado. Si está por encima, lo **descarta**.

---

## 🟢 LA FORMA FÁCIL (un clic)

1. Instala **Python 3.10+** desde https://www.python.org/downloads/
   (en Windows, marca la casilla **"Add Python to PATH"** al instalar).
2. **Windows:** doble clic en **EJECUTAR_windows.bat**
   **Mac/Linux:** abre terminal en la carpeta y ejecuta `bash ejecutar_mac_linux.sh`

La primera vez instala todo solo (tarda unos minutos) y luego abre el navegador
para que aceptes cookies. Cuando termine, mira **chollos.csv**.

Para que busque solo cada 30 min: usa **EJECUTAR_continuo_windows.bat**.

---

## La forma manual (si prefieres terminal)

Necesitas **Python 3.10+**. En la carpeta del radar:

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Primer arranque (IMPORTANTE)

La primera vez, lánzalo **con el navegador visible** para aceptar cookies y, si
sale algún captcha en Coches.net o Milanuncios, resolverlo a mano (queda guardado):

```bash
python radar.py --once --headful
```

Mira la consola y el archivo **chollos.csv** (ábrelo con Excel, separador `;`).
Cuando veas que va bien, ya puedes lanzarlo normal:

```bash
python radar.py --once     # una pasada (para cron / programador de tareas)
python radar.py            # bucle cada 30 min
```

---

## Ajustes (config.json)

- **precio_min / precio_max / km_max**: tus límites.
- **anio_min_diesel**: por defecto 2006 (etiqueta B segura). Ponlo en 2005 si
  quieres tu regla original (riesgo de colar algún "sin etiqueta").
- **radio_km / municipios_30km**: el radio lo respeta Wallapop; en los otros dos
  se filtra por la lista de municipios (edítala a tu gusto).
- **margen_chollo_pct**: 0 = avisa de todo lo que esté en la media o por debajo.
  Pon 5 para exigir al menos un 5% por debajo.
- **incluir_sin_valoracion**: true = también te avisa de coches sin suficientes
  comparables (no sabe si es chollo). false = solo chollos confirmados.
- **portales_activos**: pon en false el que no quieras usar.

---

## Avisos al móvil

- **WhatsApp (CallMeBot, gratis):** guarda el número del bot de callmebot.com,
  mándale "I allow callmebot to send me messages", te da una apikey. Ponla en
  `notificaciones.whatsapp` y `"enabled": true`.
- **Telegram:** habla con @BotFather (token) y @userinfobot (chat_id).

---

## ⚠️ Lo que tienes que saber

- **Wallapop** es el motor más fiable. **Coches.net y Milanuncios** tienen
  anti-bot fuerte: pueden fallar o pedir captcha. Si te bloquean a menudo, la
  solución limpia es usar un actor de **Apify** para esos dos (céntimos por
  búsqueda). Dímelo y te cambio esos dos adaptadores.
- La **tasación** es por comparables propios: cuantos más anuncios recoja, mejor
  valora. En la primera pasada con pocos datos, muchos saldrán "sin valoración
  fiable"; mejora según acumula histórico.
- La **etiqueta** se aproxima por combustible+año. Lo definitivo es la norma Euro
  / fecha de matrícula real (app DGT). Úsalo como primer filtro, no como verdad
  absoluta.
- Esto raspa datos públicos para uso propio. Las condiciones de los portales no
  permiten scraping automatizado: intervalos razonables, sin saturar.

---

## Archivos

- `radar.py` — el que ejecutas.
- `portales.py` — un adaptador por portal.
- `filtros.py` — etiqueta, km, precio, negativos.
- `valoracion.py` — el cerebro de la tasación.
- `config.json` — todos tus ajustes.
- `chollos.csv` — resultados (se crea solo).
- `vistos.json` — memoria de lo ya avisado (bórralo para empezar de cero).
