# NOVA v0.1.4

NOVA es un DSL IA-first para APIs y scripting con IR estable y backends pluggable.

## Instalacion

```bash
pip install -e .
nova --version
```

## v0.1.4

### Backends

- `interp`: runtime Python para desarrollo.
- `llvm`: AOT con runtime HTTP nativo en binario (`axum` + caps nativas).
- `go`: stub pluggable.

```bash
nova build demo/llvm_serve_profile.nv --b llvm
nova serve demo/llvm_serve_profile.nv --b llvm --cap net --port 3000
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

Output IA-first con keys cortas.

- `http.get(url, h?, t?) -> {st, hd, bd}`
- `html.tte(html) -> str`
- `html.sct(html, css) -> [str]`
- `db.opn(path) -> handle`, `db.qry(h, sql, args?)`, `db.cls(h)`

Permisos en runtime LLVM:

- `--cap net`
- `--cap db`
- `--cap fs`
- `--cap env`

Sin permiso requerido se responde error claro (`NVR200`).

### Agent Context Index

```bash
nova agt init --root .
nova agt sync --root .
```

Archivo generado: `.nova/idx.toon` con keys `v, rt, sum, api, cap, m, dep, chg, ts`.

## Demos

### 1) LLVM nativo: profile scraping

```bash
nova build demo/llvm_serve_profile.nv --b llvm
./out/llvm_serve_profile --cap net --port 3000        # Windows: .\out\llvm_serve_profile.exe --cap net --port 3000
curl http://127.0.0.1:3000/profile
```

### 2) LLVM nativo: SQLite

```bash
nova build demo/llvm_db.nv --b llvm
./out/llvm_db --cap db --port 3001                    # Windows: .\out\llvm_db.exe --cap db --port 3001
curl http://127.0.0.1:3001/db
```

### 3) Interp (compatibilidad v0.1.3)

```bash
nova run demo/db_sqlite.nv --cap db
nova serve demo/scrape_profile.nv --cap net --port 8099
```

## Testing

```bash
python -m unittest discover -s tests -v
cd compiler/llvm && cargo test
```

## Limitaciones v0.1.4

- Backend LLVM soporta subset de handlers (`let`, `cap call`, `rst.ok/err`, JSON literals).
- `rte` soportado para flujo HTTP JSON (GET/otros metodos por matching basico).
- No hay aun compilacion LLVM de AST a machine IR por funcion; se usa runtime embebido con IR interpreter.
- v0.1.5 objetivo: ampliar subset (if/match), typed body JSON robusto y optimizer/codegen real.
