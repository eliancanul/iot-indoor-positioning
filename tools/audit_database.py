"""Auditoría offline y de solo lectura de una base SQLite exportada.

Uso::

    python tools/audit_database.py --db copia/iot_platform.db --output audit.json

El script nunca modifica la base indicada. La copia debe realizarse cuando la
captura esté detenida, siguiendo ``WORKFLOW.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_TABLES = (
    "areas",
    "esp32",
    "dataset",
    "collection_sessions",
    "fingerprint_samples",
    "fingerprint_readings",
)

RSSI_COLUMNS = ("rssi_median", "rssi_min", "rssi_max")
SPREAD_COLUMNS = ("rssi_iqr", "rssi_std")
LEGACY_RSSI_COLUMNS = ("rssi_1", "rssi_2", "rssi_3")
MATCH_TOLERANCE = 1e-6


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    # ``mode=ro`` is an SQLite connection invariant: even an accidental write
    # in a future audit query fails instead of changing the source file.
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info([{table}])")
    }


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _valid_rssi(value: Any) -> bool:
    return _finite(value) and -150 <= float(value) <= 0


def _audit_quality(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    quality = {
        "missing_rssi_values": 0,
        "invalid_rssi_values": 0,
        "missing_coordinates": 0,
        "invalid_coordinates": 0,
        "missing_timestamps": 0,
    }

    if "fingerprint_readings" in tables:
        reading_columns = _columns(conn, "fingerprint_readings")
        selected = [
            column
            for column in (*RSSI_COLUMNS, *SPREAD_COLUMNS, "reading_count")
            if column in reading_columns
        ]
        if selected:
            query = "SELECT " + ", ".join(selected) + " FROM fingerprint_readings"
            for row in conn.execute(query):
                for column in RSSI_COLUMNS:
                    if column not in reading_columns:
                        continue
                    value = row[column]
                    quality["missing_rssi_values"] += int(value is None)
                    quality["invalid_rssi_values"] += int(
                        value is not None and not _valid_rssi(value)
                    )
                for column in SPREAD_COLUMNS:
                    if column not in reading_columns:
                        continue
                    value = row[column]
                    quality["missing_rssi_values"] += int(value is None)
                    quality["invalid_rssi_values"] += int(
                        value is not None
                        and (not _finite(value) or float(value) < 0)
                    )
                if "reading_count" in reading_columns:
                    value = row["reading_count"]
                    quality["invalid_rssi_values"] += int(
                        value is None or not isinstance(value, (int, float)) or value < 0
                    )

    if "fingerprint_samples" in tables:
        sample_columns = _columns(conn, "fingerprint_samples")
        selected = [
            column
            for column in ("x_real", "y_real", "captured_at")
            if column in sample_columns
        ]
        if selected:
            for row in conn.execute(
                "SELECT " + ", ".join(selected) + " FROM fingerprint_samples"
            ):
                if "x_real" in sample_columns and "y_real" in sample_columns:
                    missing = row["x_real"] is None or row["y_real"] is None
                    quality["missing_coordinates"] += int(missing)
                    quality["invalid_coordinates"] += int(
                        not missing
                        and (
                            not _finite(row["x_real"])
                            or not _finite(row["y_real"])
                        )
                    )
                if "captured_at" in sample_columns:
                    quality["missing_timestamps"] += int(not row["captured_at"])

    return quality


def _session_counts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    if "collection_sessions" not in tables:
        return {}
    columns = _columns(conn, "collection_sessions")
    if "area_id" not in columns:
        return {}
    return {
        str(area_id): count
        for area_id, count in conn.execute(
            "SELECT area_id, COUNT(*) FROM collection_sessions GROUP BY area_id"
        ).fetchall()
    }


def _number_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return abs(float(left) - float(right)) <= MATCH_TOLERANCE
    except (TypeError, ValueError):
        return False


def _base_match_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("area_id"),
        record.get("timestamp"),
        record.get("x_real"),
        record.get("y_real"),
    )


def _full_match_key(record: dict[str, Any]) -> tuple[Any, ...] | None:
    values = record.get("rssi") or ()
    if len(values) != 3 or any(value is None for value in values):
        return None
    return (*_base_match_key(record), *values)


def _same_key(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    if len(left) != len(right):
        return False
    for left_value, right_value in zip(left, right):
        if isinstance(left_value, (int, float)) or isinstance(right_value, (int, float)):
            if not _number_equal(left_value, right_value):
                return False
        elif left_value != right_value:
            return False
    return True


def _read_normalized_records(
    conn: sqlite3.Connection, tables: set[str]
) -> list[dict[str, Any]]:
    if "fingerprint_samples" not in tables:
        return []
    sample_columns = _columns(conn, "fingerprint_samples")
    required = {"id", "area_id", "captured_at", "x_real", "y_real"}
    if not required <= sample_columns:
        return []

    records = [
        {
            "id": row["id"],
            "area_id": row["area_id"],
            "timestamp": row["captured_at"],
            "x_real": row["x_real"],
            "y_real": row["y_real"],
            "rssi": [],
        }
        for row in conn.execute(
            "SELECT id, area_id, captured_at, x_real, y_real "
            "FROM fingerprint_samples ORDER BY id"
        )
    ]
    by_id = {record["id"]: record for record in records}

    if "fingerprint_readings" not in tables:
        return records
    reading_columns = _columns(conn, "fingerprint_readings")
    if not {"sample_id", "node_id", "rssi_median"} <= reading_columns:
        return records

    for row in conn.execute(
        "SELECT sample_id, node_id, rssi_median "
        "FROM fingerprint_readings ORDER BY sample_id, node_id"
    ):
        record = by_id.get(row["sample_id"])
        if record is not None:
            record["rssi"].append(row["rssi_median"])
    for record in records:
        record["rssi"] = tuple(record["rssi"])
    return records


def _read_legacy_records(
    conn: sqlite3.Connection, tables: set[str]
) -> list[dict[str, Any]]:
    if "dataset" not in tables:
        return []
    columns = _columns(conn, "dataset")
    required = {"id", "area_id", "x_real", "y_real"}
    if not required <= columns:
        return []

    timestamp_column = "timestamp" if "timestamp" in columns else None
    selected = ["id", "area_id", "x_real", "y_real"]
    if timestamp_column:
        selected.append(timestamp_column)
    selected.extend(column for column in LEGACY_RSSI_COLUMNS if column in columns)
    query = "SELECT " + ", ".join(selected) + " FROM dataset ORDER BY id"

    records = []
    for row in conn.execute(query):
        records.append(
            {
                "id": row["id"],
                "area_id": row["area_id"],
                "timestamp": row[timestamp_column] if timestamp_column else None,
                "x_real": row["x_real"],
                "y_real": row["y_real"],
                "rssi": tuple(
                    row[column] if column in columns else None
                    for column in LEGACY_RSSI_COLUMNS
                ),
            }
        )
    return records


def _reconcile(
    normalized: list[dict[str, Any]], legacy: list[dict[str, Any]]
) -> dict[str, Any]:
    matched_ids: set[Any] = set()
    matches: list[dict[str, Any]] = []
    normalized_only: list[Any] = []
    normalized_ambiguous: list[dict[str, Any]] = []
    legacy_ambiguous_ids: set[Any] = set()

    for sample in normalized:
        full_key = _full_match_key(sample)
        if full_key is not None:
            candidates = [
                candidate
                for candidate in legacy
                if _full_match_key(candidate) is not None
                and _same_key(full_key, _full_match_key(candidate))
            ]
            basis = "full"
        else:
            candidates = []
            basis = "area_timestamp_position"
        if not candidates:
            base_key = _base_match_key(sample)
            candidates = [
                candidate
                for candidate in legacy
                if _same_key(base_key, _base_match_key(candidate))
            ]
            basis = "area_timestamp_position"

        available = [candidate for candidate in candidates if candidate["id"] not in matched_ids]
        if len(available) == 1 and len(candidates) == 1:
            candidate = available[0]
            matched_ids.add(candidate["id"])
            matches.append(
                {
                    "normalized_sample_id": sample["id"],
                    "legacy_row_id": candidate["id"],
                    "basis": basis,
                }
            )
        elif len(candidates) > 1:
            normalized_ambiguous.append(
                {
                    "normalized_sample_id": sample["id"],
                    "legacy_candidate_ids": [candidate["id"] for candidate in candidates],
                }
            )
            legacy_ambiguous_ids.update(candidate["id"] for candidate in candidates)
        else:
            normalized_only.append(sample["id"])

    matched_count = len(matches)
    legacy_only = [
        record["id"]
        for record in legacy
        if record["id"] not in matched_ids
        and record["id"] not in legacy_ambiguous_ids
    ]
    legacy_ambiguous = [
        record_id
        for record_id in sorted(legacy_ambiguous_ids)
        if record_id not in matched_ids
    ]

    return {
        "normalized": len(normalized),
        "legacy": len(legacy),
        "matched": matched_count,
        "normalized_only": len(normalized_only),
        "legacy_only": len(legacy_only),
        "ambiguous": len(normalized_ambiguous),
        "normalized_ambiguous": normalized_ambiguous,
        "legacy_ambiguous": legacy_ambiguous,
        "normalized_only_ids": normalized_only,
        "legacy_only_ids": legacy_only,
        "matches": matches,
        "accounting": {"normalized": len(normalized), "legacy": len(legacy)},
        "closed": not normalized_ambiguous and not legacy_ambiguous,
    }


def audit_database(path: str) -> dict[str, Any]:
    """Audit ``path`` without opening it for writes."""
    db_path = Path(path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    conn = _connect_readonly(db_path)
    try:
        tables = _table_names(conn)
        counts = {
            table: _count(conn, table)
            for table in REQUIRED_TABLES
            if table in tables
        }
        missing_tables = [table for table in REQUIRED_TABLES if table not in tables]
        normalized = _read_normalized_records(conn, tables)
        legacy = _read_legacy_records(conn, tables)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]

        return {
            "database": str(db_path.resolve()),
            "source_sha256": _sha256(db_path),
            "read_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
            "tables": sorted(tables),
            "missing_required_tables": missing_tables,
            "counts": counts,
            "sessions_by_area": _session_counts(conn, tables),
            "quality": _audit_quality(conn, tables),
            "reconciliation": _reconcile(normalized, legacy),
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Ruta de la copia SQLite exportada")
    parser.add_argument("--output", type=Path, help="Archivo JSON de salida")
    args = parser.parse_args()
    report = audit_database(args.db)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
