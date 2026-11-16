"""Exercise the Windows entrypoints using cmd.exe and isolated Python runtimes.

These tests never install project dependencies or start the application. They
must run on Windows; text inspection cannot validate cmd.exe quoting behavior.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "requires Windows cmd.exe")
class WindowsEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_directory = tempfile.TemporaryDirectory()
        cls.runtime = Path(cls.runtime_directory.name) / "python"
        venv.EnvBuilder(with_pip=False).create(cls.runtime)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runtime_directory.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "Numarator İş & (test)!"
        self.root.mkdir()
        self.caller = Path(self.temporary.name) / "caller"
        self.caller.mkdir()
        self.result = self.root / "arguments.json"
        for name in ("start-local.bat", "start-prod.bat"):
            shutil.copyfile(ROOT / name, self.root / name)
        (self.root / "launcher.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['NUMARATOR_TEST_RESULT']).write_text(\n"
            "    json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(),\n"
            "                'python': sys.executable}),\n"
            "    encoding='utf-8',\n"
            ")\n"
            "sys.exit(int(os.environ.get('NUMARATOR_TEST_EXIT', '0')))\n",
            encoding="utf-8",
        )

    def install_local_python(self) -> None:
        shutil.copytree(self.runtime, self.root / "backend" / ".venv")

    def run_entrypoint(
        self, name: str, *arguments: str, exit_code: int = 0, path: str = "",
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        environment.update(
            PATH=path,
            NUMARATOR_TEST_RESULT=str(self.result),
            NUMARATOR_TEST_EXIT=str(exit_code),
        )
        environment.update(extra_environment or {})
        # A command string is intentional: cmd.exe has different quoting rules
        # from the MS C runtime used by subprocess's Windows argument builder.
        quoted_arguments = " ".join(f'"{argument}"' for argument in arguments)
        command = (
            f'"{os.environ["COMSPEC"]}" /d /v:off /s /c '
            f'""{self.root / name}" {quoted_arguments}"'
        )
        return subprocess.run(
            command,
            cwd=self.caller,
            env=environment,
            input="\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_entrypoints_anchor_root_and_preserve_quoted_arguments(self) -> None:
        self.install_local_python()
        marker = r"C:\İş & (veri)!\dosya ^ adı.pem"
        for name, environment in (
            ("start-local.bat", "development"),
            ("start-prod.bat", "production"),
        ):
            with self.subTest(name=name):
                completed = self.run_entrypoint(
                    name, "--configure", "--marker", marker,
                    path=str(self.runtime / "Scripts"),
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                received = json.loads(self.result.read_text(encoding="utf-8"))
                self.assertEqual(
                    received["argv"],
                    [
                        "quickstart", "--environment", environment,
                        "--configure", "--marker", marker,
                    ],
                )
                self.assertEqual(Path(received["cwd"]), self.root)
                self.assertEqual(
                    Path(received["python"]),
                    self.root / "backend" / ".venv" / "Scripts" / "python.exe",
                )
                self.assertNotIn("Press any key", completed.stdout)

    def test_entrypoints_preserve_failure_code_and_pause(self) -> None:
        self.install_local_python()
        for name in ("start-local.bat", "start-prod.bat"):
            with self.subTest(name=name):
                completed = self.run_entrypoint(name, "--prepare", exit_code=23)
                self.assertEqual(completed.returncode, 23, completed.stdout + completed.stderr)
                self.assertIn("Press any key", completed.stdout)
                self.assertEqual(
                    json.loads(self.result.read_text(encoding="utf-8"))["argv"][-1],
                    "--prepare",
                )

    def test_entrypoints_fall_back_to_python_on_path(self) -> None:
        for name in ("start-local.bat", "start-prod.bat"):
            with self.subTest(name=name):
                completed = self.run_entrypoint(name, path=str(self.runtime / "Scripts"))
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                received = json.loads(self.result.read_text(encoding="utf-8"))
                self.assertEqual(
                    Path(received["python"]), self.runtime / "Scripts" / "python.exe"
                )

    def test_entrypoints_reject_unsupported_virtual_environment_python(self) -> None:
        self.install_local_python()
        hooks = self.root / "hooks"
        hooks.mkdir()
        (hooks / "sitecustomize.py").write_text(
            "import os, sys\n"
            "if os.path.normcase(sys.executable) == os.path.normcase(\n"
            "    os.environ['NUMARATOR_TEST_OLD_PYTHON']\n"
            "):\n"
            "    sys.version_info = (3, 10, 0)\n",
            encoding="utf-8",
        )
        environment = {
            "PYTHONPATH": str(hooks),
            "NUMARATOR_TEST_OLD_PYTHON": str(
                self.root / "backend" / ".venv" / "Scripts" / "python.exe"
            ),
        }
        for name in ("start-local.bat", "start-prod.bat"):
            with self.subTest(name=name):
                completed = self.run_entrypoint(
                    name, path=str(self.runtime / "Scripts"), extra_environment=environment
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                received = json.loads(self.result.read_text(encoding="utf-8"))
                self.assertEqual(
                    Path(received["python"]), self.runtime / "Scripts" / "python.exe"
                )

    def test_entrypoints_explain_missing_python_and_return_failure(self) -> None:
        for name in ("start-local.bat", "start-prod.bat"):
            with self.subTest(name=name):
                completed = self.run_entrypoint(name)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("Python 3.11+", completed.stdout)
                self.assertIn("Press any key", completed.stdout)
                self.assertFalse(self.result.exists())


if __name__ == "__main__":
    unittest.main()
