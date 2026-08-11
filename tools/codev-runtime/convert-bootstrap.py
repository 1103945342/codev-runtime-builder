#!/usr/bin/env python3

import argparse
import datetime
import os
import pathlib
import tarfile
import zipfile


def normalized_name(value: str) -> str:
    name = value.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    path = pathlib.PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid archive path: {value!r}")
    return path.as_posix()


def zip_timestamp(epoch: int) -> tuple[int, int, int, int, int, int]:
    value = datetime.datetime.fromtimestamp(
        max(epoch, 315532800), datetime.timezone.utc
    )
    return (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
    )


def zip_info(name: str, member: tarfile.TarInfo, directory: bool = False):
    entry_name = name.rstrip("/") + ("/" if directory else "")
    info = zipfile.ZipInfo(entry_name, zip_timestamp(member.mtime))
    info.create_system = 3
    mode = member.mode or (0o755 if directory else 0o644)
    info.external_attr = ((mode | (0o040000 if directory else 0o100000)) << 16)
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def convert(source: pathlib.Path, destination: pathlib.Path, package_name: str):
    old_prefix = b"/data/data/com.termux/files/usr"
    expected_prefix = f"/data/data/{package_name}/files/usr".encode()
    symlinks: list[str] = []
    expected_prefix_count = 0
    required_files = {"bin/bash": False, "bin/pkg": False}
    source_date_epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "315532800"))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)

    with tarfile.open(source, "r:xz") as archive, zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=False,
    ) as output:
        for member in archive:
            name = normalized_name(member.name)
            if name == ".":
                continue
            if member.isdir():
                output.writestr(zip_info(name, member, directory=True), b"")
                continue
            if member.issym():
                target = member.linkname
                if old_prefix in target.encode():
                    raise ValueError(f"official Termux prefix remains in symlink {name}")
                if expected_prefix in target.encode():
                    expected_prefix_count += 1
                symlinks.append(f"{target}\u2190./{name}")
                continue
            if not member.isfile() and not member.islnk():
                continue

            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"failed to read archive member {name}")
            content = extracted.read()
            if old_prefix in content:
                # Binary-level prefix replacement for ELF files that embed the
                # Termux prefix at compile time (e.g., termux-exec-ld-preload-lib).
                # The replace_termux_name function only handles text files via sed,
                # so compiled binaries need byte-level patching here.
                content = content.replace(old_prefix, expected_prefix)
                if old_prefix in content:
                    raise ValueError(f"official Termux prefix remains in {name} after replacement")
            expected_prefix_count += content.count(expected_prefix)
            if name in required_files:
                required_files[name] = True
            output.writestr(zip_info(name, member), content)

        if not symlinks:
            raise ValueError("source Bootstrap contains no symbolic links")
        symlink_text = ("\n".join(symlinks) + "\n").encode("utf-8")
        symlink_info = zipfile.ZipInfo(
            "SYMLINKS.txt", zip_timestamp(source_date_epoch)
        )
        symlink_info.create_system = 3
        symlink_info.external_attr = (0o100644 << 16)
        symlink_info.compress_type = zipfile.ZIP_DEFLATED
        output.writestr(symlink_info, symlink_text)

    missing = [name for name, found in required_files.items() if not found]
    if missing:
        temporary.unlink(missing_ok=True)
        raise ValueError("Bootstrap is missing: " + ", ".join(missing))
    if expected_prefix_count == 0:
        temporary.unlink(missing_ok=True)
        raise ValueError("CodeV prefix was not found in the Bootstrap")

    temporary.replace(destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--package-name", default="com.codev")
    arguments = parser.parse_args()
    convert(arguments.input, arguments.output, arguments.package_name)


if __name__ == "__main__":
    main()
