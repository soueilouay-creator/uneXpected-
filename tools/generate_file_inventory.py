from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "FILE_INVENTORY_SHA256.txt"


def build_inventory() -> str:
    excluded_dirs = {".git", "__pycache__", "state"}
    excluded_suffixes = {".pyc", ".sqlite3"}
    files = sorted(
        path for path in ROOT.rglob("*")
        if path.is_file()
        and path != INVENTORY
        and not any(part in excluded_dirs for part in path.parts)
        and path.suffix not in excluded_suffixes
    )
    return "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(ROOT).as_posix()}\n"
        for path in files
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate uneXpected's SHA-256 source inventory.")
    parser.add_argument("--write", action="store_true", help="Write FILE_INVENTORY_SHA256.txt.")
    args = parser.parse_args()
    content = build_inventory()
    if args.write:
        INVENTORY.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
