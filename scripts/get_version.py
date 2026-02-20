#!/usr/bin/env python3
"""Read or update package.version in Cargo.toml with bounded I/O."""

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
VERSION_LINE_PATTERN = re.compile(
    r'^(?P<prefix>\s*version\s*=\s*)"(?P<value>[^"]*)"(?P<suffix>\s*(?:#.*)?)$'
)
VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?"
    r"(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_parser = subparsers.add_parser("get", help="Read the current package.version.")
    get_parser.add_argument(
        "--file",
        default="Cargo.toml",
        help="Path to the Cargo manifest (default: Cargo.toml).",
    )
    get_parser.add_argument("--key", default=SUPPORTED_KEY, help=argparse.SUPPRESS)

    set_parser = subparsers.add_parser("set", help="Set package.version.")
    set_parser.add_argument("version", help="Version to write.")
    set_parser.add_argument(
        "--file",
        default="Cargo.toml",
        help="Path to the Cargo manifest (default: Cargo.toml).",
    )
    set_parser.add_argument("--key", default=SUPPORTED_KEY, help=argparse.SUPPRESS)

    return parser.parse_args(argv)


def read_text(path: pathlib.Path) -> str:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"Refusing to read {path}: file size {size} exceeds {MAX_FILE_BYTES} bytes"
        )
    return path.read_text(encoding="utf-8")


def load_manifest(path: pathlib.Path, key: str) -> str:
    if key != SUPPORTED_KEY:
        raise ValueError(f"Unsupported key {key!r}; only {SUPPORTED_KEY!r} is supported")
    text = read_text(path)
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


def write_version(path: pathlib.Path, key: str, version: str) -> None:
    if key != SUPPORTED_KEY:
        raise ValueError(f"Unsupported key {key!r}; only {SUPPORTED_KEY!r} is supported")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"Invalid semantic version: {version!r}")

    text = read_text(path)
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

        if version_match.group("value") == version:
            return

        lines[index] = (
            f"{version_match.group('prefix')}\"{version}\""
            f"{version_match.group('suffix')}{line_ending}"
        )
        write_atomic(path, "".join(lines))
        return

    raise ValueError("Could not find package.version assignment inside [package] section")


def write_atomic(path: pathlib.Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    path = pathlib.Path(args.file)
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    try:
        if args.command == "get":
            print(load_manifest(path, args.key))
            return 0
        if args.command == "set":
            write_version(path, args.key, args.version)
            print(args.version)
            return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Unsupported command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
