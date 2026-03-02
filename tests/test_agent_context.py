import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

from nova.agent_context import (
    check_agent,
    default_agent_dictionary_path,
    default_agent_guide_md_path,
    init_agent_knowledge,
    pack_agent,
    sync_agent,
)


ROOT = Path(__file__).resolve().parents[1]


class NovaAgentContextTests(unittest.TestCase):
    def test_init_creates_dictionary_and_language_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = init_agent_knowledge(
                root,
                default_agent_dictionary_path(root),
                default_agent_guide_md_path(root),
            )
            self.assertTrue(report.dictionary_written)
            self.assertTrue(report.guide_written)
            self.assertGreater(report.dictionary_rows, 0)
            self.assertTrue(report.dictionary_path.exists())
            self.assertTrue(report.guide_path.exists())
            self.assertIn("@toon v1", report.dictionary_path.read_text(encoding="utf-8"))
            self.assertIn("NOVA Language Notes", report.guide_path.read_text(encoding="utf-8"))

    def test_sync_creates_auto_keys_and_preserves_manual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "SPEC.md").write_text("spec", encoding="utf-8")
            (root / "a.nv").write_text('rte str"/x" str"GET" json: rst<any, err> { rst.ok(str"ok") }', encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
            (root / "agent.toon").write_text(
                """toon agent_context {
| key | value |
| project_name | \"TMP\" |
| custom_note | \"keep\" |
}
""",
                encoding="utf-8",
            )

            rst = sync_agent(root, root / "agent.toon")
            self.assertGreater(rst.auto_count, 0)

            chk = check_agent(root, root / "agent.toon")
            self.assertTrue(chk.ok)

            packed = pack_agent(root, root / "agent.toon")
            self.assertIn("@toon v1", packed.text)
            self.assertIn("custom_note", packed.text)

    def test_chk_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "SPEC.md").write_text("spec", encoding="utf-8")
            (root / "a.nv").write_text('rte str"/x" str"GET" json: rst<any, err> { rst.ok(str"ok") }', encoding="utf-8")
            agent = root / "agent.toon"

            sync_agent(root, agent)
            (root / "b.md").write_text("new", encoding="utf-8")

            chk = check_agent(root, agent)
            self.assertFalse(chk.ok)
            self.assertTrue(any("sys.snapshot.file_count" in issue for issue in chk.issues))

    def test_cli_agt_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copy(ROOT / "agent.toon", root / "agent.toon")
            shutil.copy(ROOT / "SPEC.md", root / "SPEC.md")
            shutil.copy(ROOT / "EXAMPLES.md", root / "EXAMPLES.md")
            (root / "app.nv").write_text('rte str"/x" str"GET" json: rst<any, err> { rst.ok(str"ok") }', encoding="utf-8")

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

