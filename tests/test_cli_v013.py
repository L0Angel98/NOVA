from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NovaCliV016Tests(unittest.TestCase):
    def test_version_flag(self) -> None:
        proc = subprocess.run(
            ["python", "-m", "nova", "--version"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("0.1.6", proc.stdout)

    def test_run_db_sqlite_demo_interp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            proc = subprocess.run(
                [
                    "python",
                    "-m",
                    "nova",
                    "run",
                    str(ROOT / "demo" / "db_sqlite.nv"),
                    "--b",
                    "interp",
                    "--cap",
                    "db",
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("ada", proc.stdout)

    @unittest.skipUnless(shutil.which("cargo") and shutil.which("rustc"), "cargo/rustc not available")
    def test_build_hello_llvm_and_run_binary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            build = subprocess.run(
                [
                    "python",
                    "-m",
                    "nova",
                    "build",
                    str(ROOT / "demo" / "hello_llvm.nv"),
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

            suffix = ".exe" if platform.system().lower().startswith("win") else ""
            bin_path = out_dir / f"hello_llvm{suffix}"
            self.assertTrue(bin_path.exists(), f"missing binary: {bin_path}")

            run = subprocess.run([str(bin_path)], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("hello nova", run.stdout)


if __name__ == "__main__":
    unittest.main()
