"""Approval authority from the provider, never from a caller's review JSON."""

import os
import re
from urllib.parse import quote, unquote, urlsplit

from pipeline_lifecycle import require
from pipeline_approvals import ENVIRONMENT as REVIEW_ENVIRONMENT, audience


class ProtectedJobReview:
    def __init__(self, cloud, route, *, environ=None):
        self.cloud, self.route = cloud, route
        self.environ = os.environ if environ is None else environ

    def get(self, endpoint):
        _, headers, body = self.cloud.state_request(self.route["kind"], "GET", endpoint, None, (200,))
        require(not any(key.lower() in ("link", "x-ms-continuationtoken") for key in headers),
                "complete-provider-review-evidence-required")
        return body

    def origin(self, snapshot):
        env = self.environ
        if self.route["kind"] == "gha":
            repository = urlsplit(self.route["repository"]).path.strip("/")
            require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY") == repository
                    and re.fullmatch(r"[1-9][0-9]*", env.get("GITHUB_RUN_ID", "")), "authenticated-provider-job-required")
            run = self.get("repos/" + repository + "/actions/runs/" + env["GITHUB_RUN_ID"])
            require(str(run.get("id")) == env["GITHUB_RUN_ID"] and run.get("head_sha") == env.get("GITHUB_SHA")
                    and run.get("repository", {}).get("full_name") == repository
                    and run.get("event") == "workflow_dispatch"
                    and str(run.get("run_attempt")) == env.get("GITHUB_RUN_ATTEMPT"),
                    "provider-job-binding-mismatch")
            require(run["run_attempt"] == 1, "provider-rerun-requires-new-review")
            require(re.fullmatch(r"[a-f0-9]{40}", run["head_sha"])
                    and env.get("GITHUB_REF", "").startswith("refs/"), "exact-provider-source-required")
            return {"provider": "gha", "repository": repository, "run_id": env["GITHUB_RUN_ID"],
                    "attempt": run["run_attempt"], "commit": run["head_sha"], "ref": env["GITHUB_REF"]}
        org, project, _, _ = unquote(urlsplit(self.route["repository"]).path).strip("/").split("/")
        run_id = env.get("BUILD_BUILDID", "")
        require(env.get("TF_BUILD", "").lower() == "true" and re.fullmatch(r"[1-9][0-9]*", run_id),
                "authenticated-provider-job-required")
        base = "https://dev.azure.com/" + quote(org) + "/" + quote(project)
        run = self.get(base + "/_apis/build/builds/" + run_id + "?api-version=7.1")
        require(str(run.get("id")) == run_id and run.get("sourceVersion") == env.get("BUILD_SOURCEVERSION")
                and run.get("sourceBranch") == env.get("BUILD_SOURCEBRANCH")
                and run.get("repository", {}).get("url", "").lower() == self.route["repository"].lower(),
                "provider-job-binding-mismatch")
        return {"provider": "ado", "repository": self.route["repository"], "run_id": run_id,
                "attempt": 1, "commit": run["sourceVersion"], "ref": run["sourceBranch"]}

    def verify(self, record):
        current = self.origin(record["snapshot"] if "snapshot" in record else {})
        require(current == record["plan"].get("origin"), "provider-review-origin-changed")
        from pipeline_approvals import verify_review
        return verify_review(record, environ=self.environ)

    def verify_finalizer(self, record):
        require(self.origin(record["snapshot"]) == record["plan"].get("origin"),
                "provider-finalizer-origin-changed")
        from pipeline_approvals import verify_finalizer
        return verify_finalizer(record, environ=self.environ)
