"""Authenticated native approval evidence for the fixed Pipelines-only copies.

Request JSON and binding files cannot supply consent. The provider's immutable
workflow copy, run, task/job, protection settings and review history are checked.
GitHub additionally requires a fresh, operation-specific, RS256-verified OIDC JWT.
All network boundaries are injectable; this module never changes provider state.
"""
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener
from uuid import UUID

from pipeline_dispatch import DispatchError, ProviderTransport, _NoRedirect


ENVIRONMENT = "esaf-pipelines-execute"
ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = ISSUER + "/.well-known/jwks"
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
MAX_BYTES = 256 * 1024


class ApprovalError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise ApprovalError(code)


def audience(record):
    return "api://azurefactory/pipelines-lifecycle/" + record["operation_id"] + "/" + record["plan_hash"]


def finalizer_audience(record):
    return "api://azurefactory/pipelines-lifecycle-finalize/" + record["operation_id"] + "/" + record["plan_hash"]


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate-approval-evidence-key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ApprovalError("invalid-json-number")))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ApprovalError):
            raise
        raise ApprovalError("invalid-approval-json") from None


def _b64(value):
    require(isinstance(value, str) and 0 < len(value) <= 32768
            and re.fullmatch(r"[A-Za-z0-9_-]+", value), "invalid-jwt-encoding")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        raise ApprovalError("invalid-jwt-encoding") from None


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "timezone-required-in-review-evidence")
        return parsed.timestamp()
    except (ValueError, TypeError, AttributeError):
        raise ApprovalError("invalid-review-timestamp") from None


