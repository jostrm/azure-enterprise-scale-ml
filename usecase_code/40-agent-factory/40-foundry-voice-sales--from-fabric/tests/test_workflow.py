"""Offline workflow contracts. Fixtures never contact Azure or install packages."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
SCRIPT = ROOT / "Start-FoundryVoiceSales.ps1"


@unittest.skipUnless(PWSH, "PowerShell 7 is required for workflow integration tests")
class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ROOT / (".workflow-test-" + uuid.uuid4().hex)
        cls.fixture.mkdir()
        cls.app = cls.fixture / "template with spaces"
        cls.app.mkdir()
        if SCRIPT.exists():
            shutil.copy2(SCRIPT, cls.app)
        helpers = ROOT / "scripts" / "workflow_process.py"
        if helpers.exists():
            (cls.app / "scripts").mkdir()
            shutil.copy2(helpers, cls.app / "scripts")
        (cls.app / ".env").write_text("TEST_ONLY=true\n", encoding="utf-8")
        (cls.app / "package.json").write_text('{"type":"commonjs"}\n', encoding="utf-8")
        (cls.app / "requirements.lock.txt").write_text("", encoding="utf-8")
        (cls.app / "requirements-notebook.lock.txt").write_text("", encoding="utf-8")
        (cls.app / "sales_agent").mkdir()
        (cls.app / "sales_agent" / "__init__.py").write_text("", encoding="utf-8")
        (cls.app / "sales_agent" / "__main__.py").write_text(
            """import http.server, json, pathlib, sys
pathlib.Path("last-call.json").write_text(json.dumps(sys.argv[1:]))
if pathlib.Path("fail-start").exists() and "serve" in sys.argv: sys.exit(4)
if "serve" in sys.argv:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "ok", "application": "foundry-voice-sales"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    http.server.HTTPServer(("127.0.0.1", int(sys.argv[-1])), Handler).serve_forever()
else:
    print("FAKE_BACKEND " + json.dumps(sys.argv[1:]))
