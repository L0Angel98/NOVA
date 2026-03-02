# NOVA v0.1

NOVA es un DSL IA-first para APIs y scripting, con foco en:

- Menos tokens
- Menos ambiguedad
- Flujo declarativo (rutas, DB IR, capacidades)
- Formatos `json` y `toon`

toon: formato tabular comprimido nativo de NOVA. Alternativa a JSON
disenada para agentes IA — menos tokens, estructura fija, parseable
sin librerias externas.

Estado: `v0.1` estable para uso de desarrollo y demos.

## Instalacion

Requisitos:

- Python >= 3.10
- pip >= 22 (recomendado: actualizar con python -m pip install --upgrade pip)

El proyecto usa pyproject.toml como sistema de build.
No se requiere setup.py.

Instalacion de desarrollo (recomendada):

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS/Linux
pip install -e .
nova --help
```

Instalacion global (sin venv):

```bash
pip install -e .
nova --help
```

Nota: si pip install -e . falla, ver seccion Troubleshooting.

## Uso del CLI

Comandos visibles:

- Parse: `nova parse archivo.nv`
- Format: `nova fmt archivo.nv`
- Type check: `nova check archivo.nv`
- Runtime HTTP: `nova serve demo/app.nv --cap db`
- Agent Context:
  - `nova agt init --root .`
  - `nova agt sync --root .`
  - `nova agt chk --root .`
  - `nova agt pack --root . --output demo/agent.pack.toon`
- Tests: `python -m unittest discover -s tests -v`

El modo modulo de Python sigue siendo compatible para backward compatibility.

## Agent Context (TOON) generado por `nova agt init`

`nova agt init --root .` ahora genera `agent.toon` con keys cortas IA-first
como formato por defecto. Se mantiene compatibilidad con flujos legacy via `leg`
y con `nova agt sync/chk/pack`.

Keys cortas principales:

- `v`: version del contrato de agente (`0.1.2`)
- `k`: tipo de documento (`agt`)
- `gen`: metadatos del generador (`by`, `at`, `os`, `py`)
- `rt`: root relativo
- `pn`: nombre de proyecto
- `ig`: globs ignorados recomendados
- `ns`: namespaces reservados (`ctx`, `db`)
- `cxa`: aliases de contexto (`q`, `p`, `h`, `b`)
- `cap`: capacidades experimentales documentadas (`net`, `html`)
- `fs`: resumen de filesystem (`ent`, `upd`)
- `fls`: lista corta de archivos importantes
- `tsk`: tareas iniciales sugeridas (`sync`, `chk`, `pack`)
- `leg`: bloque de compatibilidad legacy

Ejemplo minimo:

```toon
@toon v1
@type table
|key|value|origin|
|"v"|"0.1.2"|"manual"|
|"k"|"agt"|"manual"|
|"cxa"|"{\"b\":\"body\",\"h\":\"headers\",\"p\":\"params\",\"q\":\"query\"}"|"manual"|
|"tsk"|"[\"sync\",\"chk\",\"pack\"]"|"manual"|
```

## Demo

Archivo de demo: `demo/app.nv`

Incluye:

- CRUD `json`
- Endpoints `toon`
- DB IR declarativo (`tb`, `whe`, `lim`, `ord`)
- Enforcement real de `cap`

Nota de sintaxis:

- Los strings son `"..."` sin prefijo. `str"..."` fue removido.
- Los metodos HTTP (`GET`, `POST`, `PUT`, `DEL`, `PAT`, `OPT`, `HED`) son keywords sin comillas.
- `nova fmt` normaliza ambas convenciones automaticamente.
- Alias estandar de contexto: `ctx.q` (query), `ctx.p` (params), `ctx.h` (headers), `ctx.b` (body).
- Ejemplo:

```nova
rte "/items" POST json {
  tb items
  grd ctx.b, ctx.b.name : "BAD_REQUEST"
  rst.ok(db.create(ctx.b))
}
```

## Troubleshooting

Si `nova` no se encuentra:

- activa el entorno virtual donde instalaste el paquete
- verifica instalacion con `pip show nova-lang`
- reinstala en modo editable con `pip install -e .`

Si `pip install -e .` falla con `Cannot set --home and --prefix together`:

- ejecuta `pip config debug` para ubicar el `pip.ini`/`pip.cfg` activo
- ejecuta `pip config list` y busca claves `home`, `prefix` o `target`
- elimina esas claves del bloque `[global]` (o ejecuta `pip config unset global.target` si aplica)
- vuelve a correr `pip install -e .`

## Documentacion de release

- Especificacion: `SPEC.md`
- Ejemplos: `EXAMPLES.md`
- Notas tecnicas: `NOTES.md`
- Roadmap v0.2: `ROADMAP_v0.2.md`
- Limitaciones conocidas: `LIMITATIONS.md`
- Metricas de release: `METRICS.md`

## Alcance de esta fase de release

Esta fase pule DX + estabilidad + documentacion.

No agrega features nuevas de lenguaje.

## How to test

```bash
pip install -e .
nova --help
nova fmt demo/app.nv
nova agt pack --root . --output demo/agent.pack.toon
```

## Runtime Error Format (.toon)

Errores de ruta en DSL usan `err { code, msg }` dentro de `rst`.
El runtime tambien emite errores estructurados en TOON para fallos de parse/validacion:

Cuando el runtime encuentra un `.nv` invalido, devuelve error estructurado en TOON:

```toon
@toon v1
@type error
|k|v|
|"line"|"12"|
|"token"|"whe"|
|"expected"|"tb antes de whe"|
|"file"|"app.nv"|
|"severity"|"error"|
```

El agente debe esperar y parsear este formato en el loop de iteracion.

## Changelog

### v0.1.0 — Release inicial
- Parser (.nv -> AST JSON)
- Formatter canonico (nova fmt)
- Type checker estatico (nova check)
- Runtime HTTP (nova serve)
- Agent Context system (nova agt)
- Formatos de respuesta: json y toon
- Enforcement de capabilities (cap)
- DB IR declarativo (tb, whe, lim, ord)

### v0.1.1 — Ajuste de sintaxis de strings
- `str"..."` deja de ser obligatorio en codigo fuente.
- `nova fmt` normaliza strings a `"..."`.

### v0.1.2 — Refactor sintaxis IA-first
- str"..." removido del spec. nova fmt lo normaliza automaticamente. El runtime lo acepta pero no es sintaxis valida nueva.
- Metodos HTTP promovidos a keywords (`GET`, `POST`, `PUT`, `DEL`, `PAT`, `OPT`, `HED`)
- `rst<any, err>` declarado una vez en firma de modulo
- `cap [db]` inferido automaticamente desde `tb`
- `grd` reemplaza cascadas de validacion de nulos `BAD_REQUEST`
- Version del modulo en firma con `v"x.x.x"`
- Formato de error del runtime estandarizado en `.toon`
