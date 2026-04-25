#!/usr/bin/env python3
"""Generate release-oriented diffs for eggrolls JLPT notes.csv files."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FIELD_NAMES = [
    "Notetype",
    "Deck",
    "NoteID",
    "VocabKanji",
    "VocabPitch",
    "VocabPoS",
    "VocabFurigana",
    "VocabDefSC",
    "VocabDefTC",
    "VocabPlus",
    "VocabAudio",
    "SentType1",
    "SentKanji1",
    "SentFurigana1",
    "SentDefSC1",
    "SentDefTC1",
    "SentAudio1",
    "SentType2",
    "SentKanji2",
    "SentFurigana2",
    "SentDefSC2",
    "SentDefTC2",
    "SentAudio2",
    "SentType3",
    "SentKanji3",
    "SentFurigana3",
    "SentDefSC3",
    "SentDefTC3",
    "SentAudio3",
    "SentType4",
    "SentKanji4",
    "SentFurigana4",
    "SentDefSC4",
    "SentDefTC4",
    "SentAudio4",
    "Sort",
    "Alt1",
    "Alt2",
    "Tags",
]

LEGACY_FIELD_COUNT = len(FIELD_NAMES) + 1
DECK_FIRST_FIELD_COUNT = len(FIELD_NAMES) - 1
KEY_FIELD = "NoteID"
VERSION_TAG_RE = re.compile(r"(?:^|::)v(\d{2}\.\d{2}\.\d{2}(?:_\d+)?)$")

CATEGORY_FIELDS = {
    "词条信息": {
        "VocabKanji",
        "VocabPitch",
        "VocabPoS",
        "VocabFurigana",
        "VocabPlus",
    },
    "释义": {
        "VocabDefSC",
        "VocabDefTC",
    },
    "例句": {
        "SentType1",
        "SentKanji1",
        "SentFurigana1",
        "SentDefSC1",
        "SentDefTC1",
        "SentType2",
        "SentKanji2",
        "SentFurigana2",
        "SentDefSC2",
        "SentDefTC2",
        "SentType3",
        "SentKanji3",
        "SentFurigana3",
        "SentDefSC3",
        "SentDefTC3",
        "SentType4",
        "SentKanji4",
        "SentFurigana4",
        "SentDefSC4",
        "SentDefTC4",
    },
    "音频": {
        "VocabAudio",
        "SentAudio1",
        "SentAudio2",
        "SentAudio3",
        "SentAudio4",
    },
    "分组/排序/标签": {
        "Deck",
        "Tags",
        "Sort",
    },
    "模板开关": {
        "Alt1",
        "Alt2",
    },
}


@dataclass(frozen=True)
class Note:
    index: int
    fields: dict[str, str]

    @property
    def note_id(self) -> str:
        return self.fields[KEY_FIELD]

    @property
    def vocab(self) -> str:
        return self.fields["VocabKanji"] or self.note_id

    @property
    def furigana(self) -> str:
        return self.fields["VocabFurigana"]

    @property
    def definition(self) -> str:
        return first_nonempty(self.fields["VocabDefSC"], self.fields["VocabDefTC"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser(
        "version", help="print the most common version tag from notes.csv"
    )
    version_parser.add_argument("notes", type=Path)

    diff_parser = subparsers.add_parser(
        "diff", help="print a Markdown diff report between two notes.csv files"
    )
    diff_parser.add_argument("--old", required=True, type=Path, help="old notes.csv")
    diff_parser.add_argument("--new", required=True, type=Path, help="new notes.csv")
    diff_parser.add_argument("--from-tag", default="", help="old release tag")
    diff_parser.add_argument("--to-tag", default="", help="new release tag")
    diff_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="maximum listed notes per section; 0 means unlimited",
    )
    diff_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="only print the release-body summary, not full note lists",
    )
    diff_parser.add_argument(
        "--report-url",
        default="",
        help="URL to the full report; used with --summary-only",
    )
    diff_parser.add_argument(
        "--include-version-tags",
        action="store_true",
        help="include version tag changes in Tags comparisons",
    )
    return parser.parse_args()


def read_notes(path: Path, include_version_tags: bool = False) -> dict[str, Note]:
    notes: dict[str, Note] = {}
    with path.open(encoding="utf-8", newline="") as file:
        delimiter = detect_delimiter(file.readline())
        file.seek(0)
        reader = csv.reader(file, delimiter=delimiter)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            fields = row_to_fields(row, path)
            fields = normalize_fields(fields, include_version_tags)
            note = Note(index=len(notes) + 1, fields=fields)
            if not note.note_id:
                raise ValueError(f"{path}: note at data row {note.index} has empty NoteID")
            if note.note_id in notes:
                raise ValueError(f"{path}: duplicate NoteID {note.note_id}")
            notes[note.note_id] = note
    return notes


def detect_delimiter(first_line: str) -> str:
    normalized = first_line.strip().lower()
    if normalized == "#separator:comma":
        return ","
    if normalized == "#separator:semicolon":
        return ";"
    return "\t"


def row_to_fields(row: list[str], path: Path) -> dict[str, str]:
    if len(row) == LEGACY_FIELD_COUNT:
        row = row[1:]

    if len(row) == len(FIELD_NAMES):
        return dict(zip(FIELD_NAMES, row))

    if len(row) == DECK_FIRST_FIELD_COUNT:
        fields = dict(zip(FIELD_NAMES[1:], row))
        fields["Notetype"] = ""
        return fields

    raise ValueError(f"{path}: expected {len(FIELD_NAMES)} columns, got {len(row)}")


def normalize_fields(fields: dict[str, str], include_version_tags: bool) -> dict[str, str]:
    normalized = {key: normalize_value(value) for key, value in fields.items()}
    if not include_version_tags:
        normalized["Tags"] = normalize_tags(normalized["Tags"])
    return normalized


def normalize_value(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_tags(tags: str) -> str:
    kept = [tag for tag in tags.split() if not VERSION_TAG_RE.search(tag)]
    return " ".join(sorted(kept))


def extract_version(notes_path: Path) -> str:
    versions: Counter[str] = Counter()
    with notes_path.open(encoding="utf-8", newline="") as file:
        delimiter = detect_delimiter(file.readline())
        file.seek(0)
        reader = csv.reader(file, delimiter=delimiter)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            fields = row_to_fields(row, notes_path)
            for tag in fields["Tags"].split():
                match = VERSION_TAG_RE.search(tag)
                if match:
                    versions[match.group(1)] += 1

    if not versions:
        raise ValueError(f"{notes_path}: no version tag found in Tags field")

    version, count = versions.most_common(1)[0]
    if len(versions) > 1:
        print(
            f"warning: multiple version tags found; using {version} ({count} notes)",
            file=sys.stderr,
        )
    return version


def changed_fields(old: Note, new: Note) -> list[str]:
    return [
        field
        for field in FIELD_NAMES
        if field != KEY_FIELD and old.fields[field] != new.fields[field]
    ]


def categories_for(fields: Iterable[str]) -> list[str]:
    categories = [
        category
        for category, category_fields in CATEGORY_FIELDS.items()
        if any(field in category_fields for field in fields)
    ]
    return categories or ["其他"]


def first_nonempty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def short(value: str, max_length: int = 76) -> str:
    value = " ".join(value.split())
    if len(value) <= max_length:
        return value
    return value[: max_length - 1] + "..."


def note_summary(note: Note) -> str:
    parts = [note.vocab]
    if note.furigana and note.furigana != note.vocab:
        parts.append(note.furigana)
    if note.definition:
        parts.append(short(note.definition))
    return " | ".join(parts)


def changed_line(old: Note, new: Note, fields: list[str]) -> str:
    categories = "、".join(categories_for(fields))
    line = f"- `{new.note_id}` {note_summary(new)} | {categories} | `{', '.join(fields)}`"

    old_def = short(old.definition)
    new_def = short(new.definition)
    if old_def != new_def and {"VocabDefSC", "VocabDefTC"} & set(fields):
        line += f"\n  - 释义：{old_def} -> {new_def}"
    return line


def limited(items: list[str], limit: int) -> tuple[list[str], int]:
    if limit <= 0 or len(items) <= limit:
        return items, 0
    return items[:limit], len(items) - limit


def render_section(lines: list[str], title: str, items: list[str], limit: int) -> None:
    lines.extend([f"### {title}", ""])
    if not items:
        lines.extend(["无。", ""])
        return
    shown, hidden = limited(items, limit)
    lines.extend(shown)
    if hidden:
        lines.append(f"- ... 另有 {hidden} 条未显示")
    lines.append("")


def render_diff(args: argparse.Namespace) -> str:
    old_notes = read_notes(args.old, include_version_tags=args.include_version_tags)
    new_notes = read_notes(args.new, include_version_tags=args.include_version_tags)

    old_ids = set(old_notes)
    new_ids = set(new_notes)
    added_ids = sorted(new_ids - old_ids, key=lambda note_id: new_notes[note_id].index)
    deleted_ids = sorted(old_ids - new_ids, key=lambda note_id: old_notes[note_id].index)
    common_ids = sorted(old_ids & new_ids, key=lambda note_id: new_notes[note_id].index)

    changed: list[tuple[str, list[str]]] = []
    category_counter: Counter[str] = Counter()
    field_counter: Counter[str] = Counter()

    for note_id in common_ids:
        fields = changed_fields(old_notes[note_id], new_notes[note_id])
        if not fields:
            continue
        changed.append((note_id, fields))
        category_counter.update(categories_for(fields))
        field_counter.update(fields)

    lines = ["## 自动生成的内容差异", ""]
    if args.from_tag or args.to_tag:
        lines.extend([f"> 对比范围：`{args.from_tag or 'old'}` -> `{args.to_tag or 'new'}`", ""])

    lines.extend(
        [
            "### 摘要",
            "",
            f"- 旧版笔记数：{len(old_notes)}",
            f"- 新版笔记数：{len(new_notes)}",
            f"- 新增：{len(added_ids)}",
            f"- 删除：{len(deleted_ids)}",
            f"- 修改：{len(changed)}",
            "",
        ]
    )

    if category_counter:
        lines.extend(["### 修改类型", ""])
        for category, count in category_counter.most_common():
            lines.append(f"- {category}：{count}")
        lines.append("")

    if args.summary_only:
        if args.report_url:
            return f"完整更新差异见 [Markdown 报告]({args.report_url})。\n"
        else:
            return "完整更新差异见 Markdown 报告。\n"

    render_section(
        lines,
        "新增词条",
        [f"- `{note_id}` {note_summary(new_notes[note_id])}" for note_id in added_ids],
        args.limit,
    )
    render_section(
        lines,
        "删除词条",
        [f"- `{note_id}` {note_summary(old_notes[note_id])}" for note_id in deleted_ids],
        args.limit,
    )
    render_section(
        lines,
        "修改词条",
        [
            changed_line(old_notes[note_id], new_notes[note_id], fields)
            for note_id, fields in changed
        ],
        args.limit,
    )

    lines.extend(
        [
            "### 比较规则",
            "",
            "- 使用 `NoteID` 对齐新旧笔记。",
            "- 默认忽略形如 `eggrolls-JLPT10k-v3::v26.03.25` 的版本标签。",
            "- 比较前会统一换行符、去掉字段首尾空白，并规范化标签顺序。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    try:
        if args.command == "version":
            print(extract_version(args.notes))
            return 0
        if args.command == "diff":
            print(render_diff(args), end="")
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"error: unsupported command {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
