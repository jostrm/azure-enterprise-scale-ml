"""Explicit, bounded outbound ticket synchronization; no automatic retry."""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)


class TicketError(ValueError):
    """A safe message suitable for returning to the API client."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


class SyncError(TicketError):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message, 502)
        self.uncertain = uncertain


def validate_origin(provider: str, value: str) -> str:
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        suffix = ".atlassian.net" if provider == "Jira" else ".service-now.com"
        allowed = {
            item.strip().lower() for item in
            os.environ.get("AIFACTORY_TICKETING_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        }
        if (
            provider not in {"Jira", "ServiceNow"} or url.scheme != "https"
            or url.port not in (None, 443) or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or any(ord(char) <= 32 for char in value) or "\\" in value
            or not (host.endswith(suffix) or host in allowed)
            or any(not label or label.startswith("-") or label.endswith("-") for label in host.split("."))
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
    except ValueError:
        raise TicketError(
            "Use an HTTPS origin on the provider's cloud domain, or an exact host allowed by "
            "AIFACTORY_TICKETING_ALLOWED_HOSTS. Paths, credentials, IPs and non-443 ports are forbidden."
        ) from None
    return "https://" + host


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, address, **kwargs):
        super().__init__(host, **kwargs)
        self.address = address

    def connect(self):
        # TLS retains the original hostname while TCP uses the validated DNS result.
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, address):
        super().__init__()
        self.address = address

    def https_open(self, req):
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(host, address=self.address, **kwargs),
            req, context=self._context,
        )


class JsonTransport:
    """Injected in tests; production disables proxies, redirects and private DNS targets."""

    def __call__(self, method, url, headers, payload=None):
        host = urlsplit(url).hostname
        try:
            addresses = sorted({
                item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            })
        except OSError:
            raise SyncError("Provider DNS lookup failed; no request was sent.") from None
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise SyncError("Provider hostname must resolve exclusively to public IP addresses.")
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if data is not None and len(data) > 256 * 1024:
            raise TicketError("Outbound ticket payload exceeds the 256 KiB limit.")
        opener = build_opener(ProxyHandler({}), _NoRedirect(), _PinnedHTTPSHandler(addresses[0]))
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with opener.open(request, timeout=20) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise SyncError("Provider response exceeded the size limit; verify the remote ticket.", uncertain=True)
                if not raw:
                    return {}
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise SyncError(
                f"Provider returned HTTP {status}; no response body or credentials are exposed.",
                uncertain=status >= 500 or 300 <= status < 400 or status in {408, 409},
            ) from None
        except (URLError, OSError, http.client.HTTPException, ValueError):
            raise SyncError(
                "Provider result is uncertain. Verify the remote ticket before further synchronization; "
                "automatic retry is disabled.", uncertain=True,
            ) from None


JIRA_STATUSES = {
    "New": ["new", "open", "to do"],
    "Active": ["active", "in progress"],
    "Solved": ["solved", "resolved", "done", "closed"],
}


def sync_plan(ticket: dict, connection: dict) -> dict:
    severity = ticket.get("severity", "blocker" if ticket["type"] == "Blocker" else "minor")
    text = (
        f"{ticket['description']}\n\nAI Factory ticket: {ticket['id']}\n"
        f"Type: {ticket['type']}\nStatus: {ticket['status']}\n"
        f"Severity: {severity}\n"
        f"Project: {ticket['project_number'] or 'Factory-wide'}\n"
        f"Resource group: {ticket.get('resource_group') or 'Unknown'}\n"
        f"Environment: {ticket.get('environment') or 'Unknown'}\n"
        f"Region: {ticket.get('region') or 'Unknown'}\n"
        f"AI Factory prefix: {ticket.get('ai_factory_prefix') or 'Unknown'}\n"
        f"AI Factory suffix: {ticket.get('ai_factory_suffix') or 'Unknown'}\n"
        f"Cost center: {ticket.get('cost_center') or 'Not specified'}\n"
        f"Department name: {ticket.get('department_name') or 'Not specified'}\n"
        "Resource-group identity is naming metadata, not deployment or access verification.\n"
        f"Requested Azure service: {ticket['requested_service'] or 'Not specified'}"
    )
    external_id = ticket.get("external_id") or ""
    if connection["provider"] == "Jira":
        fields = {
            "summary": ticket["title"],
            "description": {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            ]},
        }
        if not external_id:
            fields.update({
                "project": {"key": connection["project_key"]},
                "issuetype": {"name": "Bug" if ticket["type"] == "Bug report" else "Task"},
            })
        return {
            "method": "PUT" if external_id else "POST",
            "path": "/rest/api/3/issue" + ("/" + external_id if external_id else ""),
            "payload": {"fields": fields}, "status": ticket["status"],
            "status_mapping": JIRA_STATUSES[ticket["status"]],
            "field_mapping": "title → summary; description/type/project/requested_service/severity/resource_group/"
            "environment/region/ai_factory_prefix/ai_factory_suffix/cost_center/department_name → ADF description; "
            "severity is descriptive metadata, not a remote priority mapping. "
            "Bug report → Bug; Request Azure service/Blocker → Task. "
            "Status uses GET issue/{id}/transitions, then POST the matching workflow transition; "
            "unsupported workflow states fail explicitly.",
        }
    payload = {
        "short_description": ticket["title"], "description": text,
        "state": {"New": "1", "Active": "2", "Solved": "6"}[ticket["status"]],
        "category": "inquiry" if ticket["type"] == "Request Azure service" else "software",
        "correlation_id": ticket["id"],
    }
    if ticket["status"] == "Solved":
        payload.update({"close_code": "Solution provided", "close_notes": "Marked Solved in AI Factory ticketing."})
    return {
        "method": "PATCH" if external_id else "POST",
        "path": "/api/now/table/incident" + ("/" + external_id if external_id else ""),
        "payload": payload, "status": ticket["status"],
        "field_mapping": "title → short_description; description/type/project/requested_service/severity/resource_group/"
        "environment/region/ai_factory_prefix/ai_factory_suffix/cost_center/department_name → description; "
        "severity is descriptive metadata, not a remote priority mapping. "
        "New/Active/Solved → incident state 1/2/6. Requests → inquiry incident (not a catalog order); "
        "Bug report/Blocker → software incident; local ID → correlation_id.",
    }


class TicketConnector:
    def __init__(self, transport=None):
        self.transport = transport or JsonTransport()

    def send(self, connection, ticket, plan, credential, on_created):
        base = validate_origin(connection["provider"], connection["base_url"])
        if connection["provider"] == "Jira" or connection["username"]:
            authorization = "Basic " + base64.b64encode(
                (connection["username"] + ":" + credential).encode("utf-8")
            ).decode("ascii")
        else:
            authorization = "Bearer " + credential
        headers = {"Authorization": authorization, "Content-Type": "application/json", "Accept": "application/json"}
        result = self.transport(plan["method"], base + plan["path"], headers, plan["payload"])
        external_id = ticket.get("external_id") or ""
        if not external_id:
            if connection["provider"] == "Jira":
                external_id = result.get("key", "")
                valid = isinstance(external_id, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", external_id)
                if valid and external_id.rsplit("-", 1)[0] != connection["project_key"]:
                    valid = False
                external_url = base + "/browse/" + external_id if valid else ""
            else:
                item = result.get("result") or {}
                external_id = item.get("sys_id", "") if isinstance(item, dict) else ""
                valid = isinstance(external_id, str) and re.fullmatch(r"[a-fA-F0-9]{32}", external_id)
                external_url = base + "/nav_to.do?uri=incident.do%3Fsys_id%3D" + external_id if valid else ""
            if not valid:
                raise SyncError("Provider did not return a valid ticket ID. Verify remotely; no automatic retry.", uncertain=True)
            on_created(external_id, external_url)
        if connection["provider"] == "ServiceNow":
            incident = result.get("result")
            if (
                not isinstance(incident, dict) or incident.get("sys_id") != external_id
                or str(incident.get("state")) != plan["payload"]["state"]
            ):
                raise SyncError(
                    "Remote incident ID retained, but ServiceNow did not confirm the requested state. "
                    "Verify the incident and its mandatory fields before previewing another update."
                )
        if connection["provider"] == "Jira":
            path = base + "/rest/api/3/issue/" + external_id
            current = self.transport("GET", path + "?fields=status", headers)
            fields = current.get("fields")
            status_object = fields.get("status") if isinstance(fields, dict) else None
            status = status_object.get("name", "") if isinstance(status_object, dict) else ""
            if str(status).casefold() not in plan["status_mapping"]:
                transitions = self.transport("GET", path + "/transitions", headers).get("transitions", [])
                if not isinstance(transitions, list) or len(transitions) > 500:
                    raise SyncError("Remote issue ID saved, but the Jira workflow response was invalid.")
                transition = next((
                    item for item in transitions if isinstance(item, dict)
                    and isinstance(item.get("to"), dict)
                    and str(item["to"].get("name", "")).casefold() in plan["status_mapping"]
                    and re.fullmatch(r"\d+", str(item.get("id", "")))
                ), None)
                if not transition:
                    raise SyncError(
                        "Remote issue ID saved, but the requested Jira status has no available workflow transition. "
                        "Adjust the workflow/status and preview again."
                    )
                self.transport("POST", path + "/transitions", headers, {"transition": {"id": str(transition["id"])}})
        return external_id
