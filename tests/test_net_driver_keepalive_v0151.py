import os
import time
import unittest
from unittest.mock import patch

from nova.cap.http_cap import HttpCapError, http_get
from nova.cap.net import node as node_driver


class NovaNodeKeepaliveV0151Tests(unittest.TestCase):
    def tearDown(self) -> None:
        node_driver._reset_worker_for_tests()

    def test_node_worker_is_reused_for_multiple_http_get_calls(self) -> None:
        url = "https://example.com/"
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "node"}, clear=False):
            node_driver._reset_worker_for_tests()

            pids: list[int] = []
            t0 = time.perf_counter()
            for _ in range(5):
                try:
                    out = http_get(url, None, 10)
                except HttpCapError as exc:
                    self.skipTest(f"example.com not reachable in this env: {exc.code} {exc.msg}")
                self.assertEqual(out["st"], 200)
                self.assertNotEqual(str(out["bd"]).strip(), "")
                state = node_driver._debug_worker_state()
                self.assertTrue(state["alive"])
                self.assertIsNotNone(state["pid"])
                pids.append(int(state["pid"]))
            keepalive_ms = (time.perf_counter() - t0) * 1000.0

            state = node_driver._debug_worker_state()
            self.assertEqual(state["starts"], 1)
            self.assertEqual(len(set(pids)), 1, f"expected single worker pid, got {pids}")

            # Baseline approximation of old v0.1.5 behavior: spawn per request.
            t1 = time.perf_counter()
            for _ in range(5):
                node_driver._reset_worker_for_tests()
                out = http_get(url, None, 10)
                self.assertEqual(out["st"], 200)
            respawn_ms = (time.perf_counter() - t1) * 1000.0

            self.assertLess(
                keepalive_ms,
                respawn_ms,
                f"keepalive={keepalive_ms:.2f}ms respawn={respawn_ms:.2f}ms",
            )


if __name__ == "__main__":
    unittest.main()

