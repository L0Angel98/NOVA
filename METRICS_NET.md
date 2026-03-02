# Net Driver Metrics (v0.1.5.1)

Fecha: 2026-03-02  
Entorno: Windows, Python 3.10, Node v22.13.1

## Keepalive benchmark (node)

Objetivo: comparar `node` keepalive (worker persistente) contra baseline de `spawn por request` (simulado reiniciando worker en cada llamada).

Endpoint: `https://example.com/`  
Requests: 10

Resultados medidos:

- keepalive total: `694.78 ms`
- keepalive starts: `1`
- respawn baseline total: `2852.12 ms`
- respawn starts total: `10`
- mejora estimada: `75.64%`

Benchmark reproducible:

```bash
python - <<'PY'
import os
import time
from nova.cap.http_cap import http_get
from nova.cap.net import node as node_driver

URL = "https://example.com/"
N = 10
os.environ["NOVA_NET_DRIVER"] = "node"

node_driver._reset_worker_for_tests()
t0 = time.perf_counter()
for _ in range(N):
    http_get(URL, None, 10)
keep_ms = (time.perf_counter() - t0) * 1000.0
keep_state = node_driver._debug_worker_state()

respawn_ms = 0.0
respawn_starts = 0
for _ in range(N):
    node_driver._reset_worker_for_tests()
    t1 = time.perf_counter()
    http_get(URL, None, 10)
    respawn_ms += (time.perf_counter() - t1) * 1000.0
    respawn_starts += node_driver._debug_worker_state()["starts"]

node_driver._reset_worker_for_tests()
print("keepalive_ms", round(keep_ms, 2))
print("keepalive_starts", keep_state["starts"])
print("respawn_ms", round(respawn_ms, 2))
print("respawn_starts_total", respawn_starts)
PY
```

## Driver comparison (py vs node keepalive)

Repeticiones por caso: 6

| case | endpoint | driver | avg ms | status |
|---|---|---|---:|---:|
| profile | `https://angelvlqz.onrender.com/` | py | 232.10 | 200 |
| profile | `https://angelvlqz.onrender.com/` | node (keepalive) | 136.11 | 200 |
| occ_blocked | `https://www.g2.com/` | py | 177.18 | 403 |
| occ_blocked | `https://www.g2.com/` | node (keepalive) | 474.49 | 403 |

Caso OCC: blocked by site anti-bot (expected behavior).

## Notas

- `http.get` mantiene contrato estable: `{st, hd, bd}`.
- Status no-200 se propagan sin respuestas vacias silenciosas.
- `node` ahora usa worker keepalive (JSONL), evitando spawn por request.
