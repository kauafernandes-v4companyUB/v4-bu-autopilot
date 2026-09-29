"""A1 notation helpers for Google Sheets ranges (skills/read-google-sheet,
skills/update-google-sheet). Pure functions, no I/O, no client logic.

Rows and columns are 1-based everywhere in this module (A1 = row 1,
col 1). A range always carries an explicit sheet title — a bare "A1:B2"
is rejected, because it would silently target whatever the first tab
happens to be.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_SIMPLE_TITLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENDPOINT = re.compile(r"^\$?([A-Za-z]{1,3})?\$?([0-9]+)?$")
_CELL_LIKE = re.compile(r"^\$?[A-Za-z]{1,3}\$?[0-9]+(:\$?[A-Za-z]{0,3}\$?[0-9]*)?$")


class A1Error(ValueError):
    pass


def col_to_letters(col: int) -> str:
    if col < 1:
        raise A1Error(f"column index must be >= 1, got {col}")
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def letters_to_col(letters: str) -> int:
    if not letters or not letters.isalpha():
        raise A1Error(f"invalid column letters: {letters!r}")
    col = 0
    for ch in letters.upper():
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return col


def quote_sheet_title(title: str) -> str:
    if _SIMPLE_TITLE.match(title) and not _CELL_LIKE.match(title):
        return title
    return "'" + title.replace("'", "''") + "'"


def cell_a1(sheet_title: str, row: int, col: int) -> str:
    return f"{quote_sheet_title(sheet_title)}!{col_to_letters(col)}{row}"


@dataclass(frozen=True)
class A1Range:
    sheet_title: str
    start_row: Optional[int] = None
    start_col: Optional[int] = None
    end_row: Optional[int] = None
    end_col: Optional[int] = None

    @property
    def is_whole_sheet(self) -> bool:
        return self.start_row is None and self.start_col is None and self.end_row is None and self.end_col is None

    @property
    def is_bounded(self) -> bool:
        return None not in (self.start_row, self.start_col, self.end_row, self.end_col)

    @property
    def n_rows(self) -> int:
        self._require_bounded()
        return self.end_row - self.start_row + 1

    @property
    def n_cols(self) -> int:
        self._require_bounded()
        return self.end_col - self.start_col + 1

    def _require_bounded(self) -> None:
        if not self.is_bounded:
            raise A1Error(f"range {self.to_a1()!r} is not bounded (needs explicit start and end cell)")

    def cells(self) -> list[tuple[int, int]]:
        """Row-major list of (row, col) for a bounded range."""
        self._require_bounded()
        return [(r, c) for r in range(self.start_row, self.end_row + 1) for c in range(self.start_col, self.end_col + 1)]

    def to_a1(self) -> str:
        sheet = quote_sheet_title(self.sheet_title)
        if self.is_whole_sheet:
            return sheet

        def endpoint(row, col):
            return (col_to_letters(col) if col is not None else "") + (str(row) if row is not None else "")

        start = endpoint(self.start_row, self.start_col)
        end = endpoint(self.end_row, self.end_col)
        if self.is_bounded and (self.start_row, self.start_col) == (self.end_row, self.end_col):
            return f"{sheet}!{start}"
        return f"{sheet}!{start}:{end}"

    def contains(self, row: int, col: int) -> bool:
        return (
            (self.start_row is None or row >= self.start_row)
            and (self.end_row is None or row <= self.end_row)
            and (self.start_col is None or col >= self.start_col)
            and (self.end_col is None or col <= self.end_col)
        )


def _split_sheet(text: str) -> tuple[str, Optional[str]]:
    if text.startswith("'"):
        i, title = 1, []
        while i < len(text):
            ch = text[i]
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    title.append("'")
                    i += 2
                    continue
                rest = text[i + 1:]
                if rest == "":
                    return "".join(title), None
                if not rest.startswith("!"):
                    raise A1Error(f"unexpected characters after quoted sheet title in {text!r}")
                return "".join(title), rest[1:]
            title.append(ch)
            i += 1
        raise A1Error(f"unterminated quoted sheet title in {text!r}")
    if "!" in text:
        sheet, _, cells = text.partition("!")
        return sheet, cells
    if _CELL_LIKE.match(text):
        raise A1Error(f"range {text!r} has no sheet title — always use 'Sheet'!A1 form")
    return text, None


def _parse_endpoint(text: str) -> tuple[Optional[int], Optional[int]]:
    m = _ENDPOINT.match(text)
    if not m or (m.group(1) is None and m.group(2) is None):
        raise A1Error(f"invalid A1 endpoint: {text!r}")
    col = letters_to_col(m.group(1)) if m.group(1) else None
    row = int(m.group(2)) if m.group(2) else None
    if row is not None and row < 1:
        raise A1Error(f"row must be >= 1 in {text!r}")
    return row, col


def parse_a1(text: str) -> A1Range:
    if not isinstance(text, str) or not text.strip():
        raise A1Error("range must be a non-empty string")
    sheet, cells = _split_sheet(text.strip())
    if not sheet:
        raise A1Error(f"empty sheet title in {text!r}")
    if cells is None:
        return A1Range(sheet_title=sheet)
    if not cells:
        raise A1Error(f"empty cell reference in {text!r}")
    start_txt, sep, end_txt = cells.partition(":")
    start_row, start_col = _parse_endpoint(start_txt)
    if not sep:
        if start_row is None or start_col is None:
            raise A1Error(f"single-endpoint range must be a full cell reference: {text!r}")
        return A1Range(sheet, start_row, start_col, start_row, start_col)
    end_row, end_col = _parse_endpoint(end_txt)
    if start_row is not None and end_row is not None and end_row < start_row:
        raise A1Error(f"range rows are reversed in {text!r}")
    if start_col is not None and end_col is not None and end_col < start_col:
        raise A1Error(f"range columns are reversed in {text!r}")
    # "A:C" style: rows open on both sides; "2:5" style: cols open.
    if start_row is None and end_row is not None:
        start_row = 1
    if start_col is None and end_col is not None:
        start_col = 1
    return A1Range(sheet, start_row, start_col, end_row, end_col)
