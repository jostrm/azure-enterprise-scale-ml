#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  printf '%s\n' 'This CI installer requires Linux x64. Locally, pass your installed Bicep path to run_ci.py --bicep.' >&2
  exit 1
fi

destination="${1:?Supply an installation directory}"
version='0.44.1'
checksum='e17dc9a9888184886bb0c0051a3230b83b19f342749999f707bc571c3dfd2f45'
mkdir -p "$destination"
temporary="$(mktemp "$destination/bicep.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
curl --fail --silent --show-error --location --retry 3 --max-time 180 \
  "https://github.com/Azure/bicep/releases/download/v${version}/bicep-linux-x64" \
  --output "$temporary"
printf '%s  %s\n' "$checksum" "$temporary" | sha256sum --check --status
chmod 755 "$temporary"
mv "$temporary" "$destination/bicep"
"$destination/bicep" --version
