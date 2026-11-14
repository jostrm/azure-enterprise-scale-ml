"""Native transport recognizing authenticated current and quiescent ancestor runs.

The original API-owned coordinator has no provider run of its own. Its unchanged
active-run check quite correctly blocks every run. A provider-owned coordinator
may exclude itself and finalized ancestors' read-only waiters, never other writers.
"""

import copy
from http.client import IncompleteRead
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request

import factory_enrollment as en
import factory_lifecycle as fl
from pipeline_lifecycle import PipelineError, canonical, require


class _ProviderTransport:
    """Provider bearer credentials never participate in ARM actor selection."""

    def _provider_request(self, kind, method, endpoint, body, allowed, *, limit, headers=None):
        require(kind in ("gha", "ado") and kind == self._provider_route["kind"],
                "pipeline-provider-route-mismatch")
        require(method in ("GET", "HEAD", "POST", "PUT", "PATCH"), "provider-method-forbidden")
        require(isinstance(endpoint, str) and not any(ord(char) < 33 for char in endpoint),
                "untrusted-provider-endpoint")
        url = "https://api.github.com/" + endpoint if kind == "gha" else endpoint
        parsed, route = urlsplit(url), urlsplit(self._provider_route["repository"])
        decoded = unquote(parsed.path)
        require(parsed.scheme == "https" and parsed.netloc == (
                    "api.github.com" if kind == "gha" else "dev.azure.com")
                and not parsed.fragment and not parsed.username and not parsed.password
                and "\\" not in decoded and not {".", ".."}.intersection(decoded.split("/"))
                and all(ord(char) >= 32 for char in unquote(url)), "untrusted-provider-endpoint")
        prefix = "/repos/" + route.path.strip("/") if kind == "gha" else "/" + unquote(route.path).strip("/").split("/")[0]
        require(decoded == prefix or decoded.startswith(prefix + "/"), "provider-repository-scope-mismatch")
        name = "GH_TOKEN" if kind == "gha" else "AIFACTORY_STATE_TOKEN"
        token = self._provider_environ.get(name, "")
        require(isinstance(token, str) and 1 <= len(token) <= 32768
                and all(33 <= ord(char) <= 126 for char in token)
                and not token.startswith("$("), "pipeline-provider-token-required-or-invalid")
        outgoing = dict(headers or {})
        require(not any(key.lower() == "authorization" for key in outgoing), "caller-authorization-forbidden")
        outgoing.update(Authorization="Bearer " + token, **{
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json" if kind == "gha" else "application/json"})
        data = body if isinstance(body, bytes) else canonical(body) if body is not None else None
        try:
            try:
                response = self.opener.open(Request(url, method=method, data=data, headers=outgoing),
                                            timeout=en.REQUEST_TIMEOUT_SECONDS)
            except HTTPError as error:
                response = error
            with response:
                status = response.status if hasattr(response, "status") else response.code
                incoming = {key.lower(): value for key, value in response.headers.items()}
                raw = response.read(limit + 1)
            require(status in allowed, "pipeline-provider-request-failed-" + str(status))
            require(len(raw) <= limit, "pipeline-provider-response-too-large")
            return status, incoming, json.loads(raw) if raw else None
        except (URLError, OSError, TimeoutError, IncompleteRead):
            raise PipelineError("pipeline-provider-request-uncertain") from None
        except (ValueError, UnicodeError) as error:
            if isinstance(error, PipelineError):
                raise
            raise PipelineError("pipeline-provider-response-invalid") from None

    def _assert_no_active_runs(self, writers):
        origin = self.origin
        require(isinstance(origin, dict) and origin.get("provider") == self._provider_route["kind"]
                and origin.get("repository") == (urlsplit(self._provider_route["repository"]).path.strip("/")
                    if origin["provider"] == "gha" else self._provider_route["repository"])
                and isinstance(origin.get("run_id"), str) and re.fullmatch(r"[1-9][0-9]*", origin["run_id"])
                and type(origin.get("attempt")) is int and origin["attempt"] == 1
                and isinstance(origin.get("commit"), str) and re.fullmatch(r"[a-f0-9]{40}", origin["commit"])
                and origin.get("ref") == self._provider_route["ref"], "authenticated-pipeline-origin-required")
        ancestors = None

        def ancestor(run_id):
            nonlocal ancestors
            if ancestors is None:
                from pipeline_ancestor_runs import quiescent_ancestors
                from provider_repository_state import ProviderState
                _, state = ProviderState(self, self._provider_route, PipelineError).read()
                ancestors = quiescent_ancestors(origin, state=state, request=self.state_request)
            return run_id in ancestors

        for writer in writers:
            if writer["kind"] == "gha":
                repository = urlsplit(writer["repository"]).path.strip("/")
                for status in ("queued", "in_progress", "waiting", "pending", "requested"):
                    _, headers, page = self.state_request("gha", "GET", "repos/" + repository
                        + "/actions/runs?per_page=100&status=" + status, None, (200,))
                    require(isinstance(page, dict) and isinstance(page.get("workflow_runs"), list)
                            and type(page.get("total_count")) is int
                            and len(page["workflow_runs"]) == page["total_count"]
                            and not any(key.lower() == "link" for key in headers), "complete-active-run-inventory-required")
                    for run in page["workflow_runs"]:
                        require(isinstance(run, dict) and self.origin["provider"] == "gha"
                                and repository == self.origin["repository"]
                                and run.get("head_sha") == self.origin["commit"]
                                and run.get("run_attempt") == self.origin["attempt"]
                                and isinstance(run.get("repository"), dict)
                                and run.get("repository", {}).get("full_name") == repository
                                and (str(run.get("id")) == self.origin["run_id"]
                                     or run.get("status") == "in_progress" and run.get("conclusion") is None
                                     and "refs/heads/" + run.get("head_branch", "") == self.origin["ref"]
                                     and ancestor(str(run.get("id")))),
                                "active-or-queued-remote-run")
            elif writer["kind"] == "ado":
                org, project, _, repository = unquote(urlsplit(writer["repository"]).path).strip("/").split("/")
                base = "https://dev.azure.com/" + quote(org) + "/" + quote(project) + "/_apis"
                _, _, repo = self.state_request("ado", "GET", base + "/git/repositories/"
                                                + quote(repository) + "?api-version=7.1", None, (200,))
                require(fl.guid(repo.get("id")), "registered-provider-repository-id-required")
                _, headers, page = self.state_request("ado", "GET", base + "/build/builds?repositoryId=" + repo["id"]
                    + "&repositoryType=TfsGit&statusFilter=inProgress,notStarted,cancelling,postponed"
                    + "&%24top=100&api-version=7.1", None, (200,))
                require(isinstance(page, dict) and isinstance(page.get("value"), list)
                        and type(page.get("count")) is int and page["count"] == len(page["value"])
                        and not any(key.lower() == "x-ms-continuationtoken" for key in headers),
                        "complete-active-run-inventory-required")
                for run in page["value"]:
                    require(isinstance(run, dict) and self.origin["provider"] == "ado"
                            and writer["repository"] == self.origin["repository"]
                            and run.get("sourceVersion") == self.origin["commit"]
                            and run.get("sourceBranch") == self.origin["ref"]
                            and isinstance(run.get("repository"), dict)
                            and run.get("repository", {}).get("id") == repo["id"]
                            and (str(run.get("id")) == self.origin["run_id"]
                                 or run.get("status") == "inProgress" and run.get("result") is None
                                 and ancestor(str(run.get("id")))), "active-or-queued-remote-run")
            else:
                require(False, "unsupported-enrolled-writer")


class PipelineCloud(_ProviderTransport, fl.Cloud):
    def __init__(self, document, origin, *, environ=None, **kwargs):
        super().__init__(document, **kwargs)
        self.origin = copy.deepcopy(origin)
        self._provider_route = document["route"]
        self._provider_environ = os.environ if environ is None else environ

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if audience.rstrip("/") not in (en.ADO_AUDIENCE, "https://app.vssps.visualstudio.com"):
            return super().request(method, url, audience, data, headers, allowed)
        return self._provider_request("ado", method, url, data, allowed, limit=fl.MAX_DOCUMENT, headers=headers)

    def state_request(self, kind, method, endpoint, body, allowed):
        require(fl.single_writer(self.document) or method in ("GET", "HEAD"), "single-writer-not-selected")
        return self._provider_request(kind, method, endpoint, body, allowed, limit=fl.STATE_RESPONSE_MAX)

    def assert_no_active_runs(self, enrollment):
        scopes = self.document["locks"]["scopes"] + self.document["locks"]["common_dependencies"]
        writers = {writer for scope in scopes for writer in enrollment["scopes"][scope.lower()]["writers"]}
        self._assert_no_active_runs([enrollment["writers"][writer] for writer in sorted(writers)])


class PipelineEnrollmentCloud(_ProviderTransport, en.Cloud):
    def __init__(self, request, origin=None, *, environ=None, **kwargs):
        super().__init__(request, **kwargs)
        self.origin = copy.deepcopy(origin)
        self._provider_route = request["route"]
        self._provider_environ = os.environ if environ is None else environ

    def gh(self, method, endpoint, body=None, allowed=(200,), limit=en.MAX_BYTES):
        require(method in ("GET", "POST") or (
            method == "PATCH" and en._single_writer(self.request_config)
            and endpoint == "repos/" + urlsplit(self._provider_route["repository"]).path.strip("/")
            + "/git/refs/heads/aifactory-state/single-writer-v1"
            and isinstance(body, dict) and body.get("force") is False), "delete-or-replacement-forbidden")
        require(not self.read_only or method == "GET", "plan-mutation-forbidden")
        return self._provider_request("gha", method, endpoint, body, allowed, limit=limit)

    def http(self, method, url, audience, data=None, headers=None, tenant=None, allowed=(200,)):
        if audience != en.ADO_AUDIENCE:
            return super().http(method, url, audience, data, headers, tenant, allowed)
        require(method in ("GET", "HEAD", "PUT", "POST"), "delete-or-replacement-forbidden")
        require(not self.read_only or method in ("GET", "HEAD"), "plan-mutation-forbidden")
        return self._provider_request("ado", method, url, data, allowed, limit=en.MAX_BYTES, headers=headers)

    def state_request(self, kind, method, endpoint, body, allowed):
        require(en._single_writer(self.request_config), "single-writer-not-selected")
        if kind == "gha":
            return self.gh(method, endpoint, body, allowed, limit=en.STATE_RESPONSE_MAX)
        require(kind == "ado" and method in ("GET", "HEAD", "POST"), "provider-method-forbidden")
        require(not self.read_only or method in ("GET", "HEAD"), "plan-mutation-forbidden")
        return self._provider_request(kind, method, endpoint, body, allowed, limit=en.STATE_RESPONSE_MAX)

    def assert_no_active_runs(self):
        self._assert_no_active_runs([self.request_config["route"]])
