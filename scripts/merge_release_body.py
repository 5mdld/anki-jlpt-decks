#!/usr/bin/env python3
"""Merge an auto-generated diff block into a GitHub release body."""

from __future__ import annotations

import argparse
from pathlib import Path


AUTO_START = "<!-- AUTO_DIFF_START -->"
AUTO_END = "<!-- AUTO_DIFF_END -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-body", type=Path, required=True)
    parser.add_argument("--diff", type=Path, required=True)
    return parser.parse_args()


def replace_auto_block(body: str, diff: str) -> str:
    block = f"{AUTO_START}\n{diff.rstrip()}\n{AUTO_END}"

    if AUTO_START in body and AUTO_END in body:
        start = body.index(AUTO_START)
        end = body.index(AUTO_END, start) + len(AUTO_END)
        return (body[:start].rstrip() + "\n\n" + block + body[end:]).strip() + "\n"

    if body.strip():
        return body.rstrip() + "\n\n---\n\n" + block + "\n"

    return (
        "## 本次更新\n\n"
        "- TODO: 补充手写更新内容。\n\n"
        "---\n\n"
        f"{block}\n"
    )


def main() -> int:
    args = parse_args()
    body = args.existing_body.read_text(encoding="utf-8") if args.existing_body.exists() else ""
    diff = args.diff.read_text(encoding="utf-8")
    print(replace_auto_block(body, diff), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
