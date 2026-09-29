"""Deterministic support for skills/document-winning-creative/SKILL.md.

This module never interprets *why* a creative performed — that reasoning is
Claude/Codex following the SKILL.md, and without comparative evidence it may
only be a hypothesis. It only:

- loads the operator's brief (ONE creative the operator declared the winner,
  its metrics, period and optional campaign context) and resolves exactly the
  files the brief names — never other creatives, ad libraries, BI history or
  the internet; client identity is read only when the brief asks for it;
- enforces client isolation on every file (path tree + declared client_id);
- extracts objective asset metadata (size, sha256, image dimensions from the
  file header, operator-provided video duration) and, for video assets named
  in the brief, technical metadata from ffprobe when the environment has it
  (optional capability: never installed, never required), each field with
  its provenance and an operator-vs-ffprobe consistency status;
- normalizes the provided metrics (aliases → canonical keys, absent stays
  NOT_AVAILABLE — never zero) and derives the classic ratios, marked
  DERIVED_METRIC with formula and inputs;
- when the brief carries an operator row-selection rule (MAX_RESULTS), reads
  the per-ad export named in metric_sources, selects the row with the highest
  valid value in the result column (never aggregating rows, never choosing
  on a tie), preserves the export's original result type and extracts the
  selected row's metrics with row/column provenance;
- validates a report against the output schema plus the invariants a JSON
  Schema can't express (metrics carried unchanged, observations tied to a
  loaded asset, performance facts citing real numbers, hypotheses never
  promoted, no causal or comparative language without comparative evidence);
- renders the Markdown view FROM the JSON and writes both, only under
  <workspace>/context/generated/<client_id>/creative-performance/<id>/.

It performs no network I/O and never writes canonical memory, Sheets,
Playbook, eKyte or ad platforms.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import shutil
import struct
import subprocess
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Optional

from scripts.lib.artifact_hash import content_sha256
from scripts.lib.exec_clock import future_timestamp_problem, utc_now_rfc3339

SKILL = "document-winning-creative"
SCHEMA_VERSION = "1.0.0"
ARTIFACT_DIR = "creative-performance"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "skills" / SKILL
OUTPUT_SCHEMA_PATH = SKILL_DIR / "output.schema.json"
INPUT_SCHEMA_PATH = SKILL_DIR / "input.schema.json"

LEARNING_CLASSES = ("OBSERVED_PATTERN", "PERFORMANCE_FACT", "REPLICATION_HYPOTHESIS", "DO_NOT_GENERALIZE")
# Every report must say something about each dimension — OBSERVED, NOT_PRESENT,
# NOT_OBSERVABLE or NOT_APPLICABLE — so gaps are explicit, never silent.
DIMENSIONS = (
    "format", "piece_type", "orientation", "duration", "headline", "main_text", "cta", "offer",
    "product_or_service", "benefit", "promise", "proof", "urgency", "visual_elements", "hierarchy",
    "human_presence", "product_presence", "branding", "style", "narrative_structure", "hook_first_frame",
    "closing", "destination",
)
ELEMENT_STATUS = ("OBSERVED", "NOT_PRESENT", "NOT_OBSERVABLE", "NOT_APPLICABLE")

METRIC_ALIASES = {
    "spend": ("spend", "investimento", "investido", "valor investido", "valor usado", "amount spent", "gasto"),
    "impressions": ("impressions", "impressoes"),
    "reach": ("reach", "alcance"),
    "frequency": ("frequency", "frequencia"),
    "clicks": ("clicks", "cliques", "cliques no link", "link clicks"),
    "ctr": ("ctr",),
    "cpc": ("cpc",),
    "cpm": ("cpm",),
    "messages": ("messages", "mensagens", "conversas iniciadas", "conversations started"),
    "cost_per_message": ("cost per message", "cost_per_message", "custo por mensagem", "custo por conversa"),
    "leads": ("leads",),
    "cpl": ("cpl", "custo por lead"),
    "sql": ("sql", "sqls"),
    "sales": ("sales", "vendas"),
    "revenue": ("revenue", "faturamento", "receita"),
}
STANDARD_METRICS = tuple(METRIC_ALIASES)
# key: (formula, numerator, denominator, multiplier, unit — None = the numerator's unit)
DERIVATIONS = {
    "ctr": ("clicks / impressions * 100", "clicks", "impressions", 100, "percent"),
    "cpc": ("spend / clicks", "spend", "clicks", 1, None),
    "cpm": ("spend / impressions * 1000", "spend", "impressions", 1000, None),
    "frequency": ("impressions / reach", "impressions", "reach", 1, "ratio"),
    "cost_per_message": ("spend / messages", "spend", "messages", 1, None),
    "cpl": ("spend / leads", "spend", "leads", 1, None),
}
CONSISTENCY_TOLERANCE = 0.02  # provided vs derivable value, relative

SOURCE_KINDS = ("creative_asset", "metric_source", "comparative_evidence", "client_identity")
IDENTITY_FILES = ("client.json", "strategy.md")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".pdf": "application/pdf",
        ".txt": "text/plain", ".md": "text/markdown", ".json": "application/json", ".csv": "text/csv"}

# Assertive causal / comparative language. Matched on accent-stripped lowercase
# text. Allowed only in items citing comparative evidence; do_not_generalize,
# unknowns, warnings and the operator's own words are exempt (they describe or
# quote a claim, they don't make it).
CAUSAL_PATTERNS = (
    r"\b(venceu|ganhou|performou|funcionou|converteu|foi (o )?campeao)\b[^.;:]{0,80}\b(porque|pois|devido|gracas|por causa)\b",
    r"\bperformou melhor\b",
    r"\b(devido ao?s?|gracas ao?s?|por causa d[aeo]s?)\b",
    r"\b(causou|causaram|provocou|provocaram)\b",
    r"\b(foi|e|sao|foram) (o |os )?responsave(l|is) (por|pelo|pela)\b",
    r"\bcomprovadamente\b",
    r"\bprov(ou|am|a|ando) que\b",
    r"\b(e|foi|sao|foram) (claramente |muito )?superior(es)?\b",
    r"\b(melhor|pior|superior|inferior)(es)? (que|do que|a|aos|as) (os |as )?(outros|outras|demais)\b",
    r"\bacima da media\b|\babaixo da media\b|\bbenchmark\b",
    r"\b(because|due to|caused|drove|proven|outperform\w*)\b",
)
_CAUSAL = [re.compile(p) for p in CAUSAL_PATTERNS]
CAUSAL_EXEMPT_SECTIONS = ("do_not_generalize", "unknowns", "warnings", "operator_notes", "winner_status",
                          "sources_used", "asset_metadata", "provided_metrics", "derived_metrics", "period", "campaign_context",
                          "metric_row_selection", "post_reference")

# Operator row-selection rules for per-ad exports. The rule is the operator's
# decision about WHICH ROW holds the declared winner's metrics — never a
# statistical claim, never a change to winner_status.
ROW_SELECTION_RULES = ("MAX_RESULTS",)
# Friendly labels for export result-type identifiers. Additive only: the
# original identifier is always kept in source_result_type.
RESULT_TYPE_LABELS = (
    (r"^actions:onsite_conversion\.messaging_conversation_started_\w+$", "conversa por mensagem iniciada", "HIGH"),
    (r"^(conversions|actions):contact_website$", "contato pelo site", "HIGH"),
    (r"^actions:offsite_conversion\.fb_pixel_lead$", "lead (pixel)", "HIGH"),
    (r"^actions:(offsite_conversion\.fb_pixel_purchase|omni_purchase)$", "compra", "HIGH"),
    (r"^(profile_visit_view|total_profile_visits)$", "visita ao perfil", "HIGH"),
    (r"^actions:omni_landing_page_view$", "visualização da página de destino", "HIGH"),
    (r"^actions:post_engagement$", "engajamento com a publicação", "HIGH"),
    (r"^reach$", "alcance", "HIGH"),
    (r"^actions:offsite_conversion\.custom\.\d+$", "conversão personalizada", "MEDIUM"),
    (r"^conversions:offsite_conversion\.fb_pixel_custom\..+$", "conversão personalizada (pixel)", "MEDIUM"),
)
_EMPTY_CELLS = {"", "-", "–", "—"}

# Technical video metadata (asset_metadata[].technical_metadata). Sources:
# OPERATOR_PROVIDED (brief), FFPROBE (measured), DERIVED (computed from the
# others), NOT_AVAILABLE. FILE_HEADER stays the image-dimension basis.
VIDEO_TECH_FIELDS = ("duration_seconds", "width", "height", "frame_rate", "video_codec", "audio_codec", "audio_channels", "audio_sample_rate")
FFPROBE_TIMEOUT_S = 30
# Operator vs ffprobe agreement. Duration: ±0.5 s or ±1 % (operators round to
# whole seconds). Frame rate: ±0.05 fps (29.97 ≈ 30 is the same cadence
# family). Everything else: exact (codecs case-insensitive).
_TECH_TOLERANCE = {
    "duration_seconds": lambda a, b: abs(a - b) <= max(0.5, 0.01 * max(abs(a), abs(b))),
    "frame_rate": lambda a, b: abs(a - b) <= 0.05,
    "video_codec": lambda a, b: str(a).lower() == str(b).lower(),
    "audio_codec": lambda a, b: str(a).lower() == str(b).lower(),
}
ENV_WARNING_PREFIXES = ("FFPROBE_UNAVAILABLE", "FFPROBE_FAILED", "METADATA_INCONSISTENT")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class CreativePerformanceError(ValueError):
    pass


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).strip()


_ALIAS_INDEX = {_fold(a): k for k, aliases in METRIC_ALIASES.items() for a in aliases}


def canonical_metric_key(label: str) -> tuple[str, Optional[str]]:
    """(metric_key, canonical_metric). Unknown labels become a custom slug
    with canonical_metric None — kept, never dropped."""
    folded = _fold(label)
    if folded in _ALIAS_INDEX:
        return _ALIAS_INDEX[folded], _ALIAS_INDEX[folded]
    slug = re.sub(r"[^a-z0-9]+", "_", folded).strip("_") or "metric"
    return slug, None


# ---------------------------------------------------------------------------
# asset metadata (file header only — no decoding, no external tools)
# ---------------------------------------------------------------------------


def image_dimensions(data: bytes) -> Optional[tuple[int, int]]:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L" and len(data) >= 25:
            b = data[21:25]
            return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        return None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
                i += 2 if marker != 0xFF else 1
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + seg_len
    return None


def _orientation(w: Optional[int], h: Optional[int]) -> tuple[Optional[str], Optional[str]]:
    if not w or not h:
        return None, None
    g = math.gcd(w, h)
    return ("square" if w == h else "landscape" if w > h else "portrait"), f"{w // g}:{h // g}"


def _rate(text: Optional[str]) -> Optional[float]:
    if not text or "/" not in text:
        return None
    num, den = text.split("/", 1)
    try:
        return round(int(num) / int(den), 3) if int(den) and int(num) else None
    except ValueError:
        return None


def parse_ffprobe_json(data: dict) -> dict:
    """Only the fields ffprobe actually reported — absent stays absent."""
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    out: dict[str, Any] = {}
    if video:
        for key, src in (("width", "width"), ("height", "height")):
            if isinstance(video.get(src), int) and video[src] > 0:
                out[key] = video[src]
        if video.get("codec_name"):
            out["video_codec"] = video["codec_name"]
        rate = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
        if rate:
            out["frame_rate"] = rate
        for sd in video.get("side_data_list") or []:
            if "rotation" in sd:
                out["rotation"] = int(sd["rotation"])
    duration = parse_cell_number(str((video or {}).get("duration") or (data.get("format") or {}).get("duration") or ""))
    if duration:
        out["duration_seconds"] = round(duration, 3)
    if audio:
        if audio.get("codec_name"):
            out["audio_codec"] = audio["codec_name"]
        if isinstance(audio.get("channels"), int):
            out["audio_channels"] = audio["channels"]
        if str(audio.get("sample_rate") or "").isdigit():
            out["audio_sample_rate"] = int(audio["sample_rate"])
    return out


def ffprobe_probe(path: Path) -> dict:
    """{status, tool_version, values}. Optional capability: a missing or
    failing ffprobe never raises. Arguments are passed as a list (no shell)."""
    exe = shutil.which("ffprobe")
    if not exe:
        return {"status": "FFPROBE_UNAVAILABLE", "tool_version": None, "values": {}}
    cmd = [exe, "-v", "error", "-show_entries",
           "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels,duration"
           ":stream_side_data=rotation", "-of", "json", str(Path(path).resolve())]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=FFPROBE_TIMEOUT_S, check=False)
        ver = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=FFPROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": "FFPROBE_FAILED", "tool_version": None, "values": {}, "error": type(e).__name__}
    if run.returncode != 0:
        return {"status": "FFPROBE_FAILED", "tool_version": None, "values": {}, "error": f"exit {run.returncode}"}
    try:
        values = parse_ffprobe_json(json.loads(run.stdout or "{}"))
    except json.JSONDecodeError:
        return {"status": "FFPROBE_FAILED", "tool_version": None, "values": {}, "error": "invalid JSON"}
    first = (ver.stdout or "").splitlines()[:1]
    return {"status": "OK", "tool_version": " ".join(first[0].split()[:3]) if first else None, "values": values}


def build_technical_metadata(base: dict, operator: dict, probe: dict) -> tuple[dict, list[str]]:
    """Asset metadata with technical_metadata merged in. Precedence: an
    operator value is never overwritten — ffprobe confirms it (CONFIRMED) or
    contradicts it (METADATA_INCONSISTENT, both values kept); ffprobe fills
    only what the operator did not provide."""
    meta = json.loads(json.dumps(base))
    ok = probe.get("status") == "OK"
    measured = probe.get("values", {}) if ok else {}
    fields, warnings = {}, []
    for f in VIDEO_TECH_FIELDS:
        op, fp = operator.get(f), measured.get(f)
        if op is None and fp is None:
            fields[f] = {"value": None, "source": "NOT_AVAILABLE", "operator_value": None, "ffprobe_value": None, "status": "NOT_AVAILABLE"}
        elif op is None:
            fields[f] = {"value": fp, "source": "FFPROBE", "operator_value": None, "ffprobe_value": fp, "status": "SINGLE_SOURCE"}
        elif fp is None:
            fields[f] = {"value": op, "source": "OPERATOR_PROVIDED", "operator_value": op, "ffprobe_value": None, "status": "SINGLE_SOURCE"}
        else:
            same = _TECH_TOLERANCE.get(f, lambda a, b: a == b)(op, fp)
            fields[f] = {"value": op, "source": "OPERATOR_PROVIDED", "operator_value": op, "ffprobe_value": fp,
                         "status": "CONFIRMED" if same else "METADATA_INCONSISTENT"}
            if not same:
                warnings.append(f"METADATA_INCONSISTENT: {base['asset_id']} {f} operator={op} ffprobe={fp} — both kept, operator value not overwritten")
    w, h = fields["width"]["value"], fields["height"]["value"]
    rotation = measured.get("rotation", 0)
    disp_w, disp_h = (h, w) if rotation % 180 else (w, h)
    orientation, aspect = _orientation(disp_w, disp_h)
    fields["orientation"] = {"value": orientation, "source": "DERIVED" if orientation else "NOT_AVAILABLE", "derived_from": ["width", "height", "rotation"]}
    fields["aspect_ratio"] = {"value": aspect, "source": "DERIVED" if aspect else "NOT_AVAILABLE", "derived_from": ["width", "height", "rotation"]}
    meta["technical_metadata"] = {
        "probe": {"tool": "ffprobe", "status": probe.get("status"), "tool_version": probe.get("tool_version") if ok else None,
                  "probed_sha256": base["sha256"] if ok else None, "values": measured},
        "fields": fields,
    }
    # legacy top-level fields: filled from ffprobe only where the operator gave nothing
    if meta["width"] is None and fields["width"]["source"] == "FFPROBE" and fields["height"]["source"] == "FFPROBE":
        meta.update(width=w, height=h, dimensions_basis="ffprobe")
    if meta["width"] is not None:
        meta["orientation"], meta["aspect_ratio"] = orientation, aspect
    if meta["duration_seconds"] is None and fields["duration_seconds"]["source"] == "FFPROBE":
        meta.update(duration_seconds=fields["duration_seconds"]["value"], duration_basis="ffprobe")
    return meta, warnings


# ---------------------------------------------------------------------------
# context (brief + only the files it names)
# ---------------------------------------------------------------------------


def _check_id(value: str, what: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise CreativePerformanceError(f"unsafe {what} {value!r} (lowercase letters, digits, '.', '_', '-')")


def _client_trees(client_id: str) -> tuple[str, ...]:
    return (f"clients/{client_id}/", f"context/generated/{client_id}/", f"private/clients/{client_id}/")


def _owner_of(rel: str) -> Optional[str]:
    """client_id whose tree contains `rel`, or None."""
    for prefix in ("clients/", "context/generated/", "private/clients/"):
        if rel.startswith(prefix):
            rest = rel[len(prefix):]
            return rest.split("/", 1)[0] if "/" in rest else None
    return None


def _resolve(root: Path, rel: str, client_id: str) -> tuple[Path, str]:
    """(absolute path, status) — status 'ok' or 'rejected_other_client'.
    Anything outside the workspace or outside every client tree raises."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel) or "\\" in rel:
        raise CreativePerformanceError(f"path {rel!r} must be workspace-relative (POSIX separators)")
    parts = rel.split("/")
    if ".." in parts or "" in parts or "." in parts:
        raise CreativePerformanceError(f"unsafe path {rel!r}")
    p = (root / rel).resolve()
    if root.resolve() not in p.parents:
        raise CreativePerformanceError(f"path {rel!r} escapes the workspace")
    owner = _owner_of(rel)
    if owner is None:
        raise CreativePerformanceError(f"path {rel!r} is not inside a client tree ({', '.join(_client_trees(client_id))})")
    return p, ("ok" if owner == client_id else "rejected_other_client")


