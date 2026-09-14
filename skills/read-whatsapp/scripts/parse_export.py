#!/usr/bin/env python3
"""Deterministic structural parser for WhatsApp text exports (stdlib only)."""

import argparse
import hashlib
import json
import re
import sys
import tempfile
import unicodedata
import unittest
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


PARSER_VERSION = "1.0.0"
HEADER = re.compile(r"^\[(\d{2}/\d{2}/\d{4}), (\d{2}:\d{2}:\d{2})\] ([^:\n]+):(?: ?)(.*)$")
ATTACHMENT = re.compile(r"<anexado:\s*([^>]+)>", re.IGNORECASE)
OMITTED_MEDIA = (
    "vídeo omitido", "video omitido", "imagem omitida", "áudio omitido",
    "audio omitido", "documento omitido",
)


def matching(value):
    """Normalize only line endings, NFC, and invisible formatting/control chars."""
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    return "".join(
        char for char in value
        if unicodedata.category(char) != "Cf"
        and not (unicodedata.category(char) == "Cc" and char != "\n")
    )


def fingerprint(message_date, local_time_reference, participant_matching, body_matching, attachment_filenames):
    payload = {
        "message_date": message_date,
        "local_time_reference": local_time_reference,
        "participant_matching": participant_matching,
        "body_matching": body_matching,
        "attachment_filenames": attachment_filenames,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_message(sequence, date_raw, time_raw, participant_raw, body_raw):
    try:
        message_date = datetime.strptime(date_raw, "%d/%m/%Y").date().isoformat()
    except ValueError:  # Header regex makes this defensive branch unlikely.
        message_date = None
    participant_matching = matching(participant_raw)
    body_matching = matching(body_raw)
    attachments = [item.strip() for item in ATTACHMENT.findall(body_raw) if item.strip()]
    marker_text = body_matching.casefold()
    return {
        "source_sequence": sequence,
        "message_date": message_date,
        "local_time_reference": time_raw,
        "participant_raw": participant_raw,
        "participant_matching": participant_matching,
        "body_raw": body_raw,
        "body_matching": body_matching,
        "attachment_filenames": attachments,
        "edited_marker": "mensagem editada" in marker_text,
        "deleted_marker": "mensagem apagada" in marker_text,
        "omitted_media_marker": any(marker in marker_text for marker in OMITTED_MEDIA),
        "possible_system_event": False,
        "message_fingerprint": fingerprint(message_date, time_raw, participant_matching, body_matching, attachments),
    }


def parse_chat(chat_path):
    raw = Path(chat_path).read_text(encoding="utf-8-sig")
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # A final text-file newline is not an extra body line.
    messages, current = [], None
    for line in lines:
        header = HEADER.match(line)
        if header:
            if current is not None:
                messages.append(build_message(len(messages) + 1, *current))
            current = [header.group(1), header.group(2), header.group(3), header.group(4)]
        elif current is not None:
            current[3] += "\n" + line
    if current is not None:
        messages.append(build_message(len(messages) + 1, *current))
    return messages


def archive_details(archive_path, references):
    if not archive_path:
        return None, {"by_extension": {}, "references": [
            {"filename": name, "exists_in_archive": None} for name in references
        ]}
    archive_bytes = Path(archive_path).read_bytes()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    with zipfile.ZipFile(archive_path) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
    inventory = Counter()
    for name in names:
        suffix = Path(name).suffix.lower().lstrip(".") or "[no_extension]"
        inventory[suffix] += 1
    name_set = set(names)
    basenames = {Path(name).name for name in names}
    return archive_sha256, {"by_extension": dict(sorted(inventory.items())), "references": [
        {"filename": name, "exists_in_archive": name in name_set or name in basenames}
        for name in references
    ]}


def make_cursor(messages, source_id, archive_sha256, chat_filename, ingestion_mode):
    if len(messages) < 3:
        return None
    last = messages[-1]
    return {
        "source_id": source_id,
        "ingestion_mode": ingestion_mode,
        "archive_sha256": archive_sha256,
        "chat_filename": chat_filename,
        "conversation_end_date": max((m["message_date"] for m in messages if m["message_date"]), default=None),
        "last_source_sequence": last["source_sequence"],
        "last_message": {
            "message_date": last["message_date"], "local_time_reference": last["local_time_reference"],
            "participant": last["participant_raw"], "message_fingerprint": last["message_fingerprint"],
        },
        "anchor_fingerprints": [m["message_fingerprint"] for m in messages[-3:]],
    }


def locate_anchors(messages, anchors):
    if not isinstance(anchors, list) or len(anchors) != 3:
        return []
    actual = [message["message_fingerprint"] for message in messages]
    return [index for index in range(len(actual) - 2) if actual[index:index + 3] == anchors]


def parse_export(chat_path, archive_path=None, source_id=None, mode="baseline", previous_cursor=None):
    messages = parse_chat(chat_path)
    references = [filename for message in messages for filename in message["attachment_filenames"]]
    archive_sha256, attachment_inventory = archive_details(archive_path, references)
    dates = [message["message_date"] for message in messages if message["message_date"]]
    result = {
        "parser_version": PARSER_VERSION,
        "chat_filename": Path(chat_path).name,
        "archive_sha256": archive_sha256,
        "message_count": len(messages),
        "conversation_start_date": min(dates) if dates else None,
        "conversation_end_date": max(dates) if dates else None,
        "messages": messages,
        "attachment_inventory": attachment_inventory,
        "cursor_resolution": "not_applicable",
        "previous_cursor": previous_cursor,
        "next_cursor": None,
        "delta_start_sequence": None,
        "delta_messages": [],
        "delta_message_count": 0,
    }
    if mode == "baseline":
        result["next_cursor"] = make_cursor(messages, source_id, archive_sha256, Path(chat_path).name, "baseline")
    else:
        if previous_cursor is None:
            raise ValueError("--previous-cursor is required when --mode=incremental")
        matches = locate_anchors(messages, previous_cursor.get("anchor_fingerprints")) if isinstance(previous_cursor, dict) else []
        if len(matches) == 1:
            result["cursor_resolution"] = "unique_match"
            start = matches[0] + 3
            delta = messages[start:]
            result["delta_start_sequence"] = start + 1 if delta else None
            result["delta_messages"] = delta
            result["delta_message_count"] = len(delta)
            result["next_cursor"] = make_cursor(messages, source_id, archive_sha256, Path(chat_path).name, "incremental")
        elif not matches:
            result["cursor_resolution"] = "not_found"
        else:
            result["cursor_resolution"] = "ambiguous"
    return result


def load_cursor(value):
    candidate = Path(value)
    return json.loads(candidate.read_text(encoding="utf-8")) if candidate.is_file() else json.loads(value)


class ParserTests(unittest.TestCase):
    def parse_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "_chat.txt"
            path.write_text(text, encoding="utf-8")
            return parse_export(path)

    def test_simple_message_and_fingerprint(self):
        first = self.parse_text("[01/09/2026, 10:00:00] Ana: Olá")
        second = self.parse_text("[01/09/2026, 10:00:00] Ana: Olá")
        self.assertEqual(first["message_count"], 1)
        self.assertEqual(first["messages"][0]["message_fingerprint"], second["messages"][0]["message_fingerprint"])

    def test_multiline_attachment_and_invisible_unicode(self):
        result = self.parse_text("[01/09/2026, 10:00:00] A\u200bna: linha\ncontinua <anexado: x.pdf>")
        message = result["messages"][0]
        self.assertEqual(message["body_raw"], "linha\ncontinua <anexado: x.pdf>")
        self.assertEqual(message["attachment_filenames"], ["x.pdf"])
        self.assertEqual(message["participant_matching"], "Ana")

    def test_range_uses_dates_not_physical_endpoints(self):
        result = self.parse_text("[03/09/2026, 10:00:00] A: x\n[01/09/2026, 10:00:00] A: y\n[02/09/2026, 10:00:00] A: z")
        self.assertEqual((result["conversation_start_date"], result["conversation_end_date"]), ("2026-09-01", "2026-09-03"))

    def test_cursor_three_anchors_and_unique_incremental(self):
        text = "\n".join(f"[01/09/2026, 10:00:0{i}] A: {i}" for i in range(4))
        baseline = self.parse_text(text)
        self.assertEqual(len(baseline["next_cursor"]["anchor_fingerprints"]), 3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "_chat.txt"; path.write_text(text + "\n[01/09/2026, 10:00:04] A: 4", encoding="utf-8")
            incremental = parse_export(path, mode="incremental", previous_cursor=baseline["next_cursor"])
        self.assertEqual((incremental["cursor_resolution"], incremental["delta_message_count"]), ("unique_match", 1))

    def test_incremental_not_found_and_ambiguous(self):
        previous = {"anchor_fingerprints": ["a", "b", "c"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "_chat.txt"; path.write_text("[01/09/2026, 10:00:00] A: x", encoding="utf-8")
            result = parse_export(path, mode="incremental", previous_cursor=previous)
        self.assertEqual(result["cursor_resolution"], "not_found")
        text = "\n".join(["[01/09/2026, 10:00:00] A: a", "[01/09/2026, 10:00:01] A: b", "[01/09/2026, 10:00:02] A: c"] * 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "_chat.txt"; path.write_text(text, encoding="utf-8")
            baseline = parse_export(path)
            anchors = [m["message_fingerprint"] for m in baseline["messages"][:3]]
            ambiguous = parse_export(path, mode="incremental", previous_cursor={"anchor_fingerprints": anchors})
        self.assertEqual(ambiguous["cursor_resolution"], "ambiguous")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat")
    parser.add_argument("--archive")
    parser.add_argument("--source-id")
    parser.add_argument("--mode", choices=("baseline", "incremental"), default="baseline")
    parser.add_argument("--previous-cursor")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ParserTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if not args.chat:
        parser.error("--chat is required unless --self-test is used")
    try:
        previous = load_cursor(args.previous_cursor) if args.previous_cursor else None
        output = parse_export(args.chat, args.archive, args.source_id, args.mode, previous)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