def _uuid(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def verify_github_jwt(token, jwks, expected_audience, *, clock=time.time):
    """Verify issuer keys with the existing cryptography package, not JWT decoding."""
    require(isinstance(token, str) and len(token) <= 32768, "bounded-oidc-token-required")
    parts = token.split(".")
    require(len(parts) == 3, "invalid-provider-jwt")
    header = _json(_b64(parts[0]))
    claims = _json(_b64(parts[1]))
    require(isinstance(header, dict) and isinstance(claims, dict)
            and header.get("alg") == "RS256" and header.get("typ", "JWT") == "JWT"
            and not any(key in header for key in ("jku", "jwk", "x5u", "crit")),
            "trusted-rs256-jwt-required")
    require(isinstance(jwks, dict) and isinstance(jwks.get("keys"), list)
            and len(jwks["keys"]) <= 32, "bounded-issuer-jwks-required")
    keys = [key for key in jwks["keys"] if key.get("kid") == header.get("kid")
            and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
            and key.get("alg", "RS256") == "RS256"]
    require(isinstance(header.get("kid"), str) and len(keys) == 1, "unique-issuer-signing-key-required")
    n, e = int.from_bytes(_b64(keys[0]["n"]), "big"), int.from_bytes(_b64(keys[0]["e"]), "big")
    require(2048 <= n.bit_length() <= 8192 and 3 <= e < 2**32 and e % 2, "invalid-issuer-rsa-key")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        raise ApprovalError("cryptography-package-required-for-oidc-verification") from None
    try:
        rsa.RSAPublicNumbers(e, n).public_key().verify(
            _b64(parts[2]), (parts[0] + "." + parts[1]).encode("ascii"),
            padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, InvalidSignature):
        raise ApprovalError("provider-oidc-signature-invalid") from None
    now = clock()
    require(claims.get("iss") == ISSUER and claims.get("aud") == expected_audience
            and all(type(claims.get(key)) is int for key in ("iat", "nbf", "exp"))
            and now - 600 <= claims["iat"] <= now + 60 and claims["nbf"] <= now + 60
            and now < claims["exp"] <= claims["iat"] + 600, "provider-oidc-time-or-audience-invalid")
    return claims


class GitHubOIDC:
    def __init__(self, environ=None, *, opener=None):
        self.environ = os.environ if environ is None else environ
        self.opener = opener or build_opener(_NoRedirect())

    def _get(self, url, headers):
        try:
            with self.opener.open(Request(url, headers=headers), timeout=30) as response:
                require(response.status == 200, "oidc-provider-response-invalid")
                raw = response.read(MAX_BYTES + 1)
            require(len(raw) <= MAX_BYTES, "oidc-provider-response-too-large")
            return _json(raw)
        except ApprovalError:
            raise
        except Exception:
            # HTTP error bodies/redirect URLs may contain credentials. Never echo them.
            raise ApprovalError("oidc-provider-fetch-failed") from None

    def token(self, requested_audience):
        token = self.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        parsed = urlsplit(self.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", ""))
        require(token and parsed.scheme == "https"
                and re.fullmatch(r"[a-z0-9-]+\.actions\.githubusercontent\.com", parsed.hostname or "")
                and not parsed.username and not parsed.password and parsed.port in (None, 443)
                and not parsed.fragment and "/_apis/distributedtask/hubs/build/plans/" in parsed.path,
                "authenticated-github-oidc-endpoint-required")
        query = [(key, value) for key, value in parse_qsl(parsed.query) if key != "audience"]
        query.append(("audience", requested_audience))
        value = self._get(urlunsplit(parsed._replace(query=urlencode(query))),
                          {"Authorization": "Bearer " + token, "Accept": "application/json"})
        require(isinstance(value, dict) and isinstance(value.get("value"), str), "provider-oidc-token-required")
        return value["value"]

    def jwks(self):
        return self._get(JWKS_URL, {"Accept": "application/json"})


class _Review:
    def __init__(self, record, transport, oidc, environ, clock):
        self.record, self.env, self.clock = record, environ, clock
        self.origin = record["plan"]["origin"]
        self.provider = self.origin["provider"]
        require(self.provider in ("gha", "ado") and type(self.origin.get("attempt")) is int
                and self.origin["attempt"] == 1
                and re.fullmatch(r"[1-9][0-9]*", str(self.origin.get("run_id", "")))
                and re.fullmatch(r"[a-f0-9]{40}", self.origin.get("commit", ""))
                and re.fullmatch(r"refs/(heads|tags)/[A-Za-z0-9_./-]+", self.origin.get("ref", ""))
                and _uuid(record["operation_id"]) and re.fullmatch(r"[a-f0-9]{64}", record["plan_hash"]),
                "immutable-provider-review-origin-required")
        self.run_id = str(self.origin["run_id"])
        self.prepared = _time(record["prepared_at"])
        require(self.prepared <= clock() + 60, "prepared-operation-from-future")
        repository = self.origin["repository"]
        if self.provider == "gha":
            require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository),
                    "github-repository-required")
            self.base = "https://api.github.com/repos/" + repository
            transport_base = self.base
        else:
            parsed = urlsplit(repository)
            parts = unquote(parsed.path).strip("/").split("/")
            require(parsed.scheme == "https" and parsed.netloc == "dev.azure.com"
                    and len(parts) == 4 and parts[2] == "_git"
                    and all(part not in ("", ".", "..") for part in parts)
                    and not parsed.query and not parsed.fragment, "ado-repository-required")
            transport_base = "https://dev.azure.com/" + quote(parts[0], safe="")
            self.base = transport_base + "/" + quote(parts[1], safe="") + "/_apis"
            self.tasks_base = transport_base + "/_apis/distributedtask/tasks/"
        self.transport = transport or ProviderTransport(self.provider, transport_base)
        self.oidc = oidc or GitHubOIDC(environ)

    def get(self, url):
        status, headers, body = self.transport.request("GET", url)
        require(status == 200, "authenticated-provider-evidence-required")
        return {key.lower(): value for key, value in headers.items()}, body

    def single(self, url):
        headers, body = self.get(url)
        require('rel="next"' not in headers.get("link", "")
                and not headers.get("x-ms-continuationtoken"), "complete-review-evidence-required")
        return body

    def pages(self, url, key):
        rows = []
        for page in range(1, 11):
            headers, body = self.get(url + ("&" if "?" in url else "?") + f"per_page=100&page={page}")
            require(isinstance(body, dict) and isinstance(body.get(key), list), "provider-review-page-invalid")
            rows.extend(body[key])
            if 'rel="next"' not in headers.get("link", ""):
                return rows
        raise ApprovalError("provider-review-pagination-limit")

    def trusted_copy(self, content):
        require(isinstance(content, bytes) and len(content) <= MAX_BYTES, "bounded-installed-template-required")
        published = (TEMPLATES / f"pipelines-only-{self.provider}.yml").read_bytes()
        # Git text normalization may change CRLF only; no workflow customization
        # can silently change the approval task or its dependency relationship.
        require(content.replace(b"\r\n", b"\n") == published.replace(b"\r\n", b"\n"),
                "reviewed-provider-template-mismatch")
        self.template_digest = hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()

    def proof(self, **evidence):
        return {**self.origin, "operation_id": self.record["operation_id"],
                "plan_hash": self.record["plan_hash"], "environment": ENVIRONMENT,
                "workflow_sha256": self.template_digest, **evidence}

    def gha(self, *, finalize=False):
        origin, env = self.origin, self.env
        require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_JOB") == ("finalize" if finalize else "execute")
                and env.get("GITHUB_REPOSITORY") == origin["repository"]
                and env.get("GITHUB_RUN_ID") == self.run_id and env.get("GITHUB_RUN_ATTEMPT") == "1"
                and env.get("GITHUB_SHA") == origin["commit"] and env.get("GITHUB_REF") == origin["ref"],
                "github-current-job-mismatch")
        run = self.single(self.base + "/actions/runs/" + self.run_id)
        require(str(run.get("id")) == self.run_id and run.get("run_attempt") == 1
                and run.get("head_sha") == origin["commit"] and run.get("event") == "workflow_dispatch"
                and run.get("status") == "in_progress"
                and run.get("path") == ".github/workflows/pipelines-only-gha.yml"
                and run.get("repository", {}).get("full_name") == origin["repository"],
                "github-native-run-mismatch")
        source = self.single(self.base + "/contents/.github/workflows/pipelines-only-gha.yml?ref=" + origin["commit"])
        require(source.get("encoding") == "base64", "provider-workflow-content-required")
        self.trusted_copy(base64.b64decode("".join(source["content"].split()), validate=True))
        protection = self.single(self.base + "/environments/" + ENVIRONMENT)
        rules = [rule for rule in protection.get("protection_rules", []) if rule.get("type") == "required_reviewers"]
        require(protection.get("name") == ENVIRONMENT and type(protection.get("id")) is int
                and protection.get("can_admins_bypass") is False and len(rules) == 1
                and rules[0].get("prevent_self_review") is True and rules[0].get("reviewers"),
                "required-native-environment-review-missing")
        reviews = self.single(self.base + "/actions/runs/" + self.run_id + "/approvals")
        require(isinstance(reviews, list), "native-github-review-required")
        relevant = [row for row in reviews if any(
            item.get("id") == protection["id"] and item.get("name") == ENVIRONMENT
            for item in row.get("environments", []))]
        require(relevant and all(row.get("state") == "approved" for row in relevant)
                and all(type(row.get("user", {}).get("id")) is int
                        and row["user"]["id"] != run.get("actor", {}).get("id") for row in relevant),
                "native-github-review-required")
        jobs = self.pages(self.base + "/actions/runs/" + self.run_id + "/jobs?filter=latest", "jobs")
        prepare = [job for job in jobs if job.get("name") == "prepare"]
        expected_job = f"Execute reviewed {self.record['operation_id']} / {self.record['plan_hash']}"
        execute = [job for job in jobs if job.get("name") == expected_job]
        require(len(prepare) == len(execute) == 1, "exact-prepared-operation-jobs-required")
        finalizers = [job for job in jobs if job.get("name") ==
                      f"Finalize reviewed {self.record['operation_id']} / {self.record['plan_hash']}"] if finalize else []
        require(not finalize or len(finalizers) == 1, "exact-finalizer-job-required")
        for job in prepare + execute + finalizers:
            require(str(job.get("run_id")) == self.run_id and job.get("run_attempt") == 1
                    and job.get("head_sha") == origin["commit"], "review-job-source-or-attempt-mismatch")
        prepare, execute = prepare[0], execute[0]
        require(prepare.get("status") == "completed" and prepare.get("conclusion") == "success"
                and _time(prepare.get("started_at")) <= self.prepared <= _time(prepare.get("completed_at"))
                and _time(execute.get("started_at")) >= _time(prepare.get("completed_at"))
                and {"self-hosted", "linux", "esaf-lifecycle-external"} <= set(execute.get("labels", [])),
                "approval-not-after-prepared-operation")
        current_job = finalizers[0] if finalize else execute
        if finalize:
            require(execute.get("status") == "completed"
                    and execute.get("conclusion") in ("success", "failure", "cancelled", "timed_out")
                    and _time(current_job.get("started_at")) >= _time(execute.get("completed_at")),
                    "mutating-job-not-terminal-before-finalizer")
        require(current_job.get("status") == "in_progress"
                and {"self-hosted", "linux", "esaf-lifecycle-external"} <= set(current_job.get("labels", [])),
                "authenticated-current-provider-job-required")
        requested_audience = finalizer_audience(self.record) if finalize else audience(self.record)
        claims = verify_github_jwt(self.oidc.token(requested_audience), self.oidc.jwks(),
                                   requested_audience, clock=self.clock)
        expected = {"repository": origin["repository"], "repository_id": str(run["repository"]["id"]),
                    "sha": origin["commit"], "ref": origin["ref"], "run_id": self.run_id, "run_attempt": "1",
                    "environment": ENVIRONMENT, "sub": "repo:" + origin["repository"] + ":environment:" + ENVIRONMENT,
                    "workflow_ref": origin["repository"] + "/.github/workflows/pipelines-only-gha.yml@" + origin["ref"],
                    "workflow_sha": origin["commit"], "actor_id": str(run["actor"]["id"]),
                    "runner_environment": "self-hosted"}
        require(all(claims.get(key) == value for key, value in expected.items())
                and claims["iat"] >= self.prepared - 60, "signed-oidc-job-binding-mismatch")
        evidence = {"reviewers": sorted({row["user"]["id"] for row in relevant}), "job_id": current_job["id"],
                    "proof_kind": "github-rs256-native-finalizer" if finalize else "github-rs256-native-environment-review"}
        if finalize:
            evidence.update(execution_job_id=execute["id"], execution_result=execute["conclusion"],
                            execution_completed_at=execute["completed_at"])
        return self.proof(**evidence)

    def ado(self, *, finalize=False):
        origin, env = self.origin, self.env
        require(env.get("TF_BUILD", "").lower() == "true" and env.get("BUILD_BUILDID") == self.run_id
                and env.get("BUILD_SOURCEVERSION") == origin["commit"]
                and env.get("BUILD_SOURCEBRANCH") == origin["ref"]
                and env.get("SYSTEM_JOBATTEMPT") == env.get("SYSTEM_STAGEATTEMPT") == "1"
                and all(_uuid(env.get(key)) for key in ("SYSTEM_JOBID", "SYSTEM_STAGEID",
                                                       "SYSTEM_PLANID", "SYSTEM_TIMELINEID")),
                "ado-current-job-mismatch")
        run = self.single(self.base + "/build/builds/" + self.run_id + "?api-version=7.1")
        require(str(run.get("id")) == self.run_id and run.get("sourceVersion") == origin["commit"]
                and run.get("sourceBranch") == origin["ref"] and run.get("status") == "inProgress"
                and run.get("orchestrationPlan", {}).get("planId") == env["SYSTEM_PLANID"]
                and str(run.get("definition", {}).get("id")) == env.get("SYSTEM_DEFINITIONID")
                and run.get("repository", {}).get("url", "").lower() == origin["repository"].lower()
                and run.get("repository", {}).get("type") == "TfsGit", "ado-native-run-mismatch")
        definition = run["definition"]
        require(type(definition.get("revision")) is int and _uuid(run["repository"].get("id")),
                "immutable-ado-definition-required")
        installed = self.single(self.base + f"/build/definitions/{definition['id']}?revision={definition['revision']}&api-version=7.1")
        require(installed.get("id") == definition["id"] and installed.get("revision") == definition["revision"]
                and installed.get("repository", {}).get("id") == run["repository"]["id"]
                and installed.get("process", {}).get("yamlFilename", "").lstrip("/") == "pipelines-only-ado.yml",
                "ado-installed-pipeline-mismatch")
        source = self.single(self.base + "/git/repositories/" + run["repository"]["id"]
                             + "/items?path=%2Fpipelines-only-ado.yml&versionDescriptor.versionType=commit"
                             + "&versionDescriptor.version=" + origin["commit"]
                             + "&includeContent=true&%24format=json&api-version=7.1")
        self.trusted_copy(source["content"].encode("utf-8"))
        timeline = self.single(self.base + "/build/builds/" + self.run_id + "/timeline?api-version=7.1")
        require(timeline.get("id") == env["SYSTEM_TIMELINEID"] and isinstance(timeline.get("records"), list),
                "ado-exact-build-timeline-required")
        rows = timeline["records"]
        by_id = {row["id"]: row for row in rows}
        require(len(by_id) == len(rows), "ado-ambiguous-timeline")
        def stage(row):
            seen = set()
            while row.get("parentId"):
                require(row["id"] not in seen and row["parentId"] in by_id, "ado-invalid-job-ancestry")
                seen.add(row["id"])
                row = by_id[row["parentId"]]
            require(row.get("type") == "Stage" and row.get("attempt") == 1
                    and not row.get("previousAttempts"), "ado-reviewed-stage-rerun")
            return row
        tasks = [row for row in rows if row.get("type") == "Task" and row.get("name") == "ReviewPipelinesLifecycle"]
        prepared_jobs = [row for row in rows if row.get("type") == "Job"
                         and row.get("identifier") == "PrepareOperation"]
        require(len(tasks) == len(prepared_jobs) == 1 and env["SYSTEM_JOBID"] in by_id,
                "ado-exact-native-review-task-required")
        task, prepare, current_job = tasks[0], prepared_jobs[0], by_id[env["SYSTEM_JOBID"]]
        execute_jobs = [row for row in rows if row.get("type") == "Job"
                        and row.get("identifier") == "ExecuteReviewedOperation"]
        require(len(execute_jobs) == 1, "ado-exact-mutating-job-required")
        execute = execute_jobs[0]
        review_job = by_id.get(task.get("parentId"), {})
        for row in (task, prepare, execute, review_job, current_job):
            require(row.get("attempt") == 1 and not row.get("previousAttempts"), "ado-review-rerun-forbidden")
        require(review_job.get("type") == "Job" and review_job.get("identifier") == "ReviewPipelinesLifecycle"
                and review_job.get("name") == f"Review {self.record['operation_id']} / {self.record['plan_hash']}"
                and review_job.get("workerName") in (None, "", "Server")
                and review_job.get("state") == "completed" and review_job.get("result") == "succeeded"
                and stage(review_job).get("name") == "Review", "ado-native-server-review-job-required")
        require(execute.get("type") == "Job" and execute.get("identifier") == "ExecuteReviewedOperation"
                and stage(execute).get("name") == "Execute", "ado-native-mutating-job-required")
        expected_job = "FinalizeReviewedOperation" if finalize else "ExecuteReviewedOperation"
        expected_stage = "Finalize" if finalize else "Execute"
        require(current_job.get("type") == "Job" and current_job.get("identifier") == expected_job
                and current_job.get("state") == "inProgress" and stage(current_job).get("name") == expected_stage
                and stage(current_job)["id"] == env["SYSTEM_STAGEID"], "ado-current-provider-job-required")
        if finalize:
            require(execute.get("state") == "completed"
                    and execute.get("result") in ("succeeded", "failed", "canceled", "abandoned", "succeededWithIssues")
                    and _time(current_job.get("startTime")) >= _time(execute.get("finishTime")),
                    "mutating-job-not-terminal-before-finalizer")
        require(prepare.get("state") == "completed" and prepare.get("result") == "succeeded"
                and stage(prepare).get("name") == "Prepare"
                and _time(prepare.get("startTime")) <= self.prepared <= _time(prepare.get("finishTime"))
                and task.get("state") == "completed" and task.get("result") == "succeeded"
                and _time(task.get("startTime")) >= _time(prepare.get("finishTime"))
                and self.prepared <= _time(task.get("finishTime")) <= _time(execute.get("startTime")),
                "ado-review-not-after-prepared-operation")
        native = task.get("task", {})
        require(_uuid(native.get("id")) and native.get("name") == "ManualValidation"
                and re.fullmatch(r"1\.\d+\.\d+", native.get("version", "")),
                "ado-manual-validation-v1-task-required")
        catalog = self.single(self.tasks_base + native["id"] + "?api-version=7.1-preview.1")
        definitions = catalog.get("value", []) if isinstance(catalog, dict) and "value" in catalog else [catalog]
        matches = [item for item in definitions if item.get("id") == native["id"]
                   and item.get("name") == "ManualValidation" and item.get("serverOwned") is True
                   and item.get("runsOn") == ["Server"]
                   and ".".join(str(item.get("version", {}).get(key)) for key in ("major", "minor", "patch"))
                   == native["version"]]
        require(len(matches) == 1, "ado-provider-owned-manual-validation-required")
        evidence = {"job_id": current_job["id"], "review_task_id": task["id"], "native_task_id": native["id"],
                    "review_completed_at": task["finishTime"],
                    "proof_kind": "ado-native-server-finalizer" if finalize else "ado-native-server-manual-validation"}
        if finalize:
            evidence.update(execution_job_id=execute["id"], execution_result=execute["result"],
                            execution_completed_at=execute["finishTime"])
        return self.proof(**evidence)


def verify_review(record, *, transport=None, oidc=None, environ=None, clock=time.time):
    """Return proof only from authenticated provider observations; never consent JSON."""
    try:
        verifier = _Review(record, transport, oidc, os.environ if environ is None else environ, clock)
        return verifier.gha() if verifier.provider == "gha" else verifier.ado()
    except ApprovalError:
        raise
    except (DispatchError, KeyError, TypeError, ValueError, OSError):
        raise ApprovalError("incomplete-or-invalid-native-approval-evidence") from None


def verify_finalizer(record, *, transport=None, oidc=None, environ=None, clock=time.time):
    """Attest the same-run finalizer and terminal mutator, not the enclosing run.

    This does not claim that Azure effects or child workers are complete. The
    lifecycle runtime must freshly observe those before releasing admission.
    """
    try:
        verifier = _Review(record, transport, oidc, os.environ if environ is None else environ, clock)
        return verifier.gha(finalize=True) if verifier.provider == "gha" else verifier.ado(finalize=True)
    except ApprovalError:
        raise
    except (DispatchError, KeyError, TypeError, ValueError, OSError):
        raise ApprovalError("incomplete-or-invalid-native-finalizer-evidence") from None
