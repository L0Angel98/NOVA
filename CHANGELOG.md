# Changelog

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

