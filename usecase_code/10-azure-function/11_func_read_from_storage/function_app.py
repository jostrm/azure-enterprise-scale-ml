import azure.functions as func
import logging
import json
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContainerClient
import os

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.route(route="read_storage")
def read_storage(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function to read from Azure Storage
    
    Query parameters:
    - storage_account: name of the storage account
    - container: name of the container
    - blob_name: name of the blob to read (optional, if not provided lists blobs)
    """
    logging.info('Python HTTP trigger function processing a request to read from storage.')

    try:
        # Get parameters from query string or request body
        storage_account = req.params.get('storage_account')
        container_name = req.params.get('container')
        blob_name = req.params.get('blob_name')
        
        if not storage_account or not container_name:
            # Try to get from environment variables as fallback
            storage_account = storage_account or os.environ.get('STORAGE_ACCOUNT_NAME')
            container_name = container_name or os.environ.get('CONTAINER_NAME')
        
        if not storage_account or not container_name:
            return func.HttpResponse(
                json.dumps({
                    "error": "Please provide 'storage_account' and 'container' parameters"
                }),
                status_code=400,
                mimetype="application/json"
            )

        # Authenticate using managed identity or DefaultAzureCredential
        credential = DefaultAzureCredential()
        
        # Build account URL
        account_url = f"https://{storage_account}.blob.core.windows.net"
        
        # Create BlobServiceClient
        blob_service_client = BlobServiceClient(
            account_url=account_url,
            credential=credential
        )
        
        # Get container client
        container_client = blob_service_client.get_container_client(container_name)
        
        if blob_name:
            # Read specific blob
            blob_client = container_client.get_blob_client(blob_name)
            
            # Download blob content
            download_stream = blob_client.download_blob()
            blob_content = download_stream.readall()
            
            # Try to decode as text, otherwise return as base64
            try:
                content_text = blob_content.decode('utf-8')
                response_data = {
                    "blob_name": blob_name,
                    "content": content_text,
                    "size_bytes": len(blob_content),
                    "content_type": "text"
                }
            except UnicodeDecodeError:
                import base64
                content_b64 = base64.b64encode(blob_content).decode('utf-8')
                response_data = {
                    "blob_name": blob_name,
                    "content": content_b64,
                    "size_bytes": len(blob_content),
                    "content_type": "binary_base64"
                }
            
            return func.HttpResponse(
                json.dumps(response_data),
                status_code=200,
                mimetype="application/json"
            )
        else:
            # List blobs in container
            blob_list = []
            for blob in container_client.list_blobs():
                blob_list.append({
                    "name": blob.name,
                    "size_bytes": blob.size,
                    "last_modified": blob.last_modified.isoformat() if blob.last_modified else None,
                    "content_type": blob.content_settings.content_type if blob.content_settings else None
                })
            
            response_data = {
                "container": container_name,
                "blob_count": len(blob_list),
                "blobs": blob_list
            }
            
            return func.HttpResponse(
                json.dumps(response_data),
                status_code=200,
                mimetype="application/json"
            )
            
    except Exception as e:
        logging.error(f"Error reading from storage: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "error": str(e),
                "type": type(e).__name__
            }),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="health")
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Simple health check endpoint"""
    logging.info('Health check endpoint called.')
    
    return func.HttpResponse(
        json.dumps({"status": "healthy", "message": "Function is running"}),
        status_code=200,
        mimetype="application/json"
    )
