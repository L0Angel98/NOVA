# NOVA v0.1.5

NOVA es un DSL IA-first para APIs y scripting con IR estable y backends pluggable.

## Instalacion

```bash
pip install -e .
nova --version
```

## v0.1.5

### Backends

- `interp`: runtime Python para desarrollo.
- `llvm`: AOT con runtime HTTP nativo en binario (`axum` + caps nativas).
- `go`: stub pluggable.

### Net drivers

- `py` (default): `requests`
- `node` (opcional): Node.js 18+ con `fetch` nativo

Selector por entorno:

```bash
export NOVA_NET_DRIVER=py
nova serve demo/llvm_serve_profile.nv --cap net
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

PowerShell:

```powershell
$env:NOVA_NET_DRIVER="node"
nova serve demo/llvm_serve_profile.nv --cap net
```

Contrato de `http.get` (sin cambios):

- `http.get(url, h?, t?) -> {st, hd, bd}`

### Agent Context Index

```bash
nova agt init --root .
nova agt sync --root .
```

## Demos

```bash
nova build demo/llvm_serve_profile.nv --b llvm
./out/llvm_serve_profile --cap net --port 3000
curl http://127.0.0.1:3000/profile
```

```bash
nova build demo/llvm_db.nv --b llvm
./out/llvm_db --cap db --port 3001
curl http://127.0.0.1:3001/db
```

## Testing

```bash
python -m unittest discover -s tests -v
cd compiler/llvm && cargo test
```
