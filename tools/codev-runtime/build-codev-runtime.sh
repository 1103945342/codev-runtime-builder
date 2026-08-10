#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIRECTORY="$(cd "$SCRIPT_DIRECTORY/../.." && pwd)"
source "$SCRIPT_DIRECTORY/runtime.env"

WORK_DIRECTORY="${CODEV_RUNTIME_WORK_DIRECTORY:-$SCRIPT_DIRECTORY/.work}"
OUTPUT_DIRECTORY="${CODEV_RUNTIME_OUTPUT_DIRECTORY:-$SCRIPT_DIRECTORY/output}"
ARCHITECTURES="${CODEV_RUNTIME_ARCHITECTURES:-$CODEV_BOOTSTRAP_ARCHITECTURES}"
PACKAGE_NAME="${CODEV_RUNTIME_PACKAGE_NAME:-$CODEV_PACKAGE_NAME}"
KEEP_WORK="${CODEV_RUNTIME_KEEP_WORK:-0}"

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --architectures LIST  Bootstrap architectures.
  --output DIR          Runtime artifact directory.
  --work DIR            Temporary build directory.
  --package-name NAME   Android application package name.
  --keep-work           Preserve source and Docker build state.
EOF
}

while (($# > 0)); do
    case "$1" in
        --architectures)
            ARCHITECTURES="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIRECTORY="$2"
            shift 2
            ;;
        --work)
            WORK_DIRECTORY="$2"
            shift 2
            ;;
        --package-name)
            PACKAGE_NAME="$2"
            shift 2
            ;;
        --keep-work)
            KEEP_WORK=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

for command in docker git patch file python3 sed sha256sum dpkg-deb; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing build command: $command" >&2
        exit 2
    }
done

clone_ref() {
    local repository="$1"
    local reference="$2"
    local destination="$3"
    git init -q "$destination"
    git -C "$destination" remote add origin "$repository"
    git -C "$destination" fetch --depth=1 origin "$reference"
    git -C "$destination" checkout -q --detach FETCH_HEAD
}

if [[ "$KEEP_WORK" != "1" ]]; then
    rm -rf "$WORK_DIRECTORY"
fi
rm -rf "$OUTPUT_DIRECTORY"
mkdir -p "$WORK_DIRECTORY" "$OUTPUT_DIRECTORY"
WORK_DIRECTORY="$(cd "$WORK_DIRECTORY" && pwd)"
OUTPUT_DIRECTORY="$(cd "$OUTPUT_DIRECTORY" && pwd)"

GENERATOR_DIRECTORY="$WORK_DIRECTORY/termux-generator"
PACKAGES_DIRECTORY="$WORK_DIRECTORY/termux-packages"

if [[ ! -d "$GENERATOR_DIRECTORY/.git" ]]; then
    clone_ref \
        "$TERMUX_GENERATOR_REPOSITORY" \
        "$TERMUX_GENERATOR_COMMIT" \
        "$GENERATOR_DIRECTORY"
fi
if [[ ! -d "$PACKAGES_DIRECTORY/.git" ]]; then
    clone_ref \
        "$TERMUX_PACKAGES_REPOSITORY" \
        "$TERMUX_PACKAGES_REF" \
        "$PACKAGES_DIRECTORY"
fi

GENERATOR_RESOLVED_COMMIT="$(git -C "$GENERATOR_DIRECTORY" rev-parse HEAD)"
PACKAGES_RESOLVED_COMMIT="$(git -C "$PACKAGES_DIRECTORY" rev-parse HEAD)"
SOURCE_DATE_EPOCH="$(git -C "$PACKAGES_DIRECTORY" show -s --format=%ct HEAD)"
export SOURCE_DATE_EPOCH

export TERMUX_GENERATOR_HOME="$GENERATOR_DIRECTORY"
export TERMUX_APP__PACKAGE_NAME="$PACKAGE_NAME"
source "$GENERATOR_DIRECTORY/scripts/termux_generator_utils.sh"

CONTAINER_NAME="${PACKAGE_NAME//./-}-codev-runtime-builder"
export CONTAINER_NAME
PREPARED_MARKER="$PACKAGES_DIRECTORY/.codev-runtime-prepared"
EXPECTED_MARKER="$PACKAGE_NAME|$GENERATOR_RESOLVED_COMMIT|$PACKAGES_RESOLVED_COMMIT"
CURRENT_MARKER=""
if [[ -f "$PREPARED_MARKER" ]]; then
    CURRENT_MARKER="$(cat "$PREPARED_MARKER")"
