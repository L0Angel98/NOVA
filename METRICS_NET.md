# Net Driver Metrics (v0.1.5)

Fecha: 2026-03-02  
Entorno: Windows, Python 3.10, Node v22.13.1  
Repeticiones por caso: 6

## Benchmark reproducible

```bash
python - <<'PY'
import json
import os
import statistics
import time
from nova.cap.http_cap import http_get
from nova.cap.html_cap import html_tte

cases = [
    ("profile", "https://angelvlqz.onrender.com/"),
    ("occ_blocked", "https://www.g2.com/"),
]
n = 6
rows = []
for case, url in cases:
    for driver in ["py", "node"]:
        os.environ["NOVA_NET_DRIVER"] = driver
        times = []
        statuses = []
        extracted = 0
        for _ in range(n):
            t0 = time.perf_counter()
            out = http_get(url, None, 12)
            dt = (time.perf_counter() - t0) * 1000.0
            times.append(dt)
            statuses.append(int(out["st"]))
            if int(out["st"]) == 200 and html_tte(out).strip() != "":
                extracted += 1
        rows.append({
            "case": case,
            "url": url,
            "driver": driver,
            "avg_ms": round(statistics.mean(times), 2),
            "status_mode": max(set(statuses), key=statuses.count),
            "extract_rate": f"{extracted}/{n}",
        })
print(json.dumps(rows, indent=2))
PY
```

## Resultados

| case | endpoint | driver | avg ms | status | extraccion real |
|---|---|---|---:|---:|---|
| profile | `https://angelvlqz.onrender.com/` | py | 228.90 | 200 | si (6/6) |
| profile | `https://angelvlqz.onrender.com/` | node | 379.96 | 200 | si (6/6) |
| occ_blocked | `https://www.g2.com/` | py | 172.66 | 403 | no (0/6) |
| occ_blocked | `https://www.g2.com/` | node | 358.70 | 403 | no (0/6) |

Caso OCC: blocked by site anti-bot (expected behavior).

## Notas

- `http.get` mantiene contrato estable: `{st, hd, bd}` en ambos drivers.
- Los status no-200 se exponen sin silenciar errores.
- El driver `node` esta enfocado en compatibilidad; la latencia puede ser mayor por costo de subprocess.

