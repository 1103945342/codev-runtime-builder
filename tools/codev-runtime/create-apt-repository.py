#!/usr/bin/env python3

import argparse
import datetime
import gzip
import hashlib
import os
import pathlib
import shutil
import subprocess


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_control(path: pathlib.Path) -> tuple[str, dict[str, str]]:
    output = subprocess.check_output(
        ["dpkg-deb", "--field", str(path)],
        text=True,
        encoding="utf-8",
    ).strip()
    fields: dict[str, str] = {}
    current = ""
    for line in output.splitlines():
        if line.startswith((" ", "\t")) and current:
            fields[current] += "\n" + line
            continue
        key, separator, value = line.partition(":")
        if separator:
            current = key
            fields[key] = value.strip()
    return output, fields


def release_date() -> str:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    value = (
        datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
        if epoch > 0
        else datetime.datetime.now(datetime.timezone.utc)
    )
    return value.strftime("%a, %d %b %Y %H:%M:%S +0000")


def create_repository(
    deb_directory: pathlib.Path,
    output: pathlib.Path,
    architectures: list[str],
):
    if output.exists():
        shutil.rmtree(output)
    pool = output / "pool" / "main"
    pool.mkdir(parents=True)

    packages = []
    for source in sorted(deb_directory.glob("*.deb")):
        control, fields = package_control(source)
        architecture = fields.get("Architecture", "")
        package_name = fields.get("Package", "")
        if not architecture or not package_name:
            raise ValueError(f"invalid Debian package metadata: {source}")
        destination = pool / source.name
        shutil.copy2(source, destination)
        packages.append(
            {
                "architecture": architecture,
                "control": control,
                "file": destination,
                "relative": destination.relative_to(output).as_posix(),
            }
        )

    if not packages:
        raise ValueError(f"no Debian packages found in {deb_directory}")

    release_files: list[pathlib.Path] = []
    for architecture in architectures:
        binary = output / "dists" / "stable" / "main" / f"binary-{architecture}"
        binary.mkdir(parents=True)
        records: list[str] = []
        for package in packages:
            if package["architecture"] not in (architecture, "all"):
                continue
            file_path = package["file"]
            records.append(
                package["control"]
                + f"\nFilename: {package['relative']}"
                + f"\nSize: {file_path.stat().st_size}"
                + f"\nSHA256: {sha256(file_path)}\n"
            )
        package_index = binary / "Packages"
        package_index.write_text("\n".join(records), encoding="utf-8")
        with package_index.open("rb") as source, (binary / "Packages.gz").open(
            "wb"
        ) as compressed:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=compressed,
                mtime=0,
            ) as destination:
                shutil.copyfileobj(source, destination)
        release_files.extend([package_index, binary / "Packages.gz"])

    release_root = output / "dists" / "stable"
    checksum_lines = []
    for path in sorted(release_files):
        relative = path.relative_to(release_root).as_posix()
        checksum_lines.append(
            f" {sha256(path)} {path.stat().st_size:16d} {relative}"
        )
    release = (
        "Origin: CodeV\n"
        "Label: CodeV Runtime\n"
        "Suite: stable\n"
        "Codename: stable\n"
        f"Date: {release_date()}\n"
        f"Architectures: {' '.join(architectures)}\n"
        "Components: main\n"
        "Description: Source-built packages for the com.codev runtime\n"
        "SHA256:\n"
        + "\n".join(checksum_lines)
        + "\n"
    )
    (release_root / "Release").write_text(release, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debs", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--architectures", required=True)
    arguments = parser.parse_args()
    architectures = [
        value.strip()
        for value in arguments.architectures.split(",")
        if value.strip()
    ]
    create_repository(arguments.debs, arguments.output, architectures)


if __name__ == "__main__":
    main()
