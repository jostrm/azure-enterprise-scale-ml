"""Offline presentation tests; never run deployment/bootstrap operations."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = ROOT / "bootstrap"
LIBRARY = BOOTSTRAP / "ui/terminal.sh"
SCRIPTS = sorted(BOOTSTRAP.glob("*.sh"))
START = ROOT / "00-start.sh"


class TestBootstrapTerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.name == "nt":
            bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
            cls.bash = str(bash) if bash.is_file() else None
        else:
            cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("Bash is required for bootstrap presentation tests.")

    def run_bash(self, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = {
            key: value for key, value in os.environ.items()
            if key not in {"NO_COLOR", "AIF_COLOR", "AIF_THEME", "COLUMNS", "BASH_ENV"}
        }
        environment.update({"TERM": "xterm-256color", "AIF_TEST_LIBRARY": LIBRARY.as_posix()})
        environment.update(env or {})
        return subprocess.run(
            [self.bash, "--noprofile", "--norc", "-s"],
            input=script, env=environment, capture_output=True, text=True, timeout=30, check=False,
        )

    def render(self, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.run_bash(
            'set -euo pipefail\nsource "$AIF_TEST_LIBRARY"\n'
            'aif_banner "LAUNCH CONTROL" "Build with intent."\n'
            'aif_section "01 / Configuration"\n'
            'aif_step "01/03" "Prepare templates"\n'
            'aif_info "Connecting"\naif_warn "Review changes"\n'
            'aif_error "Action blocked"\naif_value "Project" "017"\n'
            'aif_detail "Configuration preserved"\naif_complete "Ready"\n',
            env,
        )

    def test_all_bootstrap_scripts_parse_as_bash_and_use_the_shared_theme(self) -> None:
        for path in [*SCRIPTS, START, LIBRARY]:
            with self.subTest(script=path.name):
                text = path.read_text(encoding="utf-8")
                result = subprocess.run(
                    [self.bash, "--noprofile", "--norc", "-n"],
                    input=text, text=True, capture_output=True, timeout=30, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(text.startswith("#!/"), path.name)
                if path != LIBRARY:
                    self.assertIn("source ", text)
                    self.assertIn("aif_banner ", text)
                    for line in text.splitlines():
                        if not line.lstrip().startswith("#"):
                            self.assertNotRegex(line, r"\$\{(?:GREEN|YELLOW|RED|NC)\}")

    def test_matrix_and_blue_have_distinct_bold_high_intensity_palettes(self) -> None:
        for theme, accent in (("matrix", "\x1b[1;92m"), ("blue", "\x1b[1;94m")):
            with self.subTest(theme=theme):
                result = self.render({"AIF_COLOR": "always", "AIF_THEME": theme})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(accent, result.stdout)
                self.assertIn("\x1b[1;96m", result.stdout)
                self.assertIn("\x1b[1;91m", result.stdout)
                self.assertIn("\x1b[1;93m", result.stdout)
                self.assertIn("A I   F A C T O R Y", result.stdout)
                self.assertTrue(result.stdout.endswith("\x1b[0m\n\n"))

    def test_plain_output_for_redirects_no_color_and_dumb_terminals(self) -> None:
        for env in ({}, {"TERM": "dumb"}, {"AIF_COLOR": "never"},
                    {"NO_COLOR": "1", "AIF_COLOR": "always"}):
            with self.subTest(env=env):
                result = self.render(env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertNotIn("\x1b", result.stdout)
                for badge in ("[INFO]", "[WARN]", "[ERROR]", "[OK]", "[01/03]"):
                    self.assertIn(badge, result.stdout)

    def test_log_messages_are_literal_and_machine_streams_unchanged(self) -> None:
        value = r'C:\new\repo\test $(printf INJECTED) `echo INJECTED` %s'
        result = self.run_bash(
            'source "$AIF_TEST_LIBRARY"\n'
            'aif_info "$AIF_TEST_TEXT" >&2\n'
            "printf '%s' '{\"id\":17}'\n",
            {"AIF_TEST_TEXT": value, "AIF_COLOR": "always"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('{"id":17}', result.stdout)
        self.assertIn(value, result.stderr)

    def test_sourcing_does_not_change_shell_flags_traps_or_echo(self) -> None:
        result = self.run_bash(
            'set -eu\ntrap ":" EXIT\nbefore_flags="$-"\nbefore_trap="$(trap -p EXIT)"\n'
            'source "$AIF_TEST_LIBRARY"\n'
            '[[ "$before_flags" == "$-" && "$before_trap" == "$(trap -p EXIT)" ]]\n'
            '[[ "$(type -t echo)" == builtin ]]\n'
            '[[ "$(type -t printf)" == builtin ]]\n',
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)

    def test_section_width_is_bounded_and_accepts_leading_zeroes(self) -> None:
        for columns in ("12", "080", "999", "garbage"):
            with self.subTest(columns=columns):
                result = self.render({"COLUMNS": columns})
                self.assertEqual(0, result.returncode, result.stderr)
                lines = [line for line in result.stdout.splitlines() if re.fullmatch(r"  -+", line)]
                self.assertTrue(lines)
                self.assertTrue(all(22 <= len(line) <= 86 for line in lines))

    def test_prompt_keeps_piped_input_and_secret_read_semantics(self) -> None:
        result = self.run_bash(
            'source "$AIF_TEST_LIBRARY"\n'
            'read -r -s -p "$(aif_prompt "Token: ")" token <<< \'literal\\secret\'\n'
            '[[ "$token" == \'literal\\secret\' ]]\n',
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)
        self.assertNotIn("secret", result.stderr)

    def test_human_report_filter_preserves_upstream_failure(self) -> None:
        result = self.run_bash(
            'set -euo pipefail\nsource "$AIF_TEST_LIBRARY"\n'
            '(printf "report\\nlast line"; exit 7) | aif_stream\n',
        )
        self.assertEqual(7, result.returncode)
        self.assertIn("report\n", result.stdout)
        self.assertIn("last line\n", result.stdout)

    def test_theme_resolution_in_original_copied_and_stable_launcher_layouts(self) -> None:
        for script in SCRIPTS:
            text = script.read_text(encoding="utf-8")
            is_launcher = "-update-aifactory-" in script.name
            end = text.index("\nreadonly REPO_ROOT") if is_launcher else text.index("\naif_banner ")
            loader = text[:end] + '\naif_info "Theme loaded"\n'
            for layout in ("original", "copied", "stable"):
                with self.subTest(script=script.name, layout=layout), tempfile.TemporaryDirectory() as tmp:
                    directory = Path(tmp)
                    lib = directory / (
                        "azure-enterprise-scale-ml/bootstrap/ui/terminal.sh"
                        if layout == "copied" else "ui/terminal.sh"
                    )
                    lib.parent.mkdir(parents=True)
                    shutil.copyfile(LIBRARY, lib)
                    entry = directory / script.name
                    entry.write_text(loader, encoding="utf-8", newline="\n")
                    result = self.run_bash('source "$AIF_TEST_SCRIPT"\n', {"AIF_TEST_SCRIPT": entry.as_posix()})
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("[INFO] Theme loaded", result.stdout)
            if is_launcher:
                self.assertIn('cp "$AIF_UI_LIBRARY" "$state_dir/ui/terminal.sh"', text)
                self.assertLess(text.index('cp "$AIF_UI_LIBRARY"'), text.index('exec bash "$stable_launcher"'))

    def test_initial_submodule_loader_works_without_theme_dependency(self) -> None:
        text = (BOOTSTRAP / "00-aif-add-submodule.sh").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "00-aif-add-submodule.sh"
            entry.write_text(text[:text.index("\nfunction try")] + "\n", encoding="utf-8", newline="\n")
            result = self.run_bash('source "$AIF_TEST_SCRIPT"\n', {"AIF_TEST_SCRIPT": entry.as_posix()})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("plain-text bootstrap", result.stderr)
        self.assertIn("SUBMODULE SETUP", result.stdout)

    def test_start_choices_and_copy_destinations_with_mocked_side_effects(self) -> None:
        # Only cp/rm would mutate in 00-start; stub both before sourcing the actual entrypoint.
        for choice, expected in (("a", "02-ADO-YAML-bootstrap-files.sh"), ("g", "02-GH-bootstrap-files.sh"), ("x", None)):
            with self.subTest(choice=choice):
                result = self.run_bash(
                    'cp() { printf "COPY:%s\\n" "$*" >&2; }\n'
                    'rm() { printf "REMOVE:%s\\n" "$*" >&2; }\n'
                    'source "$AIF_TEST_SCRIPT" <<< "$AIF_TEST_CHOICE"\n',
                    {"AIF_TEST_SCRIPT": START.as_posix(), "AIF_TEST_CHOICE": choice},
                )
                self.assertIn("LAUNCH CONTROL", result.stdout)
                self.assertIn("[a]", result.stdout)
                self.assertIn("[g]", result.stdout)
                if expected:
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn(expected, result.stderr)
                else:
                    self.assertEqual(1, result.returncode)
                    self.assertIn("[ERROR]", result.stdout)


if __name__ == "__main__":
    unittest.main()
