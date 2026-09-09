"""Offline region-report contracts and preflight regression tests (mock az only)."""
from __future__ import annotations

from contextlib import redirect_stderr
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "environment_setup/aifactory/bicep/scripts"
TEMPLATES = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
SPEC = importlib.util.spec_from_file_location("region_report", SCRIPTS / "region_report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)
SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
OTHER_SUB = "33333333-3333-4333-8333-333333333333"


class RegionReportsTests(unittest.TestCase):
    def setUp(self):
        self.work = ROOT / f".test-region-reports-{uuid4().hex}"
        self.work.mkdir()
        self.addCleanup(shutil.rmtree, self.work)
        self.env = {
            "AIFACTORY_REPORT_REGION": "eastus2",
            "AIFACTORY_REPORT_SUBSCRIPTION_ID": SUB,
            "AIFACTORY_REPORT_TENANT_ID": TENANT,
            "AIFACTORY_REPORT_ENVIRONMENT": "dev",
            "AIFACTORY_REPORT_JOB": "services-infra",
            "AIFACTORY_REPORT_DIR": str(self.work / "reports"),
            "AIFACTORY_REPORT_JOB_STATUS": "Failed",
            "AIFACTORY_REPORT_RUN_ID": "123",
        }
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_exact_shape_and_actual_utc_timestamp(self):
        before = datetime.now(timezone.utc)
        payload = REPORT.report([REPORT.pipeline_observation("Failed")])
        observed = datetime.fromisoformat(payload["observed_at"].replace("Z", "+00:00"))
        self.assertLessEqual(before.replace(microsecond=0), observed)
        self.assertLessEqual(observed, datetime.now(timezone.utc))
        self.assertEqual(set(payload), {
            "schema_version", "region", "subscription_id", "tenant_id", "environment",
            "source", "run_id", "run_url", "observed_at", "observations",
        })
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["source"], "pipeline_artifact")
        self.assertEqual(payload["subscription_id"], SUB)
        self.assertEqual(payload["tenant_id"], TENANT)
        self.assertEqual(set(payload["observations"][0]), {
            "check_id", "kind", "service", "sku", "status", "message",
        })

    def test_pipeline_status_and_same_job_clear_without_capacity_claims(self):
        for source, expected in {
            "Failed": "failed", "failure": "failed", "Succeeded": "passed", "success": "passed",
            "SucceededWithIssues": "unknown", "Canceled": "unknown", "cancelled": "unknown",
            "skipped": "unknown", "": "unknown",
        }.items():
            with self.subTest(source=source):
                item = REPORT.pipeline_observation(source)
                self.assertEqual(item["status"], expected)
                self.assertEqual(item["kind"], "pipeline_error")
                self.assertEqual(item["sku"], None)
                self.assertEqual(item["check_id"], "pipeline-job:services-infra")
        os.environ["AIFACTORY_REPORT_JOB"] = "networking"
        self.assertEqual(REPORT.pipeline_observation("success")["check_id"], "pipeline-job:networking")

    def test_environment_mapping_and_missing_identifiers(self):
        self.assertEqual(REPORT.report([], environment="test")["environment"], "stage")
        for field, bad in [
            ("AIFACTORY_REPORT_REGION", ""), ("AIFACTORY_REPORT_REGION", "$(admin_location)"),
            ("AIFACTORY_REPORT_REGION", "unknown"), ("AIFACTORY_REPORT_REGION", "../eastus2"),
            ("AIFACTORY_REPORT_SUBSCRIPTION_ID", "<todo>"), ("AIFACTORY_REPORT_TENANT_ID", ""),
            ("AIFACTORY_REPORT_ENVIRONMENT", "staging"),
        ]:
            with self.subTest(field=field, bad=bad), patch.dict(os.environ, {field: bad}):
                output = io.StringIO()
                with redirect_stderr(output):
                    self.assertEqual(REPORT.main(["pipeline"]), 0)
                self.assertIn("no report written", output.getvalue())
                self.assertFalse(list(self.work.rglob("*.json")))

    def test_search_discovery_and_quota_are_independent(self):
        missing = REPORT.finding_observation("WARN", "SEARCH_SKU_UNAVAILABLE", "standard2")
        quota = REPORT.finding_observation("PASS", "SEARCH_QUOTA_HEADROOM", "standard2")
        self.assertEqual((missing["check_id"], missing["kind"], missing["sku"], missing["status"]),
                         ("search_sku_availability", "capacity", "standard2", "failed"))
        self.assertEqual(missing["service"], "microsoft.search/searchservices")
        self.assertIn("not a live allocation probe", missing["message"])
        self.assertEqual((quota["check_id"], quota["kind"], quota["sku"], quota["status"]),
                         ("search_sku_quota", "quota", "standard2", "passed"))
        available = REPORT.finding_observation("PASS", "SEARCH_SKU_AVAILABLE", "standard2")
        self.assertEqual(available["check_id"], "search_sku_availability")
        self.assertEqual(available["status"], "passed")
        self.assertNotEqual(available["check_id"], "search_sku_capacity")
        self.assertEqual(REPORT.finding_observation("WARN", "SEARCH_QUOTA_LOOKUP", "basic")["status"], "unknown")
        self.assertEqual(REPORT.finding_observation("FAIL", "SEARCH_QUOTA_AT_LIMIT", "basic")["status"], "failed")

    def test_warn_only_and_skipped_preflight_cannot_hide_findings(self):
        stream = "\0".join(["", "", "FAIL", "SEARCH_QUOTA_AT_LIMIT", "password=secret", "basic"]) + "\0"
        payload = REPORT.preflight_reports(stream, completed=True)[0]
        self.assertEqual([o["status"] for o in payload["observations"]], ["failed", "failed"])
        self.assertNotIn("secret", json.dumps(payload))
        skipped = REPORT.preflight_reports("", completed=False)[0]
        self.assertEqual([o["status"] for o in skipped["observations"]], ["unknown"])

    def test_subscription_findings_are_not_assigned_to_other_targets(self):
        os.environ["PF_REPORT_TARGETS"] = f"dev|{SUB}\nprod|{OTHER_SUB}"
        stream = "\0".join(["dev", SUB, "FAIL", "SEARCH_QUOTA_AT_LIMIT", "exhausted", "basic"]) + "\0"
        reports = REPORT.preflight_reports(stream, completed=True)
        self.assertEqual(len(reports[0]["observations"]), 2)
        self.assertEqual(len(reports[1]["observations"]), 1)
        self.assertEqual(reports[1]["subscription_id"], OTHER_SUB)

    def test_invalid_target_does_not_drop_a_valid_subscription_report(self):
        os.environ["PF_REPORT_TARGETS"] = f"dev|{SUB}\nprod|<invalid>"
        with redirect_stderr(io.StringIO()):
            reports = REPORT.preflight_reports("", completed=True)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["subscription_id"], SUB)

    def test_strict_warning_failure_is_failed_without_promoting_unknown_quota(self):
        os.environ["PF_REPORT_EXIT_CODE"] = "2"
        stream = "\0".join(["", "", "WARN", "SEARCH_QUOTA_UNVALIDATED", "unvalidated", "basic"]) + "\0"
        items = REPORT.preflight_reports(stream, completed=True)[0]["observations"]
        self.assertEqual(items[0]["status"], "failed")
        self.assertEqual(items[1]["status"], "unknown")

    def test_no_environment_secrets_or_raw_messages_in_reports(self):
        os.environ["PASSWORD"] = "super-private-password"
        os.environ["AZURE_CREDENTIALS"] = '{"clientSecret":"super-private-secret"}'
        os.environ["AIFACTORY_REPORT_RUN_URL"] = "https://example.test/run/12?sig=private-token"
        stream = "\0".join(["", "", "FAIL", "CONFIG_MANDATORY_UNSET",
                            "PASSWORD=super-private-password; Token=private-token", ""]) + "\0"
        serialized = json.dumps(REPORT.preflight_reports(stream, completed=True)[0])
        for secret in ["super-private", "private-token", "clientSecret"]:
            self.assertNotIn(secret, serialized)
        self.assertIn("CONFIG_MANDATORY_UNSET", serialized)

    def test_run_urls_and_nullable_run_metadata(self):
        os.environ.pop("AIFACTORY_REPORT_RUN_ID")
        self.assertIsNone(REPORT.report([])["run_id"])
        self.assertIsNone(REPORT.report([])["run_url"])
        with patch.dict(os.environ, {
            "SYSTEM_COLLECTIONURI": "https://dev.azure.com/org/",
            "SYSTEM_TEAMPROJECT": "my project", "BUILD_BUILDID": "123",
        }):
            self.assertEqual(REPORT.report([])["run_url"],
                             "https://dev.azure.com/org/my%20project/_build/results?buildId=123")
        with patch.dict(os.environ, {
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "org/repo", "GITHUB_RUN_ID": "456",
        }):
            self.assertEqual(REPORT.report([])["run_url"], "https://github.com/org/repo/actions/runs/456")
        for url in ("https://example.test/run/12", "https://github.com/org/repo/issues/1",
                    "https://dev.azure.com/org/project/_build/results?sig=secret"):
            with patch.dict(os.environ, {"AIFACTORY_REPORT_RUN_URL": url}):
                self.assertIsNone(REPORT.report([])["run_url"])

    def test_import_contract_identifier_and_size_limits(self):
        os.environ["AIFACTORY_REPORT_JOB"] = "a" * 180
        first = REPORT.pipeline_observation("success")["check_id"]
        self.assertLessEqual(len(first), 128)
        self.assertEqual(first, REPORT.pipeline_observation("success")["check_id"])
        os.environ["AIFACTORY_REPORT_JOB"] = "a" * 179 + "b"
        self.assertNotEqual(first, REPORT.pipeline_observation("success")["check_id"])
        with self.assertRaises(ValueError):
            REPORT.report([REPORT.pipeline_observation("success")] * 201)
        with self.assertRaises(ValueError):
            REPORT.write_report(self.work / "oversized", "oversized", {"payload": "a" * REPORT.MAX_INPUT})
        self.assertFalse(list((self.work / "oversized").glob("*.json")))

    def test_only_explicit_tested_search_sku_and_known_capacity_codes(self):
        path = self.work / "command-error.json"
        for code, count in {
            "SkuNotAvailable": 1, "InsufficientCapacity": 1, "AllocationFailed": 1,
            "QuotaExceeded": 0, "DeploymentFailed": 0, "Unauthorized": 0, "NotFound": 0,
        }.items():
            with self.subTest(code=code):
                path.write_text(json.dumps({
                    "service": "Azure AI Search", "sku": "standard",
                    "error": {"code": "DeploymentFailed", "details": [{"code": code, "message": "secret=do-not-copy"}]},
                }), encoding="utf-8")
                items = REPORT.capacity_observations(path)
                self.assertEqual(len(items), count)
                if count:
                    self.assertEqual(items[0]["sku"], "standard")
                    self.assertEqual(items[0]["check_id"], "search_sku_capacity")
                    self.assertEqual(items[0]["service"], "microsoft.search/searchservices")
                    self.assertNotIn("do-not-copy", json.dumps(items))
        path.write_text('{"service":"Azure Storage","sku":"standard","error":{"code":"SkuNotAvailable"}}',
                        encoding="utf-8")
        self.assertEqual(REPORT.capacity_observations(path), [])

    def test_cli_persists_json_and_retains_generic_failure_on_invalid_error_file(self):
        path = self.work / "bad-error.json"
        path.write_text("not JSON", encoding="utf-8")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(REPORT.main(["pipeline", "--command-error-file", str(path)]), 0)
        files = list((self.work / "reports").glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text())["observations"][0]["status"], "failed")
        self.assertFalse(list(self.work.rglob("*.pending")))


