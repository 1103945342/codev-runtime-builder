#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIRECTORY="$(cd "$SCRIPT_DIRECTORY/../.." && pwd)"
SOURCE_DIRECTORY="${1:-$SCRIPT_DIRECTORY/output}"
DESTINATION_DIRECTORY="$PROJECT_DIRECTORY/app/src/main/cpp"
MANIFEST="$SOURCE_DIRECTORY/codev-bootstrap.properties"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $0 [RUNTIME_OUTPUT_DIRECTORY]

Validates a CodeV runtime output directory and imports its Bootstrap archives
and manifest into app/src/main/cpp.
EOF
    exit 0
fi

if [[ ! -f "$MANIFEST" ]]; then
    echo "Missing runtime manifest: $MANIFEST" >&2
    exit 2
fi

python3 "$SCRIPT_DIRECTORY/validate-codev-bootstrap.py" \
    --manifest "$MANIFEST" \
    --directory "$SOURCE_DIRECTORY"

PACKAGE_NAME="$(sed -n 's/^packageName=//p' "$MANIFEST")"
ARCHITECTURES="$(sed -n 's/^architectures=//p' "$MANIFEST")"
if [[ "$PACKAGE_NAME" != "com.codev" ]]; then
    echo "Runtime packageName must be com.codev" >&2
    exit 2
fi

mkdir -p "$DESTINATION_DIRECTORY"
find "$DESTINATION_DIRECTORY" \
    -maxdepth 1 -type f -name 'bootstrap-*.zip' -delete
IFS=',' read -r -a ARCHITECTURE_LIST <<< "$ARCHITECTURES"
for architecture in "${ARCHITECTURE_LIST[@]}"; do
    cp -f \
        "$SOURCE_DIRECTORY/bootstrap-$architecture.zip" \
        "$DESTINATION_DIRECTORY/bootstrap-$architecture.zip"
done
cp -f "$MANIFEST" "$DESTINATION_DIRECTORY/codev-bootstrap.properties"

python3 "$SCRIPT_DIRECTORY/validate-codev-bootstrap.py" \
    --manifest "$DESTINATION_DIRECTORY/codev-bootstrap.properties" \
    --directory "$DESTINATION_DIRECTORY"

echo "CodeV Bootstrap imported into $DESTINATION_DIRECTORY"
