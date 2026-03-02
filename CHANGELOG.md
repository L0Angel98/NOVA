# Changelog

## v0.1.5 (2026-03-02)

- add optional node-based net driver for improved scraping compatibility.
- `cap http.get` ahora selecciona driver por `NOVA_NET_DRIVER=py|node` (default `py`).
- Nuevo driver `node` con Node.js 18+ y `fetch` nativo via subprocess.
- Contrato estable de salida para `http.get`: `{st, hd, bd}`.
- Manejo de errores explicito para driver invalido, Node faltante y fallos de red.
- Benchmark documentado en `METRICS_NET.md`.

## v0.1.4 (2026-03-02)

- LLVM backend ahora compila binarios con runtime HTTP nativo (`axum`) para `rte GET ...`.
- `nova-llvm` agrega modo `build` y modo `serve`/runtime con sidecar IR.
- Capabilities nativas en binario (sin runtime Python):
  - `http.get` (`reqwest`) -> `{st, hd, bd}`
  - `html.tte` / `html.sct` (`scraper`)
  - `db.opn/qry/cls` SQLite (`rusqlite`)
- Guardas de permisos en binario (`--cap net|db|fs|env`) con error claro `[NVR200]`.
- `nova serve --b llvm` compila y ejecuta binario nativo con flags de caps/puerto.
- IR v0.1.4 anade `irv` y preserva `cap` como nodo para paridad de permisos.
- Nuevos demos: `demo/llvm_serve_profile.nv`, `demo/llvm_db.nv`.

## v0.1.3 (2026-03-02)

- Compiler core: nuevo IR estable (`nova/ir`) y serializacion JSON determinista.
- Backends pluggable: `interp`, `llvm`, `go` (stub) con `nova build/run --b ...`.
- LLVM scaffold: subproyecto Rust `compiler/llvm` (`nova-llvm`) para AOT subset.
- Capabilities runtime:
  - `http.get` con salida `{st, hd, bd}` y errores estructurados.
  - `html.tte` / `html.sct`.
  - `db` SQLite (`db.opn`, `db.qry`, `db.cls`).
- Agent context index automatico en `.nova/idx.toon` con `nova agt init/sync`.
- Nuevos demos ejecutables: `hello_llvm.nv`, `scrape_profile.nv`, `db_sqlite.nv`.
- Version bump de paquete y CLI a `0.1.3`.
