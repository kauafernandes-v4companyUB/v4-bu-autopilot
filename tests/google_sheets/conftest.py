"""Synthetic fixtures for the Google Sheets foundation. Every id, title and
value here is fictional — no real spreadsheet is ever contacted."""

from __future__ import annotations

import copy

import pytest

from scripts.lib.google_sheets_transport import FakeGoogleSheetsTransport

CLIENT_ID = "synthtest-sheets"
OTHER_CLIENT_ID = "synthtest-other"
SPREADSHEET_ID = "fake-synthtest-sheet-0001"
OTHER_SPREADSHEET_ID = "fake-synthtest-sheet-9999"
SOURCE_ID = "synthtest-metrics-sheet"
TAB = "Métricas"
Q = "'Métricas'"


@pytest.fixture
def sources_doc() -> dict:
    return {
        "schema_version": "1.0.0",
        "client_id": CLIENT_ID,
        "sources": [
            {
                "source_id": "synthtest-bi", "type": "bi_dashboard_export", "scope": "client",
                "location": "private/clients/synthtest-sheets/bi/x.pdf", "contains_multiple_clients": False,
                "client_selector": None, "canonical": False, "description": "synthetic",
            },
            {
                "source_id": SOURCE_ID, "type": "google_sheet", "scope": "client", "location": None,
                "contains_multiple_clients": False, "client_selector": None, "canonical": False,
                "description": "Synthetic metrics sheet",
                "google_sheet": {
                    "spreadsheet_id": SPREADSHEET_ID, "expected_title": "Synthetic Metrics",
                    "purpose": "metrics", "allowed_tabs": None, "writable": True,
                },
            },
        ],
    }


@pytest.fixture
def other_sources_doc() -> dict:
    return {
        "schema_version": "1.0.0",
        "client_id": OTHER_CLIENT_ID,
        "sources": [{
            "source_id": "synthtest-other-sheet", "type": "google_sheet", "scope": "client", "location": None,
            "contains_multiple_clients": False,
            "google_sheet": {"spreadsheet_id": OTHER_SPREADSHEET_ID, "expected_title": None, "writable": True},
        }],
    }


@pytest.fixture
def transport() -> FakeGoogleSheetsTransport:
    t = FakeGoogleSheetsTransport()
    t.add_spreadsheet(SPREADSHEET_ID, "Synthetic Metrics", {
        TAB: {
            "row_count": 50, "column_count": 10,
            "cells": {
                "A1": "Semana", "B1": "Investimento", "C1": "Leads", "D1": "CPL",
                "A2": "S1", "B2": 100, "C2": 10, "D2": "=IFERROR(B2/C2,0)",
                "A3": "S2", "B3": "", "C3": "", "D3": "=IFERROR(B3/C3,0)",
                "F1": "Total", "F2": "=SUM(B2:B10)",
            },
            "computed": {"D2": 10, "D3": 0, "F2": 100},
            "merges": [{"startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 7}],
            "formats": {"B2": {"numberFormat": {"type": "CURRENCY"}}, "B3": {"numberFormat": {"type": "CURRENCY"}}},
        },
        "Resumo": {"row_count": 20, "column_count": 5, "cells": {"A1": "Total geral", "B1": "='Métricas'!F2"}},
    })
    t.add_spreadsheet(OTHER_SPREADSHEET_ID, "Other Client Sheet", {"Dados": {"cells": {"A1": "x"}}})
    return t


def base_patch(**overrides) -> dict:
    patch = {
        "schema_version": "1.0.0",
        "patch_id": "synthtest-patch-001",
        "client_id": CLIENT_ID,
        "source_id": SOURCE_ID,
        "prepared_by": {"skill": "synthetic-test", "artifact_ref": None, "notes": None},
        "operations": [
            {"op_id": "op-1", "type": "write_value", "range": f"{Q}!B3:C3", "values": [[250, 5]]},
        ],
    }
    patch.update(overrides)
    return copy.deepcopy(patch)


@pytest.fixture
def patch() -> dict:
    return base_patch()
