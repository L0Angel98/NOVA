from pathlib import Path
import subprocess
import tempfile
import unittest

from nova.agent_context import check_agent, default_agent_path, init_agent_knowledge, pack_agent, sync_agent
from nova.toon import decode_toon


ROOT = Path(__file__).resolve().parents[1]


class NovaAgentContextTests(unittest.TestCase):
    def test_init_creates_idx_toon(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            report = init_agent_knowledge(root, root / "agent.dictionary.toon", root / "NOVA_LANGUAGE.md")

            self.assertTrue(report.agent_path.exists())
            self.assertEqual(report.agent_path, default_agent_path(root))

            value = decode_toon(report.agent_path.read_text(encoding="utf-8"))
            self.assertTrue(isinstance(value, dict))
            for key in ["v", "rt", "sum", "api", "cap", "m", "dep", "chg", "ts"]:
                self.assertIn(key, value)

    def test_sync_updates_index_and_changelog(self) -> None:
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

