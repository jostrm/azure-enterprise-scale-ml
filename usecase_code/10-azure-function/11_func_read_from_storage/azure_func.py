
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient
import os

# --- Config ---
account_name   = "<storage-account-name>"          # e.g., mystorageacct
container_name = "<container>"                     # e.g., data
blob_name      = "<path/to/file.csv>"              # e.g., sales/2025-11.csv
local_path     = "sales_2025-11.csv"               # where to save locally

# --- Auth via Entra ID ---
credential = DefaultAzureCredential()

# Build account URL: https://<account>.blob.core.windows.net
account_url = f"https://{account_name}.blob.core.windows.net"

# Create BlobClient bound to Entra ID credential
blob_client = BlobClient(
    account_url=account_url,
    container_name=container_name,
    blob_name=blob_name,
    credential=credential,
)

# --- Download to local file ---
# For large files, stream and write chunk-by-chunk for efficiency
with open(local_path, "wb") as f:
    download_stream = blob_client.download_blob(max_concurrency=4)
    download_stream.readinto(f)

print(f"Downloaded '{blob_name}' to '{os.path.abspath(local_path)}'")