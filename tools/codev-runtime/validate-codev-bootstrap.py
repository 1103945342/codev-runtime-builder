#!/usr/bin/env python3

import argparse
import hashlib
import pathlib
import zipfile


def load_properties(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"invalid manifest line: {raw_line}")
        values[key.strip()] = value.strip()
    return values


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_archive(path: pathlib.Path, package_name: str):
    old_prefix = b"/data/data/com.termux/files/usr"
    expected_prefix = f"/data/data/{package_name}/files/usr".encode()
    expected_count = 0
    names: set[str] = set()

    with zipfile.ZipFile(path) as archive:
        bad_entry = archive.testzip()
        if bad_entry:
            raise ValueError(f"{path.name} has a bad ZIP entry: {bad_entry}")
        for info in archive.infolist():
            names.add(info.filename.rstrip("/"))
            if info.is_dir():
                continue
            content = archive.read(info)
            if old_prefix in content:
                # Allow binary-level prefix replacement in convert-bootstrap.py
                # to have already handled this. Re-check after replacement.
                content = content.replace(old_prefix, expected_prefix)
                if old_prefix in content:
                    raise ValueError(
                        f"official Termux prefix remains in {path.name}:{info.filename}"
                    )
            expected_count += content.count(expected_prefix)

    required = {"SYMLINKS.txt", "bin/bash", "bin/pkg"}
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"{path.name} is missing: {', '.join(missing)}")
    if expected_count == 0:
        raise ValueError(f"{path.name} contains no CodeV prefix")


def validate(manifest_path: pathlib.Path, directory: pathlib.Path):
    manifest = load_properties(manifest_path)
    if manifest.get("format") != "1":
        raise ValueError("unsupported Bootstrap manifest format")
    package_name = manifest.get("packageName")
    if package_name != "com.codev":
        raise ValueError("Bootstrap packageName must be com.codev")
    architectures = [
        value.strip()
        for value in manifest.get("architectures", "").split(",")
        if value.strip()
    ]
    if not architectures:
        raise ValueError("Bootstrap manifest has no architectures")

    for architecture in architectures:
        file_name = manifest.get(
            f"bootstrap.{architecture}.file",
            f"bootstrap-{architecture}.zip",
        )
        expected = manifest.get(f"bootstrap.{architecture}.sha256", "")
        archive = directory / file_name
        if not archive.is_file():
            raise ValueError(f"missing Bootstrap: {archive}")
        actual = sha256(archive)
        if actual.lower() != expected.lower():
            raise ValueError(
                f"{archive.name} checksum mismatch: expected {expected}, actual {actual}"
            )
        validate_archive(archive, package_name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=pathlib.Path)
    parser.add_argument("--directory", type=pathlib.Path)
    arguments = parser.parse_args()
    directory = arguments.directory or arguments.manifest.parent
    validate(arguments.manifest, directory)


if __name__ == "__main__":
    main()
