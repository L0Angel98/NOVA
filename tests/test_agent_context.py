import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

from nova.agent_context import (
    check_agent,
    default_agent_path,
    default_agent_dictionary_path,
    default_agent_guide_md_path,
    init_agent_knowledge,
    load_agent_rows,
    pack_agent,
    sync_agent,
)
from nova.toon import decode_toon


ROOT = Path(__file__).resolve().parents[1]


class NovaAgentContextTests(unittest.TestCase):
    def test_init_creates_agent_dictionary_and_language_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = init_agent_knowledge(
                root,
                default_agent_dictionary_path(root),
                default_agent_guide_md_path(root),
            )
            self.assertTrue(report.agent_written)
            self.assertTrue(report.dictionary_written)
            self.assertTrue(report.guide_written)
            self.assertGreater(report.agent_rows, 0)
            self.assertGreater(report.dictionary_rows, 0)
            self.assertTrue(report.agent_path.exists())
            self.assertTrue(report.dictionary_path.exists())
            self.assertTrue(report.guide_path.exists())
            self.assertIn("@toon v1", report.agent_path.read_text(encoding="utf-8"))
            self.assertIn("@toon v1", report.dictionary_path.read_text(encoding="utf-8"))
            self.assertIn("NOVA Language Notes", report.guide_path.read_text(encoding="utf-8"))

            rows = {row.key: row.value for row in load_agent_rows(default_agent_path(root))}
            self.assertEqual(rows.get("v"), "0.1.6")
            self.assertIn("cxa", rows)
            aliases = json.loads(rows["cxa"])
            self.assertEqual(aliases, {"q": "query", "p": "params", "h": "headers", "b": "body"})

    def test_sync_creates_auto_keys_and_preserves_manual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            (root / "demo.nv").write_text(
                """
mdl x v"0.1.3" rst<any, err> {
  rte "/p" GET json {
    cap [net]
    rst.ok({ok: tru})
  }
}
""".strip()
                + "\n",
                encoding="utf-8",
            )

            idx = default_agent_path(root)
            sync_1 = sync_agent(root, idx)
            sync_2 = sync_agent(root, idx)
            self.assertGreaterEqual(sync_1.file_count, 1)
            self.assertGreaterEqual(sync_1.route_count, 1)
            self.assertIn("net", decode_toon(idx.read_text(encoding="utf-8"))["cap"])
            self.assertEqual(sync_2.path, idx)

            chk = check_agent(root, idx)
            self.assertTrue(chk.ok, chk.issues)

    def test_pack_outputs_compact_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            sync_agent(root, default_agent_path(root))
            packed = pack_agent(root, default_agent_path(root))
            self.assertIn("@toon v1", packed.text)
            self.assertGreaterEqual(packed.row_count, 1)

    def test_cli_agt_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            (root / "app.nv").write_text(
                """
mdl x v"0.1.3" rst<any, err> {
  rte "/x" GET json { rst.ok({ok: tru}) }
}
""".strip()
                + "\n",
                encoding="utf-8",
            )

            init_proc = subprocess.run(
                ["python", "-m", "nova", "agt", "init", "--root", str(root)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(init_proc.returncode, 0, init_proc.stdout + init_proc.stderr)

            sync_proc = subprocess.run(
                ["python", "-m", "nova", "agt", "sync", "--root", str(root)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(sync_proc.returncode, 0, sync_proc.stdout + sync_proc.stderr)

            chk_proc = subprocess.run(
                ["python", "-m", "nova", "agt", "chk", "--root", str(root)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(chk_proc.returncode, 0, chk_proc.stdout + chk_proc.stderr)

            pack_proc = subprocess.run(
                ["python", "-m", "nova", "agt", "pack", "--root", str(root)],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(pack_proc.returncode, 0, pack_proc.stdout + pack_proc.stderr)
            self.assertIn("@toon v1", pack_proc.stdout)


if __name__ == "__main__":
    unittest.main()