class PipelineTemplateTests(unittest.TestCase):
    def test_always_reports_are_last_and_paths_are_job_unique(self):
        import yaml

        for name in ("infra-project.yml", "infra-project-phase.yml", "infra-common.yml"):
            data = yaml.safe_load((TEMPLATES / "github-actions" / name).read_text(encoding="utf-8"))
            for job_name, job in data["jobs"].items():
                if "steps" not in job:
                    continue
                with self.subTest(file=name, job=job_name):
                    self.assertNotIn("runner.temp", str(job.get("env", {})))
                    writer, upload = job["steps"][-2:]
                    self.assertEqual(writer["if"], "always()")
                    self.assertTrue(writer["continue-on-error"])
                    self.assertEqual(writer["env"]["AIFACTORY_REPORT_JOB_STATUS"], "${{ job.status }}")
                    self.assertEqual(upload["if"], "always()")
                    self.assertEqual(upload["uses"], "actions/upload-artifact@v4")
                    self.assertEqual(upload["with"]["path"], writer["env"]["AIFACTORY_REPORT_DIR"] + "/*.json")
                    self.assertIn("${{ github.run_attempt }}", upload["with"]["name"])
                    self.assertEqual(job["steps"][0]["uses"], "actions/checkout@v4")
                    for step in job["steps"]:
                        if "PREFLIGHT_REPORT_DIR" in step.get("env", {}):
                            self.assertEqual(step["env"]["PREFLIGHT_REPORT_DIR"], writer["env"]["AIFACTORY_REPORT_DIR"])

        ado = TEMPLATES / "azure-devops/esml-yaml-pipelines"
        shared_path = ado / "esml-infra-common/jobs/region-report-steps.yaml"
        shared = yaml.safe_load(shared_path.read_text())
        self.assertEqual(shared["steps"][0]["condition"], "always()")
        self.assertIn("always()", shared["steps"][1]["condition"])
        self.assertEqual(shared["steps"][1]["task"], "PublishPipelineArtifact@1")
        for name in ("esml-infra-common/jobs/job-1-aif-cmn.yaml",
                     "esml-infra-project/jobs/job-1-genai-networking.yaml",
                     "esml-infra-project/jobs/job-2-genai-services.yaml"):
            path = ado / name
            steps = yaml.safe_load(path.read_text(encoding="utf-8"))["steps"]
            self.assertEqual((path.parent / steps[-1]["template"]).resolve(), shared_path.resolve())
            preflight = next(s for s in steps if "preflight.sh" in s.get("inputs", {}).get("scriptPath", ""))
            self.assertIn("$(System.JobId)-$(System.JobAttempt)", preflight["env"]["PREFLIGHT_REPORT_DIR"])
            self.assertEqual(preflight["env"]["AIFACTORY_REPORT_TENANT_ID"], "$(tenantId)")


class PreflightShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        cls.bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("Bash is not installed")

    def setUp(self):
        self.work = ROOT / f".test-preflight-report-{uuid4().hex}"
        self.work.mkdir()
        self.addCleanup(shutil.rmtree, self.work)
        self.mock = self.work / "mock-commands.sh"
        self.mock.write_text(r'''az() {
  printf '%s\n' "$*" >> "$PF_TEST_AZ_CALLS"
  case "$1 $2" in
    "account show"|"account set") return 0 ;;
    "policy assignment") printf '[]' ;;
    "provider show")
      case "$*" in
        *registrationState*) printf 'Registered' ;;
        *) printf '{"registrationState":"Registered","resourceTypes":[{"resourceType":"searchServices","locations":["East US 2"]}]}' ;;
      esac ;;
    "rest --method") printf '%s' "$PF_TEST_SEARCH_JSON" ;;
    *) echo "Unexpected mock Azure call" >&2; return 99 ;;
  esac
}
python3() { "$PF_TEST_PYTHON" "$@"; }
export -f az python3
if command -v cygpath >/dev/null; then export TMPDIR="$(cygpath -u "$PF_TEST_ROOT")"; else export TMPDIR="$PF_TEST_ROOT"; fi
''', encoding="utf-8", newline="\n")

    def run_preflight(self, *args, search_json=None, enabled=True, report_directory=None):
        env = os.environ.copy()
        env.update({
            "BASH_ENV": str(self.mock), "PF_TEST_ROOT": str(self.work),
            "PF_TEST_AZ_CALLS": str(self.work / "az-calls.txt"),
            "PF_TEST_PYTHON": sys.executable,
            "PF_TEST_SEARCH_JSON": search_json or json.dumps({"value": [{"name": {"value": "basic"}, "limit": 1, "currentValue": 1}]}),
            "AIFACTORY_REPORT_TENANT_ID": TENANT, "AIFACTORY_REPORT_JOB": "services-infra",
            "ENABLE_AI_FOUNDRY": "false", "ENABLE_AI_SEARCH": "true", "ADMIN_AI_SEARCH_TIER": "basic",
            "PREFLIGHT_AZ_RETRIES": "1",
        })
        report_directory = report_directory or self.work / "reports"
        if enabled:
            env["PREFLIGHT_REPORT_DIR"] = str(report_directory)
        else:
            env.pop("PREFLIGHT_REPORT_DIR", None)
        result = subprocess.run(
            [self.bash, str(SCRIPTS / "preflight.sh"), "--root", str(self.work),
             "--environment", "dev", "--subscription", SUB, "--location", "eastus2", *args],
            cwd=self.work, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        files = list(report_directory.glob("*.json")) if enabled else []
        reports = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        return result, reports

    def test_warn_only_and_hard_failure_keep_original_exits(self):
        for flag, expected in (("--warn-only", 0), ("--no-warn-only", 1)):
            with self.subTest(flag=flag):
                result, reports = self.run_preflight(flag)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertEqual(len(reports), 1, result.stderr)
                quota = next(o for o in reports[0]["observations"] if o["check_id"] == "search_sku_quota")
                self.assertEqual(quota["status"], "failed")
                self.assertEqual(quota["sku"], "basic")

    def test_missing_sku_warning_strict_exit_and_single_sku_record(self):
        result, reports = self.run_preflight("--strict", search_json='{"value":[]}')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(reports[0]["observations"][0]["status"], "failed")
        items = [o for o in reports[0]["observations"] if o["kind"] == "capacity"]
        self.assertEqual([(o["sku"], o["status"]) for o in items], [("basic", "failed")])

    def test_quota_pass_does_not_publish_capacity_pass(self):
        result, reports = self.run_preflight(search_json='{"value":[{"name":{"value":"basic"},"limit":16,"currentValue":1}]}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(o["check_id"] == "search_sku_capacity" for o in reports[0]["observations"]))
        self.assertTrue(any(o["check_id"] == "search_sku_availability" and o["status"] == "passed"
                            for o in reports[0]["observations"]))
        self.assertTrue(any(o["check_id"] == "search_sku_quota" and o["status"] == "passed"
                            for o in reports[0]["observations"]))

    def test_malformed_search_usage_is_unknown_not_capacity_failure(self):
        result, reports = self.run_preflight(search_json='{"unexpected":"response"}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(o["kind"] == "capacity" for o in reports[0]["observations"]))
        self.assertTrue(any(o["check_id"] == "search_sku_quota" and o["status"] == "unknown"
                            for o in reports[0]["observations"]))

    def test_skip_is_unknown_and_never_calls_azure(self):
        result, reports = self.run_preflight("--skip")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([o["status"] for o in reports[0]["observations"]], ["unknown"])
        self.assertFalse((self.work / "az-calls.txt").exists())

    def test_reporting_is_optional(self):
        result, reports = self.run_preflight("--skip", enabled=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(reports, [])
        self.assertFalse((self.work / "reports").exists())

    def test_output_path_is_data_not_shell_code(self):
        result, reports = self.run_preflight("--skip", report_directory=self.work / "reports; touch should-not-exist")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(reports), 1)
        self.assertFalse((self.work / "should-not-exist").exists())

    def test_report_write_failure_does_not_change_preflight_failure(self):
        blocker = self.work / "not-a-directory"
        blocker.write_text("existing file", encoding="utf-8")
        result, reports = self.run_preflight("--no-warn-only", report_directory=blocker)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(reports, [])
        self.assertEqual(blocker.read_text(), "existing file")
        self.assertIn("no report written", result.stderr)

    def run_pipeline_report(self, status, directory, **overrides):
        env = os.environ.copy()
        env.update({
            "BASH_ENV": str(self.mock), "PF_TEST_ROOT": str(self.work),
            "PF_TEST_PYTHON": sys.executable, "PF_TEST_AZ_CALLS": str(self.work / "az-calls.txt"),
            "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*",
            "AIFACTORY_REPORT_REGION": "", "AIFACTORY_REPORT_SUBSCRIPTION_ID": "",
            "AIFACTORY_REPORT_TENANT_ID": "", "AIFACTORY_REPORT_ENVIRONMENT": "",
            "admin_location": "eastus2", "dev_test_prod_sub_id": SUB,
            "tenantId": TENANT, "dev_test_prod": "dev",
            "AIFACTORY_REPORT_JOB": "deploy-project-infra",
            "AIFACTORY_REPORT_JOB_STATUS": status, "AIFACTORY_REPORT_DIR": str(directory),
        })
        env.update(overrides)
        return subprocess.run(
            [self.bash, str(SCRIPTS / "write-pipeline-region-report.sh")],
            cwd=self.work, env=env, capture_output=True, text=True, timeout=30,
        )

    def test_preflight_report_with_disabled_msys_conversion_preserves_exit_status(self):
        with patch.dict(os.environ, {"MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}):
            for option, expected in (("--warn-only", 0), ("--no-warn-only", 1)):
                with self.subTest(option=option):
                    result, reports = self.run_preflight(
                        option, report_directory=self.work / f"native reports {expected}",
                    )
                    self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
                    self.assertEqual(1, len(reports), result.stdout + result.stderr)
                    self.assertNotIn("can't open file", result.stderr)
                    self.assertNotIn("preflight report unavailable", result.stderr)
                    self.assertEqual(reports[0]["observations"][0]["status"], "failed")

    def test_pipeline_wrapper_with_disabled_msys_path_conversion(self):
        for status, expected in (("success", "passed"), ("failure", "failed"), ("cancelled", "unknown")):
            with self.subTest(status=status):
                directory = self.work / f"reports with spaces {status}"
                result = self.run_pipeline_report(status, directory)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stderr, "")
                files = list(directory.glob("*.json"))
                self.assertEqual(len(files), 1, result.stdout + result.stderr)
                payload = json.loads(files[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["region"], "eastus2")
                self.assertEqual(payload["subscription_id"], SUB)
                self.assertEqual(payload["tenant_id"], TENANT)
                self.assertEqual(payload["environment"], "dev")
                self.assertEqual(payload["observations"][0]["status"], expected)
                self.assertEqual(payload["observations"][0]["check_id"], "pipeline-job:deploy-project-infra")
        self.assertFalse((self.work / "az-calls.txt").exists())

    def test_pipeline_wrapper_report_errors_are_visible_and_best_effort(self):
        directory = self.work / "invalid-metadata"
        result = self.run_pipeline_report("success", directory, dev_test_prod_sub_id="<invalid>")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no report written", result.stderr)
        self.assertFalse(directory.exists())

        blocker = self.work / "not-a-directory"
        blocker.write_text("existing file", encoding="utf-8")
        result = self.run_pipeline_report("failure", blocker)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no report written", result.stderr)
        self.assertEqual(blocker.read_text(encoding="utf-8"), "existing file")
        self.assertFalse(list(self.work.rglob("*.json")))
        self.assertFalse((self.work / "az-calls.txt").exists())

    def test_pipeline_wrapper_and_ado_artifact_detection_without_cloud_access(self):
        import yaml

        env = os.environ.copy()
        env.update({
            "BASH_ENV": str(self.mock), "PF_TEST_ROOT": str(self.work),
            "PF_TEST_PYTHON": sys.executable, "PF_TEST_AZ_CALLS": str(self.work / "az-calls.txt"),
            "AIFACTORY_REPORT_REGION": "eastus2", "AIFACTORY_REPORT_SUBSCRIPTION_ID": SUB,
            "AIFACTORY_REPORT_TENANT_ID": TENANT, "AIFACTORY_REPORT_ENVIRONMENT": "dev",
            "AIFACTORY_REPORT_JOB_STATUS": "Failed", "AIFACTORY_REPORT_DIR": str(self.work / "reports"),
            "SYSTEM_DEFAULTWORKINGDIRECTORY": str(ROOT.parent),
        })
        template = TEMPLATES / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/region-report-steps.yaml"
        script = yaml.safe_load(template.read_text())["steps"][0]["inputs"]["script"]
        result = subprocess.run([self.bash, "-c", script],
                                cwd=self.work, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("variable=aifactoryRegionReportReady]true", result.stdout)
        files = list((self.work / "reports").glob("*.json"))
        self.assertEqual(len(files), 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(files[0].read_text())["observations"][0]["status"], "failed")
        self.assertFalse((self.work / "az-calls.txt").exists())


if __name__ == "__main__":
    unittest.main()
