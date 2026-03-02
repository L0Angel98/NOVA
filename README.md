# NOVA v0.1.3

NOVA es un DSL IA-first para APIs y scripting con claves cortas y flujo declarativo.

## Instalacion

```bash
pip install -e .
nova --version
```

## v0.1.3

### Backends

- `interp`: backend por defecto para `run` y `serve`.
- `llvm`: AOT para subset (genera binario nativo con `nova-llvm`).
- `go`: stub pluggable para siguiente iteracion.

Comandos:

```bash
nova run demo/db_sqlite.nv --b interp --cap db
nova build demo/hello_llvm.nv --b llvm
```

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

- `net`: `http.get(url, h?, t?) -> {st, hd, bd}`
- `html`: `html.tte(html)` y `html.sct(html, css)`
- `db`: `db.opn(path)`, `db.qry(h, sql, args?)`, `db.cls(h)` (SQLite db0)

Ejemplos:

```bash
nova serve demo/scrape_profile.nv --cap net
nova run demo/db_sqlite.nv --cap db
```

### Agent Context Index

`agt` ahora usa `.nova/idx.toon`.

```bash
nova agt init --root .
nova agt sync --root .
```

Estructura compacta del index:

- `v`, `rt`, `sum`, `api`, `cap`, `m`, `dep`, `chg`, `ts`

## Demos v0.1.3

### 1) LLVM subset

```bash
nova build demo/hello_llvm.nv --b llvm
./out/hello_llvm      # Windows: .\out\hello_llvm.exe
```

Salida esperada: JSON estatico (`hello nova`).

### 2) Scraping profile (serve/interp)

```bash
nova serve demo/scrape_profile.nv --cap net --port 8099
curl http://127.0.0.1:8099/profile
```

### 3) SQLite db0 (run/interp)

```bash
nova run demo/db_sqlite.nv --cap db
```

## Limitaciones LLVM v0.1.3

- Subset soportado: `let`, literales `json`, `rst.ok` estatico y `print` simple.
- No compila aun rutas HTTP completas ni capacidades en binario AOT.
- El backend `go` queda como interfaz/stub.

## Testing

```bash
python -m unittest discover -s tests -v
```

