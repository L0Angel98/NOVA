import os
import unittest
from unittest.mock import patch

from nova.cap.http_cap import HttpCapError, http_get
from nova.cap.net import browser as browser_driver


class NovaBrowserNetDriverV016Tests(unittest.TestCase):
    def tearDown(self) -> None:
        browser_driver._reset_browser_for_tests()

    def test_browser_driver_example_domain_and_keepalive(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "browser"}, clear=False):
            browser_driver._reset_browser_for_tests()
            try:
                out1 = http_get("https://example.com", None, 15)
                out2 = http_get("https://example.com", None, 15)
            except HttpCapError as exc:
                msg = exc.msg.lower()
                if "requires playwright" in msg or "install chromium" in msg:
                    self.skipTest(exc.msg)
                self.skipTest(f"browser net unavailable in this env: {exc.code} {exc.msg}")

        self.assertEqual(out1["st"], 200)
        self.assertIn("Example Domain", out1["bd"])
        self.assertEqual(out2["st"], 200)
        self.assertIn("Example Domain", out2["bd"])

        state = browser_driver._debug_browser_state()
        self.assertEqual(state["starts"], 1)
        self.assertTrue(state["alive"])


if __name__ == "__main__":
    unittest.main()

