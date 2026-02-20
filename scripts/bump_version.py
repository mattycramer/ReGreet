#!/usr/bin/env python3
"""Update package.version in Cargo.toml with bounded and validated edits."""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import tempfile
import tomllib

MAX_FILE_BYTES = 2 * 1024 * 1024
SUPPORTED_KEY = "package.version"
SECTION_PATTERN = re.compile(r"^\s*\[(?P<section>[^\]]+)\]\s*$")
VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?"
    r"(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)
VERSION_LINE_PATTERN = re.compile(
    r'^(?P<prefix>\s*version\s*=\s*)"(?P<value>[^"]*)"(?P<suffix>\s*(?:#.*)?)$'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        default="Cargo.toml",
        help="Path to the Cargo manifest (default: Cargo.toml).",
    )
    parser.add_argument("--version", required=True, help="New semantic version value.")
    parser.add_argument(
        "--format",
        default="toml",
        choices=("toml",),
        help="Manifest format. Only TOML is supported.",
    )
    parser.add_argument(
        "--key",
        default=SUPPORTED_KEY,
        help=f"Key path to update (only {SUPPORTED_KEY} is supported).",
    )
    return parser.parse_args()


def read_text(path: pathlib.Path) -> str:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"Refusing to read {path}: file size {size} exceeds {MAX_FILE_BYTES} bytes"
        )
    return path.read_text(encoding="utf-8")


def ensure_manifest_has_version(text: str, key: str) -> str:
    if key != SUPPORTED_KEY:
        raise ValueError(f"Unsupported key {key!r}; only {SUPPORTED_KEY!r} is allowed")
    try:
        manifest = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML manifest: {exc}") from exc
    package = manifest.get("package")
    if not isinstance(package, dict):
        raise ValueError("Missing [package] section in manifest")
    version = package.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("Missing package.version in manifest")
    return version


def update_package_version(text: str, new_version: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    in_package = False

    for index, line in enumerate(lines):
        section_match = SECTION_PATTERN.match(line.strip("\n"))
        if section_match:
            in_package = section_match.group("section").strip() == "package"
            continue

        if not in_package:
            continue

        line_ending = "\n" if line.endswith("\n") else ""
        line_body = line[:-1] if line_ending else line
        version_match = VERSION_LINE_PATTERN.match(line_body)
        if not version_match:
            continue

        current = version_match.group("value")
        if current == new_version:
            return text, False

        lines[index] = (
            f"{version_match.group('prefix')}\"{new_version}\""
            f"{version_match.group('suffix')}{line_ending}"
        )
        return "".join(lines), True

    raise ValueError("Could not find package.version assignment inside [package] section")


def atomic_write(path: pathlib.Path, content: str) -> None:
    parent = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    tmp_path = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def main() -> int:
    args = parse_args()
    path = pathlib.Path(args.file)
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    if not VERSION_PATTERN.fullmatch(args.version):
        print(f"Invalid semantic version: {args.version!r}", file=sys.stderr)
        return 2

    try:
        original = read_text(path)
        ensure_manifest_has_version(original, args.key)
        updated, changed = update_package_version(original, args.version)
        ensure_manifest_has_version(updated, args.key)
        if changed:
            atomic_write(path, updated)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
