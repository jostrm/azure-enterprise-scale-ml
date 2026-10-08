"""Read health and an empty local catalog; never prepare or start an operation."""

import getpass
import json
from pathlib import Path
import sys
import tempfile


def main():
    accelerator = Path(input("Accelerator source folder: ").strip()).expanduser().resolve()
    sdk_source = accelerator / "environment_setup" / "azurefactory-cli" / "src"
    if not (sdk_source / "azurefactory" / "client.py").is_file():
        raise SystemExit("The selected folder does not contain the Factory SDK.")
    sys.path.insert(0, str(sdk_source))
    from azurefactory import AzureFactoryClient

    url = input("Local demo API URL [http://127.0.0.1:8876]: ").strip() or "http://127.0.0.1:8876"
    key = getpass.getpass("Local demo API key: ")
    if not key:
        raise SystemExit("An API key is required.")
    client = AzureFactoryClient(base_url=url, api_key=key)
    print(json.dumps(client.health(), indent=2))

    folder = Path(tempfile.mkdtemp(prefix="factory-smoke-")) / "azurefactory"
    folder.mkdir()
    print(f"Empty local demo folder: {folder}")
    print(json.dumps(client.catalog_list(str(folder)), indent=2))


if __name__ == "__main__":
    main()
