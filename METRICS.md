# Metricas de release v0.1

Este documento fija metricas reproducibles para DX y eficiencia de payload.

## Metodologia

- Fecha: 2026-03-01
- Repo: este workspace
- Conteo LOC: lineas no vacias, excluyendo comentarios (`//`, `#`).
- Tokens: **proxy determinista** (regex `word|symbol`), no tokenizer propietario.
  - Formula proxy: `len(re.findall(r"[A-Za-z0-9_]+|[^\\sA-Za-z0-9_]", text))`

## 1) LOC: NOVA vs Express baseline

Archivos comparados:

- NOVA: `demo/app.nv`
- Express baseline: `demo/express_baseline.js`

Hallazgos:

- NOVA LOC: `67`
- Express LOC: `172`
- Ratio NOVA/Express: `0.3895`
- Reduccion LOC vs Express: `61.05%`

Lectura:

- Para este caso de CRUD + rutas TOON + contexto + error mapping + cap checks, NOVA expresa el flujo con menos superficie de codigo.

## 2) Tokens y tamaño: JSON vs TOON

Dataset usado:

- 119 filas tabulares de ejemplo (id, name, kind, status, tags[2], score).

Hallazgos:

- JSON bytes: `11292`
- TOON bytes: `6241`
- Reduccion bytes TOON vs JSON: `44.73%`
- JSON token proxy: `6427`
- TOON token proxy: `3476`
- Reduccion token proxy TOON vs JSON: `45.92%`

Lectura:

- En payload tabular, TOON reduce de forma consistente tamaño y tokens proxy frente a JSON en este benchmark.

## Script reproducible (resumen)

- Se puede recalcular ejecutando un script local de Python que:
  - lee `demo/app.nv` y `demo/express_baseline.js`
  - serializa dataset a JSON y TOON (`encode_toon`)
  - calcula LOC/bytes/token-proxy con las reglas anteriores.

## Notas

- Esta metrica es de referencia para v0.1, no benchmark universal.
- El token proxy es util para comparar tendencias locales; no reemplaza conteo exacto de un tokenizer de modelo especifico.