""",
            encoding="utf-8",
        )
        # A real, isolated interpreter and a fake pip module avoid network installs.
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(cls.app / ".venv")],
            check=True, capture_output=True, text=True,
        )
        (cls.app / "pip.py").write_text(
            'import json, pathlib, sys\npathlib.Path("pip-call.json").write_text(json.dumps(sys.argv[1:]))\n',
            encoding="utf-8",
        )

    @classmethod
    def tearDownClass(cls):
        if (cls.app / ".runtime" / "process.json").exists():
            cls.run_script("Stop")
        shutil.rmtree(cls.fixture)

    @classmethod
    def run_script(cls, action=None, *arguments, timeout=35):
        args = [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(cls.app / SCRIPT.name)]
        if action is not None:
            args.extend(["-Action", action])
        args.extend(arguments)
        return subprocess.run(
            args, cwd=cls.fixture, capture_output=True, text=True, timeout=timeout,
        )

    def assert_ok(self, result):
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_powershell_parses(self):
        result = subprocess.run(
            [PWSH, "-NoProfile", "-Command",
             "$e=$null; $t=$null; [System.Management.Automation.Language.Parser]::ParseFile("
             + "'" + str(SCRIPT).replace("'", "''")
             + "', [ref]$t, [ref]$e) > $null; if($e.Count){$e | Out-String; exit 1}"],
            capture_output=True, text=True,
        )
        self.assert_ok(result)

    def test_default_is_offline_check(self):
        result = self.run_script()
        self.assert_ok(result)
        self.assertIn("prerequisite", result.stdout.lower())
        self.assertNotIn("FAKE_BACKEND", result.stdout)

    def test_all_online_actions_require_explicit_consent(self):
        for action in ("Diagnose", "Connectivity", "Discover", "Text", "Smoke", "Publish", "Start"):
            with self.subTest(action=action):
                result = self.run_script(action)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("requires -AllowAzure", result.stdout + result.stderr)

    def test_validate_is_offline_and_env_path_absolute(self):
        result = self.run_script("Validate")
        self.assert_ok(result)
        args = json.loads((self.app / "last-call.json").read_text())
        self.assertEqual(["--env-file", str(self.app / ".env"), "check"], args)

    def test_setup_installs_only_locked_local_venv_dependencies(self):
        result = self.run_script("Setup", "-PythonExecutable", sys.executable)
        self.assert_ok(result)
        args = json.loads((self.app / "pip-call.json").read_text())
        self.assertEqual(["install", "-r", str(self.app / "requirements.lock.txt")], args)

    def test_setup_notebook_uses_only_optional_lock(self):
        result = self.run_script("Setup", "-Notebook", "-PythonExecutable", sys.executable)
        self.assert_ok(result)
        args = json.loads((self.app / "pip-call.json").read_text())
        self.assertEqual(["install", "-r", str(self.app / "requirements-notebook.lock.txt")], args)
        self.assertIn("no global kernel registration", result.stdout.lower())

    def test_notebook_switch_is_rejected_for_every_other_action(self):
        for action in ("Check", "Validate", "Diagnose", "Connectivity", "Discover",
                       "Publish", "Text", "Smoke", "Start", "Stop", "Test"):
            with self.subTest(action=action):
                result = self.run_script(action, "-Notebook")
                self.assertNotEqual(0, result.returncode)
                self.assertIn("-Notebook applies only to -Action Setup", result.stdout + result.stderr)

    def test_setup_notebook_missing_lock_does_not_fall_back_or_install(self):
        lock = self.app / "requirements-notebook.lock.txt"
        pip_call = self.app / "pip-call.json"
        lock.unlink()
        pip_call.unlink(missing_ok=True)
        try:
            result = self.run_script("Setup", "-Notebook", "-PythonExecutable", sys.executable)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("requirements-notebook.lock.txt is missing", result.stdout + result.stderr)
            self.assertFalse(pip_call.exists())
        finally:
            lock.write_text("", encoding="utf-8")

    def test_setup_creates_isolated_venv_without_global_changes(self):
        saved = self.app / ".venv.saved"
        (self.app / ".venv").rename(saved)
        try:
            result = self.run_script("Setup", "-PythonExecutable", sys.executable, timeout=60)
            self.assert_ok(result)
            venv_python = self.app / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            self.assertTrue(venv_python.is_file())
            self.assertEqual(
                ["install", "-r", str(self.app / "requirements.lock.txt")],
                json.loads((self.app / "pip-call.json").read_text()),
            )
        finally:
            if (self.app / ".venv").exists():
                shutil.rmtree(self.app / ".venv")
            saved.rename(self.app / ".venv")

    @unittest.skipUnless(shutil.which("node"), "Node is needed for offline UI tests")
    def test_test_action_expands_node_globs_and_runs_both_suites(self):
        tests = self.app / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_offline.py").write_text(
            "import unittest\nclass Example(unittest.TestCase):\n    def test_offline(self): self.assertTrue(True)\n",
            encoding="utf-8",
        )
        for name in ("frontend-one.test.js", "frontend-two.test.js"):
            (tests / name).write_text(
                "const test = require('node:test'); const fs = require('node:fs');"
                "test('offline', () => fs.writeFileSync("
                + json.dumps(name + ".result") + ", JSON.stringify(process.argv)));\n",
                encoding="utf-8",
            )
        result = self.run_script("Test")
        self.assert_ok(result)
        for name in ("frontend-one.test.js", "frontend-two.test.js"):
            args = json.loads((self.app / (name + ".result")).read_text())
            self.assertIn(str(tests / name), args)
            self.assertFalse(any("*" in argument for argument in args))

    def test_question_is_one_argument_not_executed(self):
        question = 'Show "sales"; $(throw "executed") & O\'Brien €?'
        result = self.run_script("Text", "-AllowAzure", "-Question", question)
        self.assert_ok(result)
        args = json.loads((self.app / "last-call.json").read_text())
        self.assertEqual(
            ["--env-file", str(self.app / ".env"), "text", "--allow-azure", "--question", question],
            args,
        )

    def test_text_and_smoke_require_question(self):
        for action in ("Text", "Smoke"):
            with self.subTest(action=action):
                result = self.run_script(action, "-AllowAzure")
                self.assertNotEqual(0, result.returncode)
                self.assertIn("-Question", result.stdout + result.stderr)

    def test_connectivity_private_option_is_forwarded(self):
        result = self.run_script("Connectivity", "-AllowAzure", "-RequirePrivate")
        self.assert_ok(result)
        args = json.loads((self.app / "last-call.json").read_text())
        self.assertEqual(["connectivity", "--allow-azure", "--require-private"], args[2:])

    def test_publish_is_separate_warned_write(self):
        result = self.run_script("Publish", "-AllowAzure")
        self.assert_ok(result)
        self.assertIn("agent version", (result.stdout + result.stderr).lower())
        self.assertEqual(
            ["publish", "--allow-azure"],
            json.loads((self.app / "last-call.json").read_text())[2:],
        )

    def test_invalid_port_rejected_before_launch(self):
        result = self.run_script("Start", "-AllowAzure", "-Port", "80")
        self.assertNotEqual(0, result.returncode)

    def test_helper_cannot_bypass_azure_opt_in(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        venv_python = self.app / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        try:
            result = subprocess.run([
                sys.executable, str(self.app / "scripts" / "workflow_process.py"), "start",
                "--root", str(self.app), "--env-file", str(self.app / ".env"),
                "--python", str(venv_python), "--port", str(port),
            ], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("--allow-azure", result.stdout + result.stderr)
        finally:
            self.assert_ok(self.run_script("Stop"))

    def test_unknown_action_rejected(self):
        self.assertNotEqual(0, self.run_script("Provision").returncode)

    def test_start_stop_and_safe_rerun(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        try:
            started = self.run_script("Start", "-AllowAzure", "-Port", str(port))
            self.assert_ok(started)
            record_path = self.app / ".runtime" / "process.json"
            record = json.loads(record_path.read_text())
            self.assertEqual(str(self.app.resolve()), record["root"])
            self.assertEqual(port, record["port"])
            self.assertIn("start_time", record)
            again = self.run_script("Start", "-AllowAzure", "-Port", str(port))
            self.assert_ok(again)
            self.assertEqual(record["pid"], json.loads(record_path.read_text())["pid"])
        finally:
            self.assert_ok(self.run_script("Stop"))
        self.assertFalse((self.app / ".runtime" / "process.json").exists())
        with socket.socket() as sock:
            sock.settimeout(1)
            self.assertNotEqual(0, sock.connect_ex(("127.0.0.1", port)))
        self.assert_ok(self.run_script("Stop"))

    def test_start_refuses_unrelated_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            port = sock.getsockname()[1]
            result = self.run_script("Start", "-AllowAzure", "-Port", str(port))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("port", (result.stdout + result.stderr).lower())
        self.assertFalse((self.app / ".runtime" / "process.json").exists())

    def test_failed_start_removes_only_owned_record(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        sentinel = self.app / "fail-start"
        sentinel.touch()
        try:
            result = self.run_script("Start", "-AllowAzure", "-Port", str(port))
            self.assertNotEqual(0, result.returncode)
            self.assertFalse((self.app / ".runtime" / "process.json").exists())
        finally:
            sentinel.unlink()

    def test_stop_rejects_recycled_or_unrelated_pid(self):
        runtime = self.app / ".runtime"
        runtime.mkdir(exist_ok=True)
        path = runtime / "process.json"
        path.write_text(json.dumps({
            "version": 1, "pid": os.getpid(), "start_time": "not-our-process",
            "root": str(self.app.resolve()), "executable": sys.executable,
            "env_file": str(self.app / ".env"), "port": 8765,
        }), encoding="utf-8")
        try:
            result = self.run_script("Stop")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("identity", (result.stdout + result.stderr).lower())
        finally:
            path.unlink(missing_ok=True)

    def test_stop_rejects_other_template_root(self):
        runtime = self.app / ".runtime"
        runtime.mkdir(exist_ok=True)
        path = runtime / "process.json"
        path.write_text(json.dumps({
            "version": 1, "pid": os.getpid(), "start_time": "ignored",
            "root": str(self.fixture), "executable": sys.executable,
            "env_file": str(self.app / ".env"), "port": 8765,
        }), encoding="utf-8")
        try:
            result = self.run_script("Stop")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("root", (result.stdout + result.stderr).lower())
        finally:
            path.unlink(missing_ok=True)


class NotebookTests(unittest.TestCase):
    def test_notebook_manifest_reuses_base_lock_and_adds_only_kernel(self):
        manifest = (ROOT / "requirements-notebook.txt").read_text(encoding="utf-8")
        self.assertEqual(["-r requirements.lock.txt", "ipykernel>=6.29,<8"], manifest.splitlines())

    def test_notebook_is_unexecuted_and_online_actions_are_guarded(self):
        notebook = json.loads((ROOT / "quickstart.ipynb").read_text(encoding="utf-8"))
        self.assertEqual(4, notebook["nbformat"])
        code = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
        self.assertIn("ALLOW_AZURE = False", code)
        self.assertIn("ALLOW_PUBLISH = False", code)
        self.assertIn("subprocess.run", code)
        self.assertNotIn("shell=True", code)
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"])
                self.assertEqual([], cell["outputs"])
                compile("".join(cell["source"]), "<notebook>", "exec")

    def test_default_run_all_cannot_call_azure_publish_or_setup(self):
        notebook = json.loads((ROOT / "quickstart.ipynb").read_text(encoding="utf-8"))
        namespace = {}
        with patch("subprocess.run") as runner, patch("pathlib.Path.cwd", return_value=ROOT), patch("shutil.which", return_value="pwsh"), patch("builtins.print"):
            for cell in notebook["cells"]:
                if cell["cell_type"] == "code":
                    exec(compile("".join(cell["source"]), "<notebook>", "exec"), namespace)
        self.assertGreater(len(runner.call_args_list), 0)
        for call in runner.call_args_list:
            command = call.args[0]
            action = command[command.index("-Action") + 1]
            self.assertIn(action, {"Check", "Validate"})
            self.assertNotIn("-AllowAzure", command)

    def test_opt_in_notebook_setup_requests_local_notebook_dependencies(self):
        notebook = json.loads((ROOT / "quickstart.ipynb").read_text(encoding="utf-8"))
        cells = {cell["id"]: cell for cell in notebook["cells"]}
        namespace = {}
        with patch("subprocess.run") as runner, patch("pathlib.Path.cwd", return_value=ROOT), patch("shutil.which", return_value="pwsh"), patch("builtins.print"):
            exec(compile("".join(cells["configuration"]["source"]), "<configuration>", "exec"), namespace)
            namespace["RUN_SETUP"] = True
            exec(compile("".join(cells["setup"]["source"]), "<setup>", "exec"), namespace)
        runner.assert_called_once()
        command = runner.call_args.args[0]
        self.assertEqual("Setup", command[command.index("-Action") + 1])
        self.assertIn("-Notebook", command)
        self.assertNotIn("-AllowAzure", command)


if __name__ == "__main__":
    unittest.main()