def _json_client_id(p: Path) -> Any:
    if p.suffix.lower() != ".json":
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data.get("client_id") if isinstance(data, dict) else None


def _num(value: float) -> float:
    return round(float(value), 4)


def normalize_metrics(brief_metrics: list[dict], source_ids: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """(provided, derived, not_available, warnings). `source_ids` maps a
    metric-source path to its context source entry."""
    provided, seen, warnings = [], {}, []
    for i, m in enumerate(brief_metrics):
        key, canonical = canonical_metric_key(m["metric"])
        if key in seen:
            raise CreativePerformanceError(f"metric {m['metric']!r} duplicates {seen[key]!r} (both normalize to {key!r}) — provide it once")
        seen[key] = m["metric"]
        value, status, note = m.get("value"), "PROVIDED", m.get("note")
        src = m.get("source", "operator")
        provenance = "operator_input"
        if src != "operator":
            s = source_ids.get(src)
            if s is None:
                raise CreativePerformanceError(f"metric {m['metric']!r} cites source {src!r} which is not in metric_sources")
            provenance = s["source_id"]
            if s["status"] != "loaded":
                value, note = None, f"source {s['source_id']} is {s['status']} — value not used"
        if value is None:
            status = "NOT_AVAILABLE"
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or not math.isfinite(value):
            raise CreativePerformanceError(f"metric {m['metric']!r} value must be a non-negative number or null (got {value!r})")
        record = {"metric_id": f"M-{i + 1:02d}", "metric_key": key, "canonical_metric": canonical, "label": m["metric"],
                  "value": value, "unit": m.get("unit", "unknown"), "status": status, "classification": "METRIC",
                  "provenance": provenance, "note": note}
        for k in ("source_row", "source_column", "result_type"):  # only for metrics extracted from a selected export row
            if k in m:
                record[k] = m[k]
        provided.append(record)
    by_key = {p["metric_key"]: p for p in provided if p["value"] is not None}
    derived = []
    for key, (formula, num, den, mult, unit) in DERIVATIONS.items():
        n, d = by_key.get(num), by_key.get(den)
        if not n or not d or d["value"] == 0:
            continue
        value = _num(n["value"] / d["value"] * mult)
        if key in by_key:
            given = by_key[key]["value"]
            if abs(given - value) > CONSISTENCY_TOLERANCE * max(abs(value), 1e-9):
                warnings.append(f"METRIC_INCONSISTENT: provided {key}={given} differs from {formula} = {value} — both kept, neither corrected")
            continue
        derived.append({"metric_id": f"D-{len(derived) + 1:02d}", "metric_key": key, "value": value,
                        "unit": unit or n["unit"], "classification": "DERIVED_METRIC", "formula": formula,
                        "inputs": [n["metric_id"], d["metric_id"]]})
    have = set(by_key) | {d["metric_key"] for d in derived}
    not_available = [{"metric_key": k, "status": "NOT_AVAILABLE"} for k in STANDARD_METRICS if k not in have]
    return provided, derived, not_available, warnings


def parse_cell_number(cell: Optional[str]) -> Optional[float]:
    """Number in an export cell, or None when empty/invalid (never 0).
    Plain decimals first (Meta exports: 12.74416667); pt-BR (1.234,56) as fallback."""
    text = (cell or "").strip()
    if text in _EMPTY_CELLS:
        return None
    try:
        value = float(text)
    except ValueError:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d+|-?\d+,\d+", text):
            value = float(text.replace(".", "").replace(",", "."))
        else:
            return None
    return value if math.isfinite(value) else None


def describe_result_type(result_type: Optional[str]) -> dict:
    """Original identifier (or UNKNOWN) plus an optional friendly label."""
    rt = (result_type or "").strip()
    if not rt:
        return {"source_result_type": "UNKNOWN", "normalized_label": None, "normalization_confidence": None}
    for rx, label, confidence in RESULT_TYPE_LABELS:
        if re.match(rx, rt):
            return {"source_result_type": rt, "normalized_label": label, "normalization_confidence": confidence}
    return {"source_result_type": rt, "normalized_label": None, "normalization_confidence": None}


def _read_export(p: Path) -> tuple[list[str], list[tuple[int, dict]]]:
    """(columns, [(row_number, row)]) — row_number is the line in the file
    where the record ends (header = line 1)."""
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise CreativePerformanceError(f"{p.name}: export is not UTF-8 ({e}) — re-export as UTF-8") from e
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [(reader.line_num, row) for row in reader]
    return list(reader.fieldnames or []), rows


def select_metric_row(root: Path, request: dict, source: dict) -> tuple[dict, list[dict], list[dict], list[str]]:
    """Apply the operator's MAX_RESULTS rule to one per-ad export.
    Returns (selection, candidates, row_metrics, warnings). Never aggregates
    rows; on a tie selected_row stays None unless the operator confirmed one
    of the tied rows (confirmed_row_number)."""
    if request["rule"] not in ROW_SELECTION_RULES:
        raise CreativePerformanceError(f"unsupported row-selection rule {request['rule']!r}")
    if source["status"] != "loaded":
        raise CreativePerformanceError(f"row-selection source {source['source_id']} is {source['status']}")
    columns, rows = _read_export(root / source["path"])
    names = {k: request.get(k) for k in ("column", "result_type_column", "ad_name_column", "ad_set_name_column", "campaign_name_column")}
    wanted = [c for c in list(names.values()) + [m["column"] for m in request.get("metric_columns", [])] if c]
    missing = [c for c in wanted if c not in columns]
    if missing:
        raise CreativePerformanceError(f"ROW_SELECTION_COLUMN_MISSING: {missing} not in {source['path']}")
    cell = lambda row, key: (row.get(names[key]) or "").strip() if names[key] else None  # noqa: E731

    candidates, excluded = [], []
    for line, row in rows:
        value = parse_cell_number(row.get(names["column"]))
        ad_name = cell(row, "ad_name_column")
        cand = {"row_number": line, "ad_name": ad_name or None, "ad_set_name": cell(row, "ad_set_name_column") or None,
                "campaign_name": cell(row, "campaign_name_column") or None, "value": value,
                "result_type": cell(row, "result_type_column") or None}
        if value is None:
            excluded.append({"row_number": line, "reason": "EMPTY_OR_INVALID_RESULT"})
        elif names["ad_name_column"] and not ad_name:
            excluded.append({"row_number": line, "reason": "SUMMARY_ROW_WITHOUT_AD_NAME"})
            cand["value"] = None
        candidates.append(cand)
    valid = [c for c in candidates if c["value"] is not None]
    if not valid:
        raise CreativePerformanceError(f"ROW_SELECTION_NO_VALID_VALUE: column {names['column']!r} has no valid value")
    top = max(c["value"] for c in valid)
    tied_rows = [c["row_number"] for c in valid if c["value"] == top]
    tied = len(tied_rows) > 1
    confirmed = request.get("confirmed_row_number")
    if confirmed is not None and confirmed not in tied_rows:
        raise CreativePerformanceError(f"confirmed_row_number {confirmed} is not a maximum row {tied_rows} — MAX_RESULTS cannot select it")
    if confirmed is not None and not tied:
        raise CreativePerformanceError("confirmed_row_number is only for resolving a RESULT_TIE")
    chosen = next(c for c in valid if c["row_number"] == (confirmed if tied else tied_rows[0])) if (not tied or confirmed is not None) else None
    below = sorted({c["value"] for c in valid if c["value"] < top}, reverse=True)
    types = sorted({c["result_type"] for c in valid if c["result_type"]})
    warnings = []
    if len(types) > 1:
        warnings.append(f"HETEROGENEOUS_RESULT_TYPES: {types} — O operador definiu MAX_RESULTS como regra de seleção deste pacote; "
                        "valores de tipos diferentes não são tratados como semanticamente comparáveis.")
    if tied and chosen is None:
        warnings.append(f"RESULT_TIE: rows {tied_rows} share the maximum {top:g} in {names['column']!r} — operator must confirm one (confirmed_row_number)")
    selected = None
    if chosen:
        selected = {"row_number": chosen["row_number"], "ad_name": chosen["ad_name"], "ad_set_name": chosen["ad_set_name"],
                    "campaign_name": chosen["campaign_name"],
                    "result": {"value": chosen["value"], "source_metric_name": names["column"], **describe_result_type(chosen["result_type"])}}
    selection = {
        "rule": request["rule"], "source": "OPERATOR_RULE", "source_id": source["source_id"], "source_path": source["path"],
        "column": names["column"], "result_type_column": names["result_type_column"], "ad_name_column": names["ad_name_column"],
        "ad_set_name_column": names["ad_set_name_column"], "campaign_name_column": names["campaign_name_column"],
        "selected_row": selected, "candidate_count": len(valid), "excluded_rows": excluded,
        "tied": tied, "tied_rows": tied_rows if tied else [], "tie_resolution": "OPERATOR_CONFIRMED" if tied and chosen else None,
        "same_ad_name_rows": [c["row_number"] for c in candidates if chosen and chosen["ad_name"] and c["ad_name"] == chosen["ad_name"]
                              and c["row_number"] != chosen["row_number"]],
        "aggregated": False, "result_types_found": types, "next_highest_value": below[0] if below else None,
        "notes": request.get("notes"),
    }
    row_metrics = []
    if chosen:
        raw = dict(rows[[line for line, _ in rows].index(chosen["row_number"])][1])
        row_metrics.append({"metric": names["column"], "value": chosen["value"], "unit": "count", "source": source["path"],
                            "note": f"row {chosen['row_number']}", "source_row": chosen["row_number"], "source_column": names["column"],
                            "result_type": selected["result"]["source_result_type"]})
        for m in request.get("metric_columns", []):
            row_metrics.append({"metric": m["metric"], "value": parse_cell_number(raw.get(m["column"])), "unit": m.get("unit", "unknown"),
                                "source": source["path"], "note": f"row {chosen['row_number']}",
                                "source_row": chosen["row_number"], "source_column": m["column"]})
    return selection, candidates, row_metrics, warnings


def source_trace(context: dict, metric_refs: list[str]) -> list[dict]:
    """Traceability entries (metric → source file, row, column, result type)
    for the row-extracted metrics among `metric_refs`."""
    by_id = {m["metric_id"]: m for m in context["provided_metrics"]}
    return [{"metric_ref": r, "source_id": by_id[r]["provenance"], "source_row": by_id[r]["source_row"],
             "source_column": by_id[r]["source_column"], "result_type": by_id[r].get("result_type")}
            for r in metric_refs if r in by_id and "source_row" in by_id[r]]


def load_context(workspace_root: Path, brief: dict, *, input_validator=None, probe=None) -> dict:
    """Creative Context: the brief normalized plus exactly the files it names,
    each marked loaded / missing / rejected_other_client. Nothing else in the
    client's workspace is read. `probe` (default: ffprobe_probe) is called only
    for loaded video assets named in the brief."""
    probe = probe or ffprobe_probe
    if input_validator is not None:
        errs = [f"brief {list(e.path)}: {e.message}" for e in sorted(input_validator.iter_errors(brief), key=lambda e: list(e.path))]
        if errs:
            raise CreativePerformanceError("invalid brief:\n- " + "\n- ".join(errs))
    cid = brief["client_id"]
    _check_id(cid, "client_id")
    _check_id(brief["creative_id"], "creative_id")
    root = Path(workspace_root)
    if not (root / "clients" / cid).is_dir():
        raise CreativePerformanceError(f"client {cid!r} has no canonical memory directory in this workspace")
    period = {"start_date": None, "end_date": None, "label": None, **(brief.get("period") or {})}
    if period["start_date"] and period["end_date"] and date.fromisoformat(period["end_date"]) < date.fromisoformat(period["start_date"]):
        raise CreativePerformanceError("period end_date is before start_date")

    sources: list[dict] = []

    def add(rel: str, kind: str, declared_client: Any = None) -> dict:
        p, status = _resolve(root, rel, cid)
        if status == "ok" and not p.is_file():
            status = "missing"
        if status == "ok":
            file_client = _json_client_id(p)
            status = "rejected_other_client" if any(c not in (None, cid) for c in (declared_client, file_client)) else "loaded"
        entry = {"source_id": f"S-{len(sources) + 1:02d}", "path": rel, "kind": kind, "status": status,
                 "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if status == "loaded" else None}
        sources.append(entry)
        return entry

    assets, probe_inputs, tech_warnings_all = [], [], []
    for i, a in enumerate(brief["assets"]):
        tech_warnings = []
        s = add(a["path"], "creative_asset", a.get("client_id"))
        meta = {"asset_id": f"A-{i + 1:02d}", "source_id": s["source_id"], "path": a["path"], "kind": a["kind"], "status": s["status"],
                "description": a.get("description"), "mime_type": MIME.get(Path(a["path"]).suffix.lower()), "bytes": None, "sha256": s["sha256"],
                "width": None, "height": None, "orientation": None, "aspect_ratio": None, "dimensions_basis": "not_available",
                "duration_seconds": None, "duration_basis": "not_available"}
        if s["status"] == "loaded":
            p = root / a["path"]
            meta["bytes"] = p.stat().st_size
            if a["kind"] == "image":
                with p.open("rb") as fh:
                    dims = image_dimensions(fh.read(1 << 20))
                if dims:
                    meta.update(width=dims[0], height=dims[1], dimensions_basis="file_header")
        if meta["width"] is None and a.get("width") and a.get("height"):
            meta.update(width=a["width"], height=a["height"], dimensions_basis="operator_provided")
        meta["orientation"], meta["aspect_ratio"] = _orientation(meta["width"], meta["height"])
        if a.get("duration_seconds") is not None:
            meta.update(duration_seconds=a["duration_seconds"], duration_basis="operator_provided")
        if a["kind"] == "video" and s["status"] == "loaded":
            operator = {f: a.get(f) for f in VIDEO_TECH_FIELDS}
            probe_inputs.append({"asset_id": meta["asset_id"], "base": json.loads(json.dumps(meta)), "operator": operator})
            result = probe(root / a["path"])
            meta, tech_warnings = build_technical_metadata(meta, operator, result)
            if result.get("status") != "OK":
                tech_warnings.append(f"{result.get('status')}: {meta['asset_id']} — technical video metadata not measured in this environment (optional capability)")
        assets.append(meta)
        tech_warnings_all += tech_warnings
    metric_sources = {m["path"]: add(m["path"], "metric_source", m.get("client_id")) for m in brief.get("metric_sources", [])}
    comparative = [add(c["path"], "comparative_evidence", c.get("client_id")) for c in brief.get("comparative_evidence", [])]
    identity_loaded = bool(brief.get("load_client_identity"))
    if identity_loaded:
        for name in IDENTITY_FILES:
            add(f"clients/{cid}/{name}", "client_identity")

    selection, candidates, row_metrics, row_warnings = None, [], [], []
    request = brief.get("metric_row_selection")
    if request:
        if request["source_path"] not in metric_sources:
            raise CreativePerformanceError("metric_row_selection.source_path must be one of metric_sources")
        selection, candidates, row_metrics, row_warnings = select_metric_row(root, request, metric_sources[request["source_path"]])
    post_reference = None
    if brief.get("post_reference"):
        url = brief["post_reference"]["url"]
        if not re.match(r"^https?://\S+$", url):
            raise CreativePerformanceError(f"post_reference.url {url!r} is not an http(s) URL")
        post_reference = {"url": url, "source": "OPERATOR_PROVIDED", "metric_row_match_required": False, "opened": False,
                          "note": brief["post_reference"].get("note")}

    provided, derived, not_available, warnings = normalize_metrics(row_metrics + brief.get("metrics", []), metric_sources)
    warnings = row_warnings + tech_warnings_all + warnings
    if not any(a["status"] == "loaded" for a in assets):
        warnings.append("NO_LOADED_ASSET: no creative file could be loaded — every element must stay NOT_OBSERVABLE")
    for s in sources:
        if s["status"] != "loaded":
            warnings.append(f"SOURCE_{s['status'].upper()}: {s['source_id']} {s['path']}")
    required_unknowns = [f"metric:{m['metric_key']}" for m in not_available]
    if not (period["start_date"] and period["end_date"]):
        required_unknowns.append("period")

    decl = brief["winner_declaration"]
    context = {
        "schema_version": SCHEMA_VERSION, "artifact": "creative-context", "skill": SKILL, "client_id": cid, "creative_id": brief["creative_id"],
        "observed_at": utc_now_rfc3339(),
        "winner_status": {"source": "OPERATOR_DECLARED", "declared_by": decl.get("declared_by", "operator"), "statement": decl["statement"],
                          "statistically_compared": False},
        "period": period, "campaign_context": brief.get("campaign_context"),
        "operator_notes": [{"id": f"OP-{i + 1:02d}", "text": t} for i, t in enumerate(brief.get("operator_instructions", []))],
        "sources": sources, "assets": assets, "asset_probe_inputs": probe_inputs,
        "comparative_evidence_ids": [c["source_id"] for c in comparative if c["status"] == "loaded"],
        "metric_row_selection": selection, "row_candidates": candidates, "post_reference": post_reference,
        "provided_metrics": provided, "derived_metrics": derived, "metrics_not_available": not_available,
        "required_unknowns": required_unknowns, "warnings": warnings,
        "loaded": {"client_identity": identity_loaded},
        "not_read": ["other creatives of the client", "ad libraries / internet", "BI history beyond the metric_sources named in the brief",
                     "account plan", "other clients", "any file not named in the brief"] + ([] if identity_loaded else ["client identity (not requested)"]),
    }
    context["context_sha256"] = content_sha256({k: v for k, v in context.items() if k != "observed_at"})
    return context


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def _strings(obj: Any, path: str):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def causal_hits(text: str) -> list[str]:
    folded = _fold(text)
    return [m.group(0) for rx in _CAUSAL for m in [rx.search(folded)] if m]


def _numbers(text: str) -> list[tuple[float, int]]:
    """(value, decimals) of each number in `text`, ignoring dates. Accepts
    pt-BR (1.234,5) and plain (1234.5) notation."""
    out = []
    for m in _NUMBER.finditer(_ISO_DATE.sub(" ", text)):
        tok = m.group(0)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", tok):
            tok = tok.replace(".", "").replace(",", ".")
        else:
            tok = tok.replace(",", ".")
        out.append((float(tok), len(tok.split(".")[1]) if "." in tok else 0))
    return out


def _number_matches(n: float, decimals: int, value: float) -> bool:
    return abs(value - n) <= 0.5 * 10 ** -decimals + 1e-9


def learning_counts(report: dict) -> dict:
    return {"OBSERVED_PATTERN": sum(1 for e in report.get("observed_elements", []) if e.get("status") == "OBSERVED"),
            "PERFORMANCE_FACT": len(report.get("performance_summary", [])),
            "REPLICATION_HYPOTHESIS": len(report.get("replication_hypotheses", [])),
            "DO_NOT_GENERALIZE": len(report.get("do_not_generalize", []))}


def _validate_row_selection(report: dict, context: dict) -> list[str]:
    """The operator's row rule, re-checked against the export rows parsed in
    the context — never trusted from the report."""
    ctx_sel, sel = context.get("metric_row_selection"), report.get("metric_row_selection")
    if ctx_sel is None:
        return ["ROW_SELECTION_UNEXPECTED: the brief has no metric_row_selection"] if sel is not None else []
    if sel is None:
        return ["ROW_SELECTION_MISSING: the brief selects a metric row; the report must carry metric_row_selection"]
    issues = []
    if sel["column"] != ctx_sel["column"]:
        issues.append(f"ROW_SELECTION_COLUMN_MISSING: column {sel['column']!r} is not the export column the rule was applied to")
    rows = {c["row_number"]: c for c in context["row_candidates"]}
    valid = [c["value"] for c in context["row_candidates"] if c["value"] is not None]
    top = max(valid) if valid else None
    at_top = [n for n, c in rows.items() if c["value"] is not None and c["value"] == top]
    if len(at_top) > 1 and sel.get("tie_resolution") != "OPERATOR_CONFIRMED":
        issues.append(f"RESULT_TIE: rows {at_top} share the maximum {top:g} — MAX_RESULTS never chooses on a tie; the operator must confirm one")
    chosen = sel.get("selected_row")
    if chosen is None:
        if len(at_top) <= 1:
            issues.append("ROW_SELECTION_ROW_NOT_FOUND: no selected_row although the maximum is unique")
    elif chosen["row_number"] not in rows:
        issues.append(f"ROW_SELECTION_ROW_NOT_FOUND: row {chosen['row_number']} does not exist in the export")
    else:
        real = rows[chosen["row_number"]]
        if real["value"] is None or chosen["result"]["value"] != real["value"]:
            issues.append(f"ROW_SELECTION_VALUE_MISMATCH: result value {chosen['result']['value']} != row {chosen['row_number']} value {real['value']} "
                          "(rows are never aggregated)")
        elif top is not None and real["value"] < top:
            issues.append(f"ROW_SELECTION_NOT_MAX: row {chosen['row_number']} ({real['value']:g}) is below the maximum {top:g} of {sel['column']!r}")
        if (chosen["ad_name"], chosen["ad_set_name"], chosen["campaign_name"]) != (real["ad_name"], real["ad_set_name"], real["campaign_name"]):
            issues.append(f"ROW_SELECTION_FIELD_MISMATCH: ad/ad set/campaign differ from row {chosen['row_number']}")
        if chosen["result"]["source_result_type"] != (real["result_type"] or "UNKNOWN"):
            issues.append("RESULT_TYPE_ALTERED: source_result_type must be the export's original identifier")
    if not issues and sel != ctx_sel:
        issues.append("ROW_SELECTION_ALTERED: metric_row_selection must equal the selection computed from the export")
    return issues


def _validate_assets(report: dict, context: dict) -> list[str]:
    """asset_metadata must equal what the files give. For video technical
    metadata the check is replica-portable: where ffprobe runs now, the
    report must match the fresh measurement; where it doesn't, the report's
    recorded ffprobe answer (bound to the file's sha256) is re-derived with
    the same deterministic rules. A report without technical metadata (made
    before 1.2.0 or without ffprobe) stays valid."""
    issues = []
    rep_assets, ctx_assets = report["asset_metadata"], context["assets"]
    if [a.get("asset_id") for a in rep_assets] != [a["asset_id"] for a in ctx_assets]:
        return ["ASSET_METADATA_ALTERED: asset_metadata must list exactly the brief's assets"]
    inputs = {x["asset_id"]: x for x in context.get("asset_probe_inputs", [])}
    for rep, ctx in zip(rep_assets, ctx_assets):
        if rep == ctx:
            ok = True
        elif rep["asset_id"] not in inputs:
            ok = False
        else:
            base, operator = inputs[rep["asset_id"]]["base"], inputs[rep["asset_id"]]["operator"]
            tm = rep.get("technical_metadata")
            ctx_probe_ok = ctx["technical_metadata"]["probe"]["status"] == "OK"
            if tm is None:
                ok = rep == base  # legacy report: no technical metadata at all
            elif ctx_probe_ok and tm["probe"]["status"] == "OK":
                ok = False  # measured here and now: must equal the fresh measurement (rep != ctx)
            else:
                recorded = {"status": tm["probe"]["status"], "tool_version": tm["probe"]["tool_version"], "values": tm["probe"]["values"]}
                bound = tm["probe"]["status"] != "OK" or tm["probe"]["probed_sha256"] == base["sha256"]
                expected, expected_warnings = build_technical_metadata(base, operator, recorded)
                ok = bound and rep == expected
                missing = [w for w in expected_warnings if w not in report["warnings"]]
                if ok and missing:
                    issues.append(f"WARNING_DROPPED: {missing}")
        if not ok:
            issues.append(f"ASSET_METADATA_ALTERED: {rep['asset_id']} must equal the metadata extracted from the file (technical metadata re-derived from its recorded ffprobe answer)")
        tm = rep.get("technical_metadata")
        if ok and tm and rep == ctx:
            _, expected_warnings = build_technical_metadata(inputs[rep["asset_id"]]["base"], inputs[rep["asset_id"]]["operator"],
                                                            {"status": tm["probe"]["status"], "tool_version": tm["probe"]["tool_version"], "values": tm["probe"]["values"]})
            missing = [w for w in expected_warnings if w not in report["warnings"]]
            if missing:
                issues.append(f"WARNING_DROPPED: {missing}")
    return issues


def validate_report(report: dict, context: dict, *, schema_validator=None) -> list[str]:
    """Schema (when a validator is given) + invariants. Empty list = valid."""
    issues: list[str] = []
    if schema_validator is not None:
        issues += [f"schema {list(e.path)}: {e.message}" for e in sorted(schema_validator.iter_errors(report), key=lambda e: list(e.path))]
        if issues:
            return issues
    cid = context["client_id"]
    if report["client_id"] != cid:
        return [f"CLIENT_ISOLATION: report client_id {report['client_id']!r} != context client_id {cid!r}"]
    if report["creative_id"] != context["creative_id"]:
        issues.append("CREATIVE_MISMATCH: creative_id differs from the brief")
    problem = future_timestamp_problem(report["generated_at"])
    if problem:
        issues.append(f"EXECUTION_TIMESTAMP_IN_FUTURE: {problem}")
    for key in ("winner_status", "period", "campaign_context", "operator_notes"):
        if report[key] != context[key]:
            issues.append(f"INPUT_ALTERED: {key} must be carried exactly as the operator provided it")

    # sources: only this brief's loaded files; every loaded asset/metric source is listed
    ctx_sources = {s["source_id"]: s for s in context["sources"]}
    used = set()
    for s in report["sources_used"]:
        cs = ctx_sources.get(s["source_id"])
        if cs is None or cs["path"] != s["path"]:
            issues.append(f"UNKNOWN_SOURCE: {s['source_id']} {s['path']!r} is not a file named in the brief")
        elif cs["status"] != "loaded":
            issues.append(f"UNUSABLE_SOURCE: {s['source_id']} has status {cs['status']!r}")
        else:
            used.add(s["source_id"])
    for cs in context["sources"]:
        if cs["status"] == "loaded" and cs["kind"] in ("creative_asset", "metric_source") and cs["source_id"] not in used:
            issues.append(f"SOURCE_NOT_RECORDED: {cs['source_id']} {cs['path']!r} was loaded and must appear in sources_used")

    # objective data carried unchanged
    issues += _validate_assets(report, context)
    if report["provided_metrics"] != context["provided_metrics"]:
        issues.append("METRICS_ALTERED: provided_metrics must equal the normalized brief (absent stays NOT_AVAILABLE, never 0)")
    if report["derived_metrics"] != context["derived_metrics"]:
        issues.append("DERIVED_METRICS_ALTERED: derived_metrics must equal the deterministic derivation")

    issues += _validate_row_selection(report, context)
    if report.get("post_reference") != context.get("post_reference"):
        issues.append("POST_REFERENCE_ALTERED: post_reference must be carried exactly as the operator provided it (reference only, never opened)")

    # accidental duplicates: same id or identical statement repeated in one section
    for section, id_key, text_key in (("observed_elements", "element_id", None), ("performance_summary", "id", "statement"),
                                      ("replication_hypotheses", "id", "statement"), ("do_not_generalize", "id", "statement"),
                                      ("comparisons", "id", "statement"), ("unknowns", "topic", None)):
        items = report.get(section) or []
        for key in filter(None, (id_key, text_key)):
            values = [it[key] for it in items]
            dupes = sorted({v for v in values if values.count(v) > 1})
            if dupes:
                issues.append(f"DUPLICATE_ITEM: {section} repeats {key} {dupes}")

    # observations: tied to a loaded asset, every dimension addressed
    loaded_assets = {a["asset_id"] for a in context["assets"] if a["status"] == "loaded"}
    elements = {e["element_id"]: e for e in report["observed_elements"]}
    if len(elements) != len(report["observed_elements"]):
        issues.append("DUPLICATE_ELEMENT_ID")
    for e in report["observed_elements"]:
        if e["status"] == "OBSERVED":
            if e.get("asset_id") not in loaded_assets:
                issues.append(f"UNOBSERVABLE_ELEMENT: {e['element_id']} ({e['dimension']}) is OBSERVED but not tied to a loaded asset")
            if not (e.get("description") or "").strip():
                issues.append(f"{e['element_id']}: OBSERVED element needs a description of what is in the creative")
        elif e.get("asset_id") and e["asset_id"] not in {a["asset_id"] for a in context["assets"]}:
            issues.append(f"{e['element_id']}: unknown asset {e['asset_id']!r}")
    missing = [d for d in DIMENSIONS if d not in {e["dimension"] for e in report["observed_elements"]}]
    if missing:
        issues.append(f"DIMENSIONS_NOT_ADDRESSED: {missing} (use NOT_PRESENT / NOT_OBSERVABLE / NOT_APPLICABLE — never omit)")

    # performance facts: cite available metrics, and every number they state is one of them
    metrics = {m["metric_id"]: m for m in context["provided_metrics"] + context["derived_metrics"]}
    for pf in report["performance_summary"]:
        refs = pf["metric_refs"]
        bad = [r for r in refs if r not in metrics or metrics[r]["value"] is None]
        if bad:
            issues.append(f"UNSUPPORTED_PERFORMANCE_FACT: {pf['id']} cites {bad} (unknown or NOT_AVAILABLE metric)")
        expected_trace = source_trace(context, refs)
        if (pf.get("source_trace") or []) != expected_trace and (expected_trace or pf.get("source_trace")):
            issues.append(f"SOURCE_TRACE: {pf['id']} source_trace must be {expected_trace} (file, row, column, result type of each cited export metric)")
        values = [metrics[r]["value"] for r in refs if r in metrics and metrics[r]["value"] is not None]
        for n, dec in _numbers(pf["statement"]):
            if not any(_number_matches(n, dec, v) for v in values):
                issues.append(f"INVENTED_NUMBER: {pf['id']} states {n} which is not the value of a cited metric")

    # hypotheses: grounded in observed elements; never facts
    for h in report["replication_hypotheses"]:
        for r in h["based_on_elements"]:
            if r not in elements or elements[r]["status"] != "OBSERVED":
                issues.append(f"UNGROUNDED_HYPOTHESIS: {h['id']} is based on {r!r}, which is not an OBSERVED element")
        for r in h.get("related_metric_refs", []):
            if r not in metrics:
                issues.append(f"{h['id']}: unknown metric {r!r}")
    for d in report["do_not_generalize"]:
        for r in d.get("related_elements", []):
            if r not in elements:
                issues.append(f"{d['id']}: unknown element {r!r}")

    # comparisons only with comparative evidence the operator provided
    cmp_ids = set(context["comparative_evidence_ids"])
    for c in report["comparisons"]:
        if not cmp_ids:
            issues.append(f"NO_COMPARATIVE_EVIDENCE: {c['id']} compares without any comparative source in the brief")
        elif not set(c["source_refs"]) & cmp_ids:
            issues.append(f"NO_COMPARATIVE_EVIDENCE: {c['id']} must cite a comparative_evidence source")

    # no assertive causal/comparative language without comparative evidence
    for section, value in report.items():
        if section in CAUSAL_EXEMPT_SECTIONS:
            continue
        items = value if isinstance(value, list) else [value]
        for i, item in enumerate(items):
            if isinstance(item, dict) and set(item.get("source_refs") or []) & cmp_ids:
                continue
            for path, text in _strings(item, f"{section}[{i}]" if isinstance(value, list) else section):
                hits = causal_hits(text)
                if hits:
                    issues.append(f"CAUSAL_CLAIM_WITHOUT_EVIDENCE: {path}: {hits} — state it as an observation or a hypothesis to test")

    # unknowns: every NOT_AVAILABLE metric (and an unknown period) is declared
    declared = {u["topic"] for u in report["unknowns"]}
    for topic in context["required_unknowns"]:
        if topic not in declared:
            issues.append(f"UNKNOWN_NOT_DECLARED: {topic!r} is not available and must be listed in unknowns")
    for w in context["warnings"]:
        if not w.startswith(ENV_WARNING_PREFIXES) and w not in report["warnings"]:
            issues.append(f"WARNING_DROPPED: {w!r}")

    # memory candidates: facts, observed patterns and operator decisions only
    pf_ids = {p["id"] for p in report["performance_summary"]}
    op_ids = {o["id"] for o in context["operator_notes"]}
    h_ids = {h["id"] for h in report["replication_hypotheses"]}
    for c in report["memory_promotion_candidates"]:
        ok = {"PERFORMANCE_FACT": pf_ids, "OBSERVED_PATTERN": {k for k, e in elements.items() if e["status"] == "OBSERVED"},
              "OPERATOR_DECISION": op_ids}[c["kind"]]
        if c["ref"] in h_ids:
            issues.append(f"HYPOTHESIS_PROMOTED: {c['ref']} is a REPLICATION_HYPOTHESIS and can never be a memory candidate")
        elif c["ref"] not in ok:
            issues.append(f"MEMORY_CANDIDATE: {c['ref']!r} is not a {c['kind']} of this report")

    if report["learning_summary"] != learning_counts(report):
        issues.append(f"LEARNING_SUMMARY: counts must be {learning_counts(report)}")
    return issues


# ---------------------------------------------------------------------------
# markdown (derived from JSON) and output
# ---------------------------------------------------------------------------


def _fmt(v: Any) -> str:
    if v is None:
        return "NOT_AVAILABLE"
    return f"{v:g}" if isinstance(v, float) else str(v)


def render_markdown(report: dict) -> str:
    per, ws = report["period"], report["winner_status"]
    L = [f"<!-- generated from creative-performance.json · report_sha256={content_sha256(report)} · do not edit by hand -->",
         f"# Criativo campeão — {report['client_id']} — {report['creative_id']}", "",
         f"- generated_at: {report['generated_at']} · status: {report['status']} · canônico: não",
         f"- vencedor: `{ws['source']}` ({ws['declared_by']}) — “{ws['statement']}” · comparação estatística: não",
         f"- período: {per['start_date'] or 'unknown'} → {per['end_date'] or 'unknown'}" + (f" ({per['label']})" if per.get("label") else ""),
         "- aprendizados: " + " · ".join(f"`{k}`={v}" for k, v in report["learning_summary"].items()), ""]
    cc = report["campaign_context"]
    if cc:
        L += ["## Contexto de campanha", ""] + [f"- **{k}:** {v}" for k, v in cc.items() if v is not None] + [""]
    if report["operator_notes"]:
        L += ["## Notas do operador", ""] + [f"- {o['id']}: {o['text']}" for o in report["operator_notes"]] + [""]
    L += ["## Fontes utilizadas", ""] + [f"- {s['source_id']} `{s['path']}` ({s['kind']}) — {s['used_for']}" for s in report["sources_used"]] + [""]
    if report.get("post_reference"):
        pr = report["post_reference"]
        L += ["## Referência do post", "", f"- {pr['url']} — `{pr['source']}` · vínculo com a linha exigido: não · aberto: não"
              + (f" · {pr['note']}" if pr.get("note") else ""), ""]
    sel = report.get("metric_row_selection")
    if sel:
        L += ["## Seleção da linha de métricas", "",
              f"- regra: `{sel['rule']}` (`{sel['source']}`) · coluna: `{sel['column']}` · fonte: {sel['source_id']} `{sel['source_path']}`",
              f"- linhas válidas: {sel['candidate_count']} · empate: {'sim ' + str(sel['tied_rows']) if sel['tied'] else 'não'}"
              + (f" (resolvido: {sel['tie_resolution']})" if sel["tie_resolution"] else "") + f" · agregação: {'sim' if sel['aggregated'] else 'não'}"
              + f" · próximo valor: {_fmt(sel['next_highest_value'])}",
              f"- tipos de resultado no export: {', '.join(f'`{t}`' for t in sel['result_types_found']) or '—'}"]
        row = sel["selected_row"]
        if row:
            res = row["result"]
            L += [f"- **linha {row['row_number']}** · anúncio: {row['ad_name'] or 'UNKNOWN'} · conjunto: {row['ad_set_name'] or 'UNKNOWN'}"
                  f" · campanha: {row['campaign_name'] or 'UNKNOWN'}",
                  f"- resultado: {_fmt(res['value'])} · `{res['source_metric_name']}` · tipo `{res['source_result_type']}`"
                  + (f" ({res['normalized_label']}, {res['normalization_confidence']})" if res["normalized_label"] else "")]
        else:
            L += ["- **nenhuma linha selecionada** — RESULT_TIE aguardando confirmação do operador"]
        if sel["same_ad_name_rows"]:
            L += [f"- mesmo nome de anúncio em outras linhas (não somadas): {sel['same_ad_name_rows']}"]
        if sel["excluded_rows"]:
            L += ["- linhas excluídas: " + ", ".join(f"{x['row_number']} ({x['reason']})" for x in sel["excluded_rows"])]
        if sel.get("notes"):
            L += [f"- notas: {sel['notes']}"]
        L += [""]
    L += ["## Asset", "", "| Asset | Arquivo | Tipo | Dimensões | Orientação | Duração | sha256 |", "|---|---|---|---|---|---|---|"]
    for a in report["asset_metadata"]:
        dims = f"{a['width']}×{a['height']} ({a['dimensions_basis']})" if a["width"] else "NOT_AVAILABLE"
        dur = f"{_fmt(a['duration_seconds'])}s ({a['duration_basis']})" if a["duration_seconds"] is not None else "NOT_AVAILABLE"
        L.append(f"| {a['asset_id']} | `{a['path']}` | {a['kind']} · {a['status']} | {dims} | {a['orientation'] or '—'} {a['aspect_ratio'] or ''} | {dur} | `{(a['sha256'] or '—')[:12]}` |")
    for a in report["asset_metadata"]:
        tm = a.get("technical_metadata")
        if tm:
            pr = tm["probe"]
            L += ["", f"### Metadados técnicos — {a['asset_id']} (ffprobe: {pr['status']}" + (f", {pr['tool_version']}" if pr["tool_version"] else "") + ")", "",
                  "| Campo | Valor | Origem | Operador | ffprobe | Status |", "|---|---|---|---|---|---|"]
            L += [f"| {k} | {_fmt(f['value']) if f['value'] is not None else 'NOT_AVAILABLE'} | {f['source']} | {_fmt(f.get('operator_value')) if f.get('operator_value') is not None else '—'}"
                  f" | {_fmt(f.get('ffprobe_value')) if f.get('ffprobe_value') is not None else '—'} | {f.get('status', f['source'])} |"
                  for k, f in tm["fields"].items()]
    L += ["", "## Elementos observados (`OBSERVED_PATTERN`)", "", "| Elemento | Dimensão | Status | Descrição | Onde | Asset |", "|---|---|---|---|---|---|"]
    L += [f"| {e['element_id']} | {e['dimension']} | {e['status']} | {e.get('description') or '—'} | {e.get('location') or '—'} | {e.get('asset_id') or '—'} |"
          for e in report["observed_elements"]] + [""]
    L += ["## Métricas fornecidas (`METRIC`)", "", "| Id | Métrica | Chave | Valor | Unidade | Status | Origem |", "|---|---|---|---|---|---|---|"]
    L += [f"| {m['metric_id']} | {m['label']} | {m['metric_key']} | {_fmt(m['value'])} | {m['unit']} | {m['status']} | {m['provenance']}"
          + (f" linha {m['source_row']} `{m['source_column']}`" if "source_row" in m else "")
          + (f" tipo `{m['result_type']}`" if m.get("result_type") else "") + " |" for m in report["provided_metrics"]] + [""]
    if report["derived_metrics"]:
        L += ["## Métricas derivadas (`DERIVED_METRIC`)", "", "| Id | Chave | Valor | Unidade | Fórmula | Entradas |", "|---|---|---|---|---|---|"]
        L += [f"| {d['metric_id']} | {d['metric_key']} | {_fmt(d['value'])} | {d['unit']} | `{d['formula']}` | {', '.join(d['inputs'])} |" for d in report["derived_metrics"]] + [""]
    def _trace(p: dict) -> str:
        return "".join(f" · {t['metric_ref']}←{t['source_id']} linha {t['source_row']} `{t['source_column']}`"
                       + (f" tipo `{t['result_type']}`" if t.get("result_type") else "") for t in p.get("source_trace") or [])
    L += ["## Desempenho (`PERFORMANCE_FACT`)", ""] + [f"- **{p['id']}** {p['statement']} ({', '.join(p['metric_refs'])}){_trace(p)}"
                                                       for p in report["performance_summary"]] + [""]
    L += ["## Hipóteses de replicação (`REPLICATION_HYPOTHESIS`)", ""]
    L += [f"- **{h['id']}** {h['statement']} — testar: {h['test_suggestion']} · confiança: {h['confidence']} · base: {', '.join(h['based_on_elements'])}"
          for h in report["replication_hypotheses"]] + [""]
    L += ["## Não generalizar (`DO_NOT_GENERALIZE`)", ""] + [f"- **{d['id']}** {d['statement']}" for d in report["do_not_generalize"]] + [""]
    if report["comparisons"]:
        L += ["## Comparações (evidência comparativa fornecida)", ""] + [f"- **{c['id']}** {c['statement']} ({', '.join(c['source_refs'])})" for c in report["comparisons"]] + [""]
    L += ["## Desconhecidos", ""] + [f"- `{u['topic']}` — {u['status']}: {u['reason']}" for u in report["unknowns"]] + [""]
    L += ["## Candidatos a memória (não promovidos)", ""]
    L += [f"- {c['kind']} `{c['ref']}` — {c['note']}" for c in report["memory_promotion_candidates"]] or ["- nenhum"]
    if report["warnings"]:
        L += ["", "## Avisos", ""] + [f"- {w}" for w in report["warnings"]]
    return "\n".join(L) + "\n"


def markdown_matches(report: dict, markdown: str) -> bool:
    return render_markdown(report) == markdown


def write_report(workspace_root: Path, report: dict, context: dict, *, out_subdir: Optional[str] = None, schema_validator=None) -> dict:
    """Validate, then write creative-performance.json + .md under
    <workspace>/context/generated/<client_id>/creative-performance/<creative_id|out_subdir>/.
    Never overwrites."""
    issues = validate_report(report, context, schema_validator=schema_validator)
    if issues:
        raise CreativePerformanceError("report is invalid:\n- " + "\n- ".join(issues))
    root = Path(workspace_root).resolve()
    base = (root / "context" / "generated" / report["client_id"] / ARTIFACT_DIR).resolve()
    sub = out_subdir or report["creative_id"]
    if not sub or "/" in sub or "\\" in sub or ".." in sub:
        raise CreativePerformanceError(f"unsafe out_subdir {sub!r}")
    target = (base / sub).resolve()
    if base not in target.parents:
        raise CreativePerformanceError("output must stay inside this client's creative-performance directory")
    json_path, md_path = target / "creative-performance.json", target / "creative-performance.md"
    if json_path.exists() or md_path.exists():
        raise CreativePerformanceError(f"{target} already has a report — refusing to overwrite (use another out_subdir)")
    target.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "report_sha256": content_sha256(report)}
