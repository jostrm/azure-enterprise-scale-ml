import io
import json
import subprocess


TENANT = "d06d9bae-d2c3-48a1-a76f-05221564d208"
TOKEN = "test-access-token"


def token_result(argv, *, tenant=TENANT, token=TOKEN, **overrides):
    document = {
        "accessToken": token,
        "subscription": argv[argv.index("--subscription") + 1],
        "tenant": tenant,
        "tokenType": "Bearer",
    }
    return subprocess.CompletedProcess(argv, 0, json.dumps(document | overrides), "")


def tables(*rows):
    columns = list(rows[0]) if rows else []
    return {"tables": [{
        "name": "PrimaryResult",
        "columns": [{"name": name} for name in columns],
        "rows": [[row.get(name) for name in columns] for row in rows],
    }]}


class TelemetryResponse(io.BytesIO):
    def __init__(self, request, payload, *, status=200, url=None):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
        self.status = status
        self.url = request.full_url if url is None else url
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)
