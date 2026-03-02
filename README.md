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

### Capabilities

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

