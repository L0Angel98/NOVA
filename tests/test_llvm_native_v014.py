import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_json(url: str, *, timeout_s: float = 20.0) -> tuple[int, dict]:
    start = time.time()
    last_exc = None
    while time.time() - start < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=2) as res:
                body = json.loads(res.read().decode("utf-8"))
                return int(res.status), body
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            return int(exc.code), body
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            time.sleep(0.2)
    raise RuntimeError(f"server did not respond in time: {last_exc}")


class _UpstreamHtmlHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        payload = b"<html><head><title>NOVA U</title></head><body><h1>A</h1><p>B</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@unittest.skipUnless(shutil.which("cargo") and shutil.which("rustc"), "cargo/rustc not available")
class NovaLlvmNativeV014Tests(unittest.TestCase):
    def test_llvm_native_profile_and_cap_guard(self) -> None:
        upstream_port = _free_port()
        upstream = ThreadingHTTPServer(("127.0.0.1", upstream_port), _UpstreamHtmlHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            src = work / "profile.nv"
            src.write_text(
                f'''
mdl profile v"0.1.4" rst<any, err> {{
  rte "/profile" GET json {{
    cap [net]
    let pg = http.get("http://127.0.0.1:{upstream_port}/")
    let ti = html.tte(pg)
    let h1 = html.sct(pg, "h1")
    rst.ok({{ti: ti, h1: h1, st: pg.st}})
  }}
}}
'''.strip()
                + "\n",
                encoding="utf-8",
            )
            out_dir = work / "out"
            build = subprocess.run(
                ["python", "-m", "nova", "build", str(src), "--b", "llvm", "--out-dir", str(out_dir)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            exe = out_dir / ("profile.exe" if os.name == "nt" else "profile")
            self.assertTrue(exe.exists(), f"missing binary: {exe}")

            port = _free_port()
            proc = subprocess.Popen([str(exe), "--cap", "net", "--port", str(port)], cwd=ROOT)
            try:
                status, body = _wait_json(f"http://127.0.0.1:{port}/profile")
                self.assertEqual(status, 200, body)
                self.assertTrue(body["ok"])
                self.assertEqual(body["data"]["ti"], "NOVA U")
                self.assertEqual(body["data"]["h1"], ["A"])
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()

            port2 = _free_port()
            proc2 = subprocess.Popen([str(exe), "--port", str(port2)], cwd=ROOT)
            try:
                status, body = _wait_json(f"http://127.0.0.1:{port2}/profile")
                self.assertEqual(status, 403, body)
                self.assertFalse(body["ok"])
                self.assertEqual(body["error"]["code"], "NVR200")
            finally:
                proc2.terminate()
                try:
                    proc2.wait(timeout=5)
                except Exception:
                    proc2.kill()

        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=2)

    def test_llvm_native_db_demo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            build = subprocess.run(
                [
                    "python",
                    "-m",
                    "nova",
                    "build",
                    str(ROOT / "demo" / "llvm_db.nv"),
                    "--b",
                    "llvm",
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

            exe = out_dir / ("llvm_db.exe" if os.name == "nt" else "llvm_db")
            self.assertTrue(exe.exists(), f"missing binary: {exe}")

            port = _free_port()
            proc = subprocess.Popen([str(exe), "--cap", "db", "--port", str(port)], cwd=ROOT)
            try:
                status, body = _wait_json(f"http://127.0.0.1:{port}/db")
                self.assertEqual(status, 200, body)
                self.assertTrue(body["ok"])
                self.assertEqual(body["data"]["n"], 2)
                self.assertEqual(len(body["data"]["it"]), 2)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()


if __name__ == "__main__":
    unittest.main()