fi
if [[ "$CURRENT_MARKER" != "$EXPECTED_MARKER" ]]; then
    git -C "$PACKAGES_DIRECTORY" reset --hard HEAD
    git -C "$PACKAGES_DIRECTORY" clean -fdx
    replace_termux_name "$PACKAGES_DIRECTORY" "$PACKAGE_NAME"
    apply_patches \
        "$GENERATOR_DIRECTORY/f-droid-patches/bootstrap-patches" \
        "$PACKAGES_DIRECTORY"
    cp -f \
        "$GENERATOR_DIRECTORY/scripts/termux_generator_utils.sh" \
        "$PACKAGES_DIRECTORY/scripts/"
    rm -rf \
        "$PACKAGES_DIRECTORY/packages/swift" \
        "$PACKAGES_DIRECTORY/packages/zeronet"
    portable_sed_i \
        -e "s|termux-package-builder|$CONTAINER_NAME|g" \
        "$PACKAGES_DIRECTORY/scripts/run-docker.sh"
    printf '%s\n' "$EXPECTED_MARKER" > "$PREPARED_MARKER"
fi

IFS=',' read -r -a ARCHITECTURE_LIST <<< "$ARCHITECTURES"
IFS=',' read -r -a RUNTIME_PACKAGE_LIST <<< "$CODEV_RUNTIME_PACKAGES"

pushd "$PACKAGES_DIRECTORY" >/dev/null
scripts/run-docker.sh \
    sudo ln -sf "/data/data/$PACKAGE_NAME/aosp" /system
scripts/run-docker.sh \
    scripts/build-bootstraps.sh \
    --add "$CODEV_BOOTSTRAP_PACKAGES" \
    --architectures "$ARCHITECTURES"

for architecture in "${ARCHITECTURE_LIST[@]}"; do
    scripts/run-docker.sh \
        ./build-package.sh \
        -a "$architecture" \
        "${RUNTIME_PACKAGE_LIST[@]}"
done
popd >/dev/null

MANIFEST="$OUTPUT_DIRECTORY/codev-bootstrap.properties"
{
    echo "format=1"
    echo "packageName=$PACKAGE_NAME"
    echo "prefix=/data/data/$PACKAGE_NAME/files/usr"
    echo "generatorRepository=$TERMUX_GENERATOR_REPOSITORY"
    echo "generatorCommit=$GENERATOR_RESOLVED_COMMIT"
    echo "termuxPackagesRepository=$TERMUX_PACKAGES_REPOSITORY"
    echo "termuxPackagesCommit=$PACKAGES_RESOLVED_COMMIT"
    echo "architectures=$ARCHITECTURES"
} > "$MANIFEST"

for architecture in "${ARCHITECTURE_LIST[@]}"; do
    SOURCE="$PACKAGES_DIRECTORY/bootstrap-$architecture.tar.xz"
    DESTINATION="$OUTPUT_DIRECTORY/bootstrap-$architecture.zip"
    python3 "$SCRIPT_DIRECTORY/convert-bootstrap.py" \
        --input "$SOURCE" \
        --output "$DESTINATION" \
        --package-name "$PACKAGE_NAME"
    {
        echo "bootstrap.$architecture.file=$(basename "$DESTINATION")"
        echo "bootstrap.$architecture.sha256=$(sha256sum "$DESTINATION" | awk '{print $1}')"
        echo "bootstrap.$architecture.size=$(wc -c < "$DESTINATION" | tr -d ' ')"
    } >> "$MANIFEST"
done

python3 "$SCRIPT_DIRECTORY/validate-codev-bootstrap.py" \
    --manifest "$MANIFEST" \
    --directory "$OUTPUT_DIRECTORY"

python3 "$SCRIPT_DIRECTORY/create-apt-repository.py" \
    --debs "$PACKAGES_DIRECTORY/output" \
    --output "$OUTPUT_DIRECTORY/apt" \
    --architectures "$ARCHITECTURES"

tar -C "$OUTPUT_DIRECTORY" -cJf \
    "$OUTPUT_DIRECTORY/codev-apt-repository.tar.xz" apt
sha256sum "$OUTPUT_DIRECTORY/codev-apt-repository.tar.xz" \
    > "$OUTPUT_DIRECTORY/codev-apt-repository.tar.xz.sha256"

cat > "$OUTPUT_DIRECTORY/runtime-build.txt" <<EOF
packageName=$PACKAGE_NAME
generatorCommit=$GENERATOR_RESOLVED_COMMIT
termuxPackagesCommit=$PACKAGES_RESOLVED_COMMIT
architectures=$ARCHITECTURES
runtimePackages=$CODEV_RUNTIME_PACKAGES
EOF

echo "CodeV runtime created in $OUTPUT_DIRECTORY"
