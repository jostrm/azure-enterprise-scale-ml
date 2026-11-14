# Upload own documents to the project's data storage (uploaded_documents in data-sources.json)
#
# Entra ID only (DefaultAzureCredential): no storage keys or SAS. The signed-in identity needs
# "Storage Blob Data Contributor" on the account, and the private endpoint must be reachable
# (AI Factory VPN, Bastion or a jumpbox). The Foundry IQ knowledge base whose blob knowledge
# source points at this container picks the files up on its next indexer run.

import argparse
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from agents import load_settings
from data_sources import (DataSourceError, blob_account_url, check_upload_size, load_data_sources,
                          upload_blob_name)


def parse(argv=None):
    parser = argparse.ArgumentParser(description="Upload documents for the agent's uploaded_documents source")
    parser.add_argument("files", nargs="+", type=Path, help="files to upload (pdf, docx, pptx, xlsx, txt, md, ...)")
    parser.add_argument("--overwrite", action="store_true", help="replace a blob that already exists")
    return parser.parse_args(argv)


def main():
    args = parse()
    source = load_data_sources(load_settings()["data_sources_file"]).uploaded_documents
    if not source.enabled:
        raise SystemExit("uploaded_documents is not enabled in data-sources.json")
    # Validate every file before the first upload, so a bad file never leaves a half-done batch
    plan = []
    for path in args.files:
        try:
            check_upload_size(path.stat().st_size)
            plan.append((path, upload_blob_name(source, path)))
        except (DataSourceError, OSError) as error:
            raise SystemExit(f"{path}: {error}")
    with (
        DefaultAzureCredential() as credential,
        BlobServiceClient(account_url=blob_account_url(source), credential=credential) as service,
    ):
        container = service.get_container_client(source.container)
        for path, blob_name in plan:
            with path.open("rb") as data:
                container.upload_blob(name=blob_name, data=data, overwrite=args.overwrite)
            print(f"Uploaded {path.name} -> {source.storage_account}/{source.container}/{blob_name}")


if __name__ == "__main__":
    main()
