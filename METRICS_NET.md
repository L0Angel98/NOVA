# Net Driver Metrics (v0.1.6)

Fecha: 2026-03-02  
Entorno: Windows, Python 3.10, Node v22.13.1, Playwright 1.58.0 (Chromium)

## Benchmark reproducible

```bash
python - <<'PY'
import os
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nova.cap.http_cap import http_get
from nova.cap.net import browser as browser_driver
from nova.cap.net import node as node_driver

class JsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"""<html><head><title>JS Fixture</title></head><body><div id='app'></div><script>document.getElementById('app').textContent=[74,83,95,79,75].map((c)=>String.fromCharCode(c)).join('');</script></body></html>"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, format, *args):
        return

def run_case(url, n=6):
    rows = []
    for drv in ['py', 'node', 'browser']:
        os.environ['NOVA_NET_DRIVER'] = drv
        if drv == 'node':
            node_driver._reset_worker_for_tests()
        if drv == 'browser':
            browser_driver._reset_browser_for_tests()
        times, statuses, js_ok = [], [], 0
        for _ in range(n):
            t0 = time.perf_counter()
            out = http_get(url, None, 12)
            times.append((time.perf_counter() - t0) * 1000.0)
            statuses.append(int(out['st']))
            if 'JS_OK' in str(out['bd']):
                js_ok += 1
        rows.append((drv, round(statistics.mean(times), 2), max(set(statuses), key=statuses.count), f"{js_ok}/{n}"))
    return rows

server = ThreadingHTTPServer(('127.0.0.1', 0), JsHandler)
thr = threading.Thread(target=server.serve_forever, daemon=True)
thr.start()
js_url = f"http://127.0.0.1:{server.server_address[1]}/js"

print('profile', run_case('https://angelvlqz.onrender.com/'))
print('js_fixture', run_case(js_url))

os.environ['NOVA_NET_DRIVER'] = 'browser'
browser_driver._reset_browser_for_tests()
t0 = time.perf_counter(); http_get('https://angelvlqz.onrender.com/', None, 12); cold = (time.perf_counter() - t0) * 1000.0
warm = []
for _ in range(5):
    t1 = time.perf_counter(); http_get('https://angelvlqz.onrender.com/', None, 12); warm.append((time.perf_counter() - t1) * 1000.0)
print('browser_cold_ms', round(cold, 2))
print('browser_warm_avg_ms', round(statistics.mean(warm), 2))
print('browser_starts', browser_driver._debug_browser_state()['starts'])

browser_driver._reset_browser_for_tests()
server.shutdown(); server.server_close(); thr.join(timeout=2)
PY
```

## Resultados

Repeticiones por caso: `n=6`

| case | endpoint | py avg ms / st | node avg ms / st | browser avg ms / st | js_render (browser) |
|---|---|---:|---:|---:|---|
| profile | `https://angelvlqz.onrender.com/` | 226.63 / 200 | 117.97 / 200 | 534.02 / 200 | n/a |
| js_fixture | local (`/js`) | 1.64 / 200 | 19.14 / 200 | 154.33 / 200 | 6/6 |

Browser cold/warm (profile):

- cold first request: `1078.54 ms`
- warm avg next 5: `358.13 ms`
- browser starts: `1` (keepalive)

## Notas

- Contrato uniforme en todos los drivers: `{st, hd, bd}`.
- `browser` esta pensado para casos con render JS permitido (sin bypass anti-bot).
- Si Chromium no esta instalado: `python -m playwright install chromium`.
