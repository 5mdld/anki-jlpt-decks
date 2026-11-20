#!/usr/bin/env python3
"""Generate release-oriented diffs for eggrolls JLPT notes.csv files."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
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
MARKDOWN_INLINE_RE = re.compile(r"([\\`*_\[\]~#])")

FIELD_LABELS = {
    "VocabKanji": "词形",
    "VocabPitch": "音调",
    "VocabPoS": "词性",
    "VocabFurigana": "读音",
    "VocabDefSC": "简体释义",
    "VocabDefTC": "繁体释义",
    "VocabPlus": "补充说明",
    "VocabAudio": "单词音频",
    "Deck": "所属牌组",
    "Sort": "排序",
    "Tags": "标签",
    "Notetype": "笔记类型",
    "Alt1": "模板开关 Alt1",
    "Alt2": "模板开关 Alt2",
}

SENTENCE_FIELD_LABELS = {
    "SentType": "类型",
    "SentKanji": "日文",
    "SentFurigana": "注音",
    "SentDefSC": "简体译文",
    "SentDefTC": "繁体译文",
    "SentAudio": "音频",
}

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
        f"{field}{slot}"
        for field in SENTENCE_FIELD_LABELS
        if field != "SentAudio"
        for slot in range(1, 5)
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
    "笔记类型/模板开关": {
        "Notetype",
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


def markdown_text(value: str) -> str:
    escaped = MARKDOWN_INLINE_RE.sub(r"\\\1", escape(value, quote=False))
    return escaped.replace("|", "&#124;").replace("\n", "<br>")


def diff_values(old: str, new: str, *, highlight: bool) -> tuple[str, str]:
    if not (highlight and old and new):
        return markdown_text(old) or "（空）", markdown_text(new) or "（空）"

    before, after = [], []
    for change, old_start, old_end, new_start, new_end in SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        old_text = markdown_text(old[old_start:old_end])
        new_text = markdown_text(new[new_start:new_end])
        if change != "equal":
            if old_text:
                old_text = f"<strong>{old_text}</strong>"
            if new_text:
                new_text = f"<strong>{new_text}</strong>"
        before.append(old_text)
        after.append(new_text)
    return "".join(before), "".join(after)


def field_label(field: str) -> str:
    if field.startswith("Sent"):
        return f"例句 {field[-1]} · {SENTENCE_FIELD_LABELS[field[:-1]]}"
    return FIELD_LABELS[field]


def render_changed_note(lines: list[str], old: Note, new: Note, fields: list[str]) -> None:
    lines.extend([f"### {markdown_text(new.vocab)}", ""])
    metadata = [f"NoteID <code>{markdown_text(new.note_id)}</code>"]
    if new.furigana and new.furigana != new.vocab and "VocabFurigana" not in fields:
        metadata.insert(0, f"读音 {markdown_text(new.furigana)}")
    lines.extend([" · ".join(metadata), ""])

    contexts = []
    for slot in sorted({field[-1] for field in fields if field.startswith("Sent")}):
        source = f"SentKanji{slot}"
        if source not in fields and new.fields[source]:
            contexts.append(f"- 例句 {slot}「{markdown_text(new.fields[source])}」")
    if contexts:
        lines.extend([*contexts, ""])

    lines.extend(["| 改动字段 | 修改前 | 修改后 |", "| --- | --- | --- |"])
    for field in fields:
        before, after = diff_values(
            old.fields[field], new.fields[field], highlight=field not in CATEGORY_FIELDS["音频"]
        )
        lines.append(f"| {field_label(field)} | {before} | {after} |")
    lines.append("")


def render_note_list(lines: list[str], title: str, notes: list[Note], limit: int) -> None:
    lines.extend([f"## {title}", ""])
    if not notes:
        lines.extend(["无。", ""])
        return
    shown = notes[:limit] if limit > 0 else notes
    lines.extend(["| 词条 | 读音 | 释义 | NoteID |", "| --- | --- | --- | --- |"])
    for note in shown:
        reading = markdown_text(note.furigana) if note.furigana != note.vocab else ""
        lines.append(
            f"| {markdown_text(note.vocab)} | {reading or '—'} | "
            f"{markdown_text(note.definition) or '—'} | <code>{markdown_text(note.note_id)}</code> |"
        )
    lines.append("")
    if len(shown) < len(notes):
        lines.extend([f"另有 {len(notes) - len(shown)} 条未显示。", ""])


def render_diff(args: argparse.Namespace) -> str:
    old_notes = read_notes(args.old, include_version_tags=args.include_version_tags)
    new_notes = read_notes(args.new, include_version_tags=args.include_version_tags)

    if args.summary_only:
        if args.report_url:
            return f"- 完整卡片差异见 [notes diff]({args.report_url})\n"
        return "- 完整卡片差异见 notes diff\n"

    old_ids = set(old_notes)
    new_ids = set(new_notes)
    added_ids = sorted(new_ids - old_ids, key=lambda note_id: new_notes[note_id].index)
    deleted_ids = sorted(old_ids - new_ids, key=lambda note_id: old_notes[note_id].index)
    common_ids = sorted(old_ids & new_ids, key=lambda note_id: new_notes[note_id].index)

    changed: list[tuple[str, list[str]]] = []
    category_counter: Counter[str] = Counter()

    for note_id in common_ids:
        fields = changed_fields(old_notes[note_id], new_notes[note_id])
        if not fields:
            continue
        changed.append((note_id, fields))
        category_counter.update(categories_for(fields))

    lines = ["# 卡片内容差异", ""]
    if args.from_tag or args.to_tag:
        old_tag = markdown_text(args.from_tag or "旧版")
        new_tag = markdown_text(args.to_tag or "新版")
        lines.extend([f"版本范围 **{old_tag} → {new_tag}**", ""])

    lines.extend(
        [
            "## 总览",
            "",
            "| 旧版笔记数 | 新版笔记数 | [删除](#删除词条) | [新增](#新增词条) | [修改](#修改词条) |",
            "| ---: | ---: | ---: | ---: | ---: |",
            f"| {len(old_notes):,} | {len(new_notes):,} | {len(deleted_ids):,} | "
            f"{len(added_ids):,} | {len(changed):,} |",
            "",
        ]
    )

    if category_counter:
        lines.extend(["| 修改类别 | 涉及词条数 |", "| --- | ---: |"])
        for category, count in category_counter.most_common():
            lines.append(f"| {category} | {count:,} |")
        lines.extend(["", "同一词条可计入多个修改类别。", ""])

    render_note_list(
        lines,
        "删除词条",
        [old_notes[note_id] for note_id in deleted_ids],
        args.limit,
    )
    render_note_list(
        lines,
        "新增词条",
        [new_notes[note_id] for note_id in added_ids],
        args.limit,
    )

    lines.extend(["## 修改词条", ""])
    if changed:
        lines.extend(
            ["粗体标出文字改动，音频栏列出完整引用。例句编号对应卡片上的栏目。", ""]
        )
        shown = changed[: args.limit] if args.limit > 0 else changed
        for note_id, fields in shown:
            render_changed_note(lines, old_notes[note_id], new_notes[note_id], fields)
        if len(shown) < len(changed):
            lines.extend([f"另有 {len(changed) - len(shown)} 条未显示。", ""])
    else:
        lines.extend(["无。", ""])

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
