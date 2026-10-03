set -eu
az login --identity --client-id "$AZURE_CLIENT_ID" --allow-no-subscriptions --output none
az storage blob download --account-name "$BUNDLE_ACCOUNT" \
  --container-name "$BUNDLE_CONTAINER" --name "$BUNDLE_BLOB" \
  --file /tmp/agent-bundle.tar.gz --auth-mode login --only-show-errors --output none
printf '%s  %s\n' "$BUNDLE_SHA256" /tmp/agent-bundle.tar.gz | sha256sum -c -
mkdir -p /tmp/agent-app
tar -xzf /tmp/agent-bundle.tar.gz -C /tmp/agent-app
cd /tmp/agent-app
export PYTHONPATH="/tmp/agent-app/wheels/pip-25.3-py3-none-any.whl"
python3 -m pip install --quiet --no-index --no-compile --find-links wheels \
  --target /tmp/agent-deps -r requirements.lock.txt
export PYTHONPATH="/tmp/agent-deps:/tmp/agent-app:/tmp/agent-app/shared:/tmp/agent-app/repository/environment_setup/azurefactory-cli/src"
if [ "${AGENT_COMMAND:-serve}" = "ingest" ]; then
  python3 -c 'import json,os; p="config.json"; c=json.load(open(p)); c["azure"]["managed_identity_client_id"]=os.environ["AZURE_CLIENT_ID"]; json.dump(c,open(p,"w"))'
  exec python3 -m aifactory_agent --config config.json ingest
fi
exec python3 -m aifactory_agent --config config.json serve --port 8080
