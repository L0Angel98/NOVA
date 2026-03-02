# NOTES

## Stack

- Python 3.10
- Sin dependencias externas
- Parser recursivo descendente + AST canonico
- Runtime HTTP con `http.server`

## Comandos

- `nova parse archivo.nv`
- `nova fmt archivo.nv`
- `nova fmt archivo.nv --write`
- `nova check archivo.nv`
- `nova serve demo/app.nv --host 127.0.0.1 --port 8080`
  - con capabilities: `nova serve demo/app.nv --cap db --cap env`
- Agent Context:
  - `nova agt sync --root .`
  - `nova agt chk --root .`
  - `nova agt pack --root . --output demo/agent.pack.toon`
- `python -m unittest discover -s tests -v`

## TOON v0.1 implementado

- Encoder: `nova.toon.encode_toon(value)`
- Decoder: `nova.toon.decode_toon(text)`
- Utilities de tamano:
  - `nova.toon.toon_size_bytes(value)`
  - `nova.toon.json_size_bytes(value)`

### Formato

- MIME: `text/toon`
- Version: `@toon v1`
- Modos:
  - `@type table` para arrays tabulares (`list[object]`)
  - `@type json` fallback para cualquier payload JSON-compatible
- Validacion `[N]` en cabecera tabular:
  - columnas como `tags[2]` obligan arrays de longitud exacta 2 por fila (o `nul`)
  - interpretacion aplicada en v0.1: `[N]` valida longitud de arrays por columna (no cardinalidad total de filas)
- Round-trip garantizado para payloads producidos por el encoder:
  - `decode_toon(encode_toon(x)) == x`

## Runtime HTTP

- `rte` soporta `GET/POST/PUT/DELETE`
- `json` y `toon` en rutas
- Contexto en handlers:
  - `params`, `query`, `headers`, `body`, `ctx`
- Parsing body por `Content-Type`:
  - `application/json` -> JSON
  - `text/toon` -> TOON
- Response por formato de ruta:
  - `json` -> `application/json`
  - `toon` -> `text/toon`

## DB IR declarativo v0.1

- Nuevo IR intermedio en `nova/db_ir.py`:
  - `DbIr` (representacion declarativa de `tb/whe/lim/ord`)
  - `DbPlan` (plan resuelto para adapter)
- In-memory adapter dedicado:
  - `InMemoryDbIrAdapter`
  - Sin SQL raw, sin joins, sin optimizaciones.
- Formas soportadas:
  - `tb users.get`
  - `tb users.q { whe ... lim ... ord ... }`
- `tb` guarda/actualiza el plan activo en `db_ir` (visible en runtime).
- `db.read/create/update/delete` ejecutan el plan IR activo.

## Enforcement real de `cap`

- Modelo de seguridad:
  - allowlist fija al iniciar runtime (`--cap net|db|env|fs`)
  - default deny: si no se pasa `--cap`, no hay capacidades concedidas
  - declaracion explicita por ruta con `cap [...]`
  - sin permisos dinamicos y sin overrides
- Reglas:
  - operaciones `db.*` requieren `cap db`
  - operaciones `env.*` requieren `cap env`
  - operaciones `fs.*` requieren `cap fs`
  - operaciones `net.*` requieren `cap net`
  - `cap` debe ser top-level en `rte` y estatico (strings/identifiers literales)
- Bloqueos en runtime:
  - `CAP_DECLARATION_REQUIRED` (403): la ruta no declaro el cap requerido
  - `CAP_FORBIDDEN` (403): runtime no tiene concedido ese cap

## Agent Context (`agent.toon`)

- Objetivo:
  - reducir tokens para sesiones IA
  - memoria estable y determinista del proyecto
- Comandos:
  - `agt sync`: sincroniza `agent.toon` con snapshot del repo
  - `agt chk`: valida formato + deriva (drift) contra snapshot actual
  - `agt pack`: genera payload compacto para contexto IA
- Formato:
  - `agent.toon` se guarda en TOON v1 tabular con columnas `key`, `value`, `origin`
  - `origin` permitido: `manual` | `auto`
- Convencion de claves:
  - claves `sys.*` = auto-gestionadas por `agt sync`
  - claves no `sys.*` = manuales

### Que actualiza `agt sync`

- Actualiza/crea solo claves `sys.*` (auto):
  - version de agente
  - metricas de snapshot (files/routes/tests/hash)
  - modelo de seguridad/cap
  - fecha de sync UTC
- Migra formato legacy de `agent.toon` a TOON v1 cuando aplica.

### Que NO actualiza `agt sync`

- No modifica claves manuales (no `sys.*`).
- No ejecuta embeddings.
- No usa vector DB.
- No modifica codigo fuente del runtime/parser/checker por si mismo.

### Que valida `agt chk`

- Duplicados de clave.
- `origin` valido por fila.
- Presencia de claves auto esperadas.
- Drift entre snapshot guardado y snapshot actual (excepto timestamp de sync).

### Que hace `agt pack`

- No muta `agent.toon`.
- Produce TOON compacto (`k`,`v`) con subset de `sys.*` + claves manuales.
- Diseñado para pegarse como contexto de bajo token en prompts/agents.

## Restricciones respetadas

- No binario
- No schema registry externo
- No DB real (solo in-memory mock)
- No auth real
