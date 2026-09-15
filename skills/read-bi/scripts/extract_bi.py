#!/usr/bin/env python3
"""Read-only, deterministic raw extractor for one BI PDF or CSV export."""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


ALLOWED_DELIMITERS = (",", ";", "\t")


def csv_rows(text, delimiter):
    """Parse logical CSV records; StringIO preserves quoted embedded newlines."""
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))


def structurally_valid_csv(rows):
    nonempty = [row for row in rows if row]
    if not nonempty or len(nonempty[0]) < 2:
        return False
    width = len(nonempty[0])
    return all(len(row) == width for row in nonempty)


def csv_delimiter(text):
    sample = text[:65536]
    sniffed = None
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters="".join(ALLOWED_DELIMITERS)).delimiter
    except csv.Error:
        pass

    candidates = []
    order = ((sniffed,) + tuple(item for item in ALLOWED_DELIMITERS if item != sniffed)) if sniffed in ALLOWED_DELIMITERS else ALLOWED_DELIMITERS
    for delimiter in order:
        rows = csv_rows(text, delimiter)
        if structurally_valid_csv(rows):
            candidates.append((delimiter, rows))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ExtractionError("csv_delimiter_ambiguous", "More than one supported delimiter yields a valid table.")

    # A one-column CSV is valid, but no delimiter is claimed or inferred.
    rows = csv_rows(text, ",")
    if all(len(row) <= 1 for row in rows):
        return None, rows
    raise ExtractionError("csv_delimiter_ambiguous", "CSV has no uniquely detectable tabular delimiter.")


def extract_csv(path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError("csv_decode_error", "CSV must be UTF-8 or UTF-8-SIG.") from exc
    delimiter, rows = csv_delimiter(text)
    headers = rows[0] if rows else []
    records = []
    for row_number, row in enumerate(rows[1:], start=2):
        cells = []
        for index, raw_cell in enumerate(row):
            column = headers[index] if index < len(headers) else f"column_{index + 1}"
            cells.append({"row": row_number, "column": column, "raw_cell": raw_cell})
        records.append({"row": row_number, "cells": cells})
    delimiter_name = {",": "comma", ";": "semicolon", "\t": "tab", None: "single_column"}[delimiter]
    return {"extractor": "python-csv", "delimiter": delimiter_name, "headers": headers, "rows": records, "row_count": len(records), "page_count": None}


def extract_pdf(path):
    if shutil.which("pdftotext"):
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise ExtractionError("pdf_extraction_failed", result.stderr.strip() or "pdftotext failed.")
        # Form-feed is the page boundary emitted by pdftotext.
        page_texts = result.stdout.split("\f")
        if result.stdout.endswith("\f"):
            page_texts.pop()
        pages = [{"page": index, "text": text} for index, text in enumerate(page_texts, start=1)]
        return {"extractor": "pdftotext-layout", "pages": pages, "page_count": len(pages), "row_count": None}
    if importlib.util.find_spec("pypdf"):
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [{"page": index, "text": page.extract_text() or ""} for index, page in enumerate(reader.pages, start=1)]
        return {"extractor": "pypdf", "pages": pages, "page_count": len(pages), "row_count": None}
    raise ExtractionError("pdf_extractor_unavailable", "Neither pdftotext nor importable pypdf is available; OCR is not used.")


class ExtractionError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = args.file
    observed_at = now_utc()
    try:
        if not path.is_file():
            raise ExtractionError("source_not_readable", "Input path does not exist or is not a regular file.")
        suffix = path.suffix.lower()
        if suffix not in (".pdf", ".csv"):
            raise ExtractionError("unsupported_file_type", "Only .pdf and .csv files are accepted in v1.")
        extracted = extract_pdf(path) if suffix == ".pdf" else extract_csv(path)
        output = {"status": "success", "source": {"type": suffix[1:], "path": str(path), "filename": path.name, "file_sha256": file_hash(path), "observed_at": observed_at, "source_date": None, "extractor": extracted.pop("extractor"), "page_count": extracted.pop("page_count"), "row_count": extracted.pop("row_count")}, "extraction": extracted}
        exit_code = 0
    except ExtractionError as exc:
        output, exit_code = {"status": "error", "error": {"code": exc.code, "message": exc.message}, "observed_at": observed_at}, 2
    serialized = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output and exit_code == 0:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
