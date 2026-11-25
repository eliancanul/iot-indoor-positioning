"""Derivación reproducible de muestras para el primer radio-map.

La función pública :func:`derive_dataset` solo lee SQLite. Escribe los
artefactos CSV/JSON en un directorio separado y nunca actualiza la base de
origen ni la tabla ``dataset`` legacy.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .audit_database import audit_database
    from .evaluation_metadata import evaluation_context
except ImportError:  # ejecución directa: python tools/derive_dataset.py
    from audit_database import audit_database
    from evaluation_metadata import evaluation_context


@dataclass(frozen=True)
class DatasetPolicy:
    version: str = "rssi-policy-v1"
    expected_anchor_count: int = 3
    readings_per_anchor: int = 10
    max_window_skew_s: float = 20.0
    max_iqr_db: float = 10.0
    max_std_db: float = 6.0
    samples_per_position: int = 30
    independent_sessions_per_position: int = 3


DEFAULT_POLICY = DatasetPolicy()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info([{table}])")}


def _finite(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _valid_rssi(value: Any) -> bool:
    return _finite(value) and -150 <= float(value) <= 0


def _policy(value: DatasetPolicy | dict[str, Any] | None) -> DatasetPolicy:
    if value is None:
        return DEFAULT_POLICY
    if isinstance(value, DatasetPolicy):
        return value
    fields = {field.name for field in DatasetPolicy.__dataclass_fields__.values()}
    return DatasetPolicy(**{key: value[key] for key in fields if key in value})


def _read_sessions(conn: sqlite3.Connection) -> dict[Any, dict[str, Any]]:
    if "collection_sessions" not in {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        return {}
    columns = _columns(conn, "collection_sessions")
    selected = [column for column in (
        "id", "area_id", "campaign_id", "environment_tag", "orientation",
        "layout_version", "independence_evidence", "operator_notes",
        "node_schema_hash",
    ) if column in columns]
    if "id" not in selected:
        return {}
    sessions = {}
    for row in conn.execute("SELECT " + ", ".join(selected) + " FROM collection_sessions"):
        sessions[row["id"]] = {
            column: row[column] if column in columns else None
            for column in selected
        }
    return sessions


def _read_campaign_positions(conn: sqlite3.Connection) -> list[list[float]]:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "capture_campaigns" not in tables:
        return []
    columns = _columns(conn, "capture_campaigns")
    if "orden_posiciones_json" not in columns:
        return []
    positions: list[list[float]] = []
    for row in conn.execute(
        "SELECT orden_posiciones_json FROM capture_campaigns ORDER BY id"
    ):
        try:
            decoded = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            continue
        for point in decoded:
            if isinstance(point, (list, tuple)) and len(point) == 2:
                candidate = [float(point[0]), float(point[1])]
                if candidate not in positions:
                    positions.append(candidate)
    return positions


def _read_samples(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not {"fingerprint_samples", "fingerprint_readings"} <= tables:
        return [], []

    sample_columns = _columns(conn, "fingerprint_samples")
    required = {"id", "session_id", "area_id", "captured_at", "cycle_number", "x_real", "y_real"}
    if not required <= sample_columns:
        return [], []
    sessions = _read_sessions(conn)

    samples: dict[Any, dict[str, Any]] = {}
    optional_sample_columns = [
        column
        for column in (
            "quality_status", "quality_reasons_json",
            "window_start_at", "window_end_at", "window_skew_s",
        )
        if column in sample_columns
    ]
    sample_select = ", ".join([
        "id", "session_id", "area_id", "captured_at", "cycle_number", "x_real", "y_real",
        *optional_sample_columns,
    ])
    for row in conn.execute(
        "SELECT " + sample_select + " FROM fingerprint_samples ORDER BY id"
    ):
        session = sessions.get(row["session_id"], {})
        samples[row["id"]] = {
            "sample_id": row["id"],
            "session_id": row["session_id"],
            "area_id": row["area_id"],
            "captured_at": row["captured_at"],
            "cycle_number": row["cycle_number"],
            "x_real": row["x_real"],
            "y_real": row["y_real"],
            "persisted_quality_status": (
                row["quality_status"]
                if "quality_status" in optional_sample_columns else "eligible"
            ),
            "persisted_quality_reasons": row["quality_reasons_json"] if "quality_reasons_json" in optional_sample_columns else "[]",
            "window_start_at": row["window_start_at"] if "window_start_at" in optional_sample_columns else None,
            "window_end_at": row["window_end_at"] if "window_end_at" in optional_sample_columns else None,
            "window_skew_s": row["window_skew_s"] if "window_skew_s" in optional_sample_columns else None,
            "campaign_id": session.get("campaign_id"),
            "environment_tag": session.get("environment_tag"),
            "orientation": session.get("orientation"),
            "layout_version": session.get("layout_version"),
            "independence_evidence": session.get("independence_evidence"),
            "readings": {},
        }

    reading_columns = _columns(conn, "fingerprint_readings")
    required_reading = {"sample_id", "node_id", "rssi_median", "rssi_iqr", "rssi_std", "reading_count", "present"}
    if not required_reading <= reading_columns:
        return list(samples.values()), []
    optional_reading_columns = [
        column for column in ("rssi_min", "rssi_max") if column in reading_columns
    ]
    reading_select = ", ".join([
        "sample_id", "node_id", "rssi_median", "rssi_iqr", "rssi_std",
        *optional_reading_columns, "reading_count", "present",
    ])
    for row in conn.execute(
        "SELECT " + reading_select + " FROM fingerprint_readings "
        "ORDER BY sample_id, node_id"
    ):
        sample = samples.get(row["sample_id"])
        if sample is not None:
            sample["readings"][row["node_id"]] = {
                "rssi_median": row["rssi_median"],
                "rssi_iqr": row["rssi_iqr"],
                "rssi_std": row["rssi_std"],
                "rssi_min": row["rssi_min"] if "rssi_min" in optional_reading_columns else None,
                "rssi_max": row["rssi_max"] if "rssi_max" in optional_reading_columns else None,
                "reading_count": row["reading_count"],
                "present": bool(row["present"]),
            }

    anchor_ids = sorted({
        node_id
        for sample in samples.values()
        for node_id in sample["readings"]
    })
    return list(samples.values()), anchor_ids


def _classify(sample: dict[str, Any], anchor_ids: list[str], policy: DatasetPolicy) -> dict[str, Any]:
    reasons: set[str] = set()
    if sample.get("persisted_quality_status") == "dirty":
        try:
            persisted = json.loads(sample.get("persisted_quality_reasons") or "[]")
        except (TypeError, json.JSONDecodeError):
            persisted = ["invalid_quality_reasons_json"]
        reasons.update(str(reason) for reason in persisted)
        if not reasons:
            reasons.add("persisted_dirty")
    readings = sample["readings"]
    if len(anchor_ids) != policy.expected_anchor_count:
        reasons.add("unexpected_anchor_count")
    if len(readings) != policy.expected_anchor_count:
        reasons.add("missing_anchor")

    for node_id in anchor_ids:
        reading = readings.get(node_id)
        if reading is None or not reading["present"]:
            reasons.add("missing_anchor")
            continue
        median = reading["rssi_median"]
        if not _valid_rssi(median):
            reasons.add("invalid_rssi")
        if reading["rssi_iqr"] is None or reading["rssi_std"] is None:
            reasons.add("missing_quality_stat")
        if _finite(reading["rssi_iqr"]) and float(reading["rssi_iqr"]) > policy.max_iqr_db:
            reasons.add("high_iqr")
        if _finite(reading["rssi_std"]) and float(reading["rssi_std"]) > policy.max_std_db:
            reasons.add("high_std")
        if reading["reading_count"] != policy.readings_per_anchor:
            reasons.add("invalid_reading_count")

    if (
        _finite(sample.get("window_skew_s"))
        and float(sample["window_skew_s"]) > policy.max_window_skew_s
    ):
        reasons.add("window_skew_exceeded")

    return {
        **sample,
        "status": "dirty" if reasons else "eligible",
        "dirty_reasons": sorted(reasons),
    }


def _sort_key(record: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(record.get("captured_at") or ""),
        int(record.get("cycle_number") or 0),
        int(record["sample_id"]),
    )


def _position_key(record: dict[str, Any]) -> tuple[float, float]:
    return (float(record["x_real"]), float(record["y_real"]))


def _independent(record: dict[str, Any]) -> bool:
    return bool(str(record.get("independence_evidence") or "").strip())


def _select_training(
    records: Iterable[dict[str, Any]], policy: DatasetPolicy
) -> list[dict[str, Any]]:
    grouped: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for record in records:
        if record["status"] == "eligible":
            grouped.setdefault(_position_key(record), []).append(record)

    selected: list[dict[str, Any]] = []
    for position in sorted(grouped):
        eligible = grouped[position]
        by_session: dict[Any, list[dict[str, Any]]] = {}
        for record in eligible:
            if _independent(record):
                by_session.setdefault(record["session_id"], []).append(record)
        for queue in by_session.values():
            queue.sort(key=_sort_key)
        session_ids = sorted(by_session, key=lambda value: str(value))
        independent_count = len(session_ids)
        position_selected: list[dict[str, Any]] = []
        if (
            len(eligible) >= policy.samples_per_position
            and independent_count >= policy.independent_sessions_per_position
        ):
            while len(position_selected) < policy.samples_per_position:
                progress = False
                for session_id in session_ids:
                    queue = by_session[session_id]
                    if queue:
                        position_selected.append(queue.pop(0))
                        progress = True
                        if len(position_selected) == policy.samples_per_position:
                            break
                if not progress:
                    break
        selected.extend(position_selected)
    return selected


def _stable_ids(values: Iterable[Any]) -> list[Any]:
    """Ordena identificadores heterogéneos de forma estable y serializable."""
    return sorted(set(values), key=lambda value: (value is not None, str(value)))


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Resume elegibilidad, selección, sesiones, campañas y posiciones."""
    positions = sorted({_position_key(record) for record in records})
    session_ids = _stable_ids(record["session_id"] for record in records)
    campaign_ids = _stable_ids(
        record.get("campaign_id")
        for record in records
        if record.get("campaign_id") is not None
    )
    return {
        "eligible": sum(record["status"] == "eligible" for record in records),
        "dirty": sum(record["status"] == "dirty" for record in records),
        "selected": sum(record.get("selected", False) for record in records),
        "session_count": len(session_ids),
        "session_ids": session_ids,
        "campaign_count": len(campaign_ids),
        "campaign_ids": campaign_ids,
        "positions": [[position[0], position[1]] for position in positions],
    }


def _build_coverage(
    records: list[dict[str, Any]], campaign_positions: list[list[float]], policy: DatasetPolicy
) -> dict[str, Any]:
    """Construye cobertura por posición, sesión y campaña sin mutar las muestras."""
    positions = {
        _position_key(record)
        for record in records
        if record.get("x_real") is not None and record.get("y_real") is not None
    }
    positions.update((float(point[0]), float(point[1])) for point in campaign_positions)

    position_rows = []
    for position in sorted(positions):
        position_records = [
            record for record in records if _position_key(record) == position
        ]
        eligible = [record for record in position_records if record["status"] == "eligible"]
        independent_sessions = _stable_ids(
            record["session_id"] for record in eligible if _independent(record)
        )
        row = {
            "position": [position[0], position[1]],
            **_summary(position_records),
            "independent_sessions": len(independent_sessions),
            "independent_session_ids": independent_sessions,
        }
        row["status"] = (
            "covered"
            if row["selected"] == policy.samples_per_position
            else (
                "insufficient_sessions"
                if row["independent_sessions"] < policy.independent_sessions_per_position
                else "insufficient_samples"
            )
        )
        position_rows.append(row)

    session_rows = []
    for session_id in _stable_ids(record["session_id"] for record in records):
        session_records = [
            record for record in records if record["session_id"] == session_id
        ]
        campaign_ids = _stable_ids(
            record.get("campaign_id") for record in session_records
        )
        session_rows.append({
            "session_id": session_id,
            "campaign_id": campaign_ids[0] if len(campaign_ids) == 1 else None,
            "campaign_ids": campaign_ids,
            "independence_evidence_present": any(
                _independent(record) for record in session_records
            ),
            **_summary(session_records),
        })

    campaign_groups: dict[Any, list[dict[str, Any]]] = {}
    for record in records:
        campaign_groups.setdefault(record.get("campaign_id"), []).append(record)
    campaign_rows = []
    for campaign_id in _stable_ids(campaign_groups):
        campaign_rows.append({
            "campaign_id": campaign_id,
            **_summary(campaign_groups[campaign_id]),
        })

    status_counts: dict[str, int] = {}
    for row in position_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    sample_status_counts = {
        "eligible": sum(record["status"] == "eligible" for record in records),
        "dirty": sum(record["status"] == "dirty" for record in records),
    }
    return {
        "positions": position_rows,
        "sessions": session_rows,
        "campaigns": campaign_rows,
        "status_counts": status_counts,
        "sample_status_counts": sample_status_counts,
    }


def _feature_columns(anchor_ids: list[str]) -> list[str]:
    columns = []
    for index, _ in enumerate(anchor_ids, start=1):
        prefix = f"anchor_{index}"
        columns.extend([
            f"{prefix}_rssi_median",
            f"{prefix}_rssi_iqr",
            f"{prefix}_rssi_std",
            f"{prefix}_reading_count",
            f"{prefix}_missing",
        ])
    return columns


def _row(record: dict[str, Any], anchor_ids: list[str], feature_columns: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sample_id": record["sample_id"],
        "area_id": record["area_id"],
        "session_id": record["session_id"],
        "campaign_id": record.get("campaign_id"),
        "captured_at": record.get("captured_at"),
        "cycle_number": record.get("cycle_number"),
        "window_start_at": record.get("window_start_at"),
        "window_end_at": record.get("window_end_at"),
        "window_skew_s": record.get("window_skew_s"),
        "capture_quality_status": record.get("persisted_quality_status"),
        "x_real": record.get("x_real"),
        "y_real": record.get("y_real"),
        "status": record["status"],
        "dirty_reasons": ";".join(record["dirty_reasons"]),
        "environment_tag": record.get("environment_tag"),
        "orientation": record.get("orientation"),
        "layout_version": record.get("layout_version"),
    }
    for index, node_id in enumerate(anchor_ids, start=1):
        reading = record["readings"].get(node_id)
        prefix = f"anchor_{index}"
        values = {
            f"{prefix}_rssi_median": reading.get("rssi_median") if reading else None,
            f"{prefix}_rssi_iqr": reading.get("rssi_iqr") if reading else None,
            f"{prefix}_rssi_std": reading.get("rssi_std") if reading else None,
            f"{prefix}_reading_count": reading.get("reading_count") if reading else 0,
            f"{prefix}_missing": int(reading is None or not reading.get("present")),
        }
        row.update(values)
    return {column: row.get(column) for column in (
        "sample_id", "area_id", "session_id", "campaign_id", "captured_at", "cycle_number",
        "window_start_at", "window_end_at", "window_skew_s",
        "capture_quality_status", "x_real", "y_real", "status", "dirty_reasons", "environment_tag",
        "orientation", "layout_version", *feature_columns,
    )}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_dataset(
    db_path: str,
    output_dir: str | Path,
    policy: DatasetPolicy | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify and select normalized capture records without modifying SQLite."""
    source = Path(db_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    selected_policy = _policy(policy)
    audit = audit_database(str(source))

    conn = _readonly_connection(source)
    try:
        samples, anchor_ids = _read_samples(conn)
        campaign_positions = _read_campaign_positions(conn)
        context = evaluation_context(conn, samples, anchor_ids, audit)
    finally:
        conn.close()

    classified = [_classify(sample, anchor_ids, selected_policy) for sample in samples]
    selected = _select_training(classified, selected_policy)
    selected_ids = {record["sample_id"] for record in selected}
    for record in classified:
        record["selected"] = record["sample_id"] in selected_ids
    coverage_details = _build_coverage(
        classified, campaign_positions, selected_policy
    )
    coverage = coverage_details["positions"]

    feature_columns = _feature_columns(anchor_ids)
    metadata_columns = [
        "sample_id", "area_id", "session_id", "campaign_id", "captured_at", "cycle_number",
        "window_start_at", "window_end_at", "window_skew_s",
        "capture_quality_status", "status", "dirty_reasons", "environment_tag", "orientation", "layout_version",
    ]
    label_columns = ["x_real", "y_real"]
    all_columns = [*metadata_columns, *label_columns, *feature_columns]
    classified_rows = [_row(record, anchor_ids, feature_columns) for record in classified]
    training_rows = [
        _row(record, anchor_ids, feature_columns)
        for record in sorted(selected, key=lambda item: (item["x_real"], item["y_real"], _sort_key(item)))
    ]

    classified_path = destination / "samples.csv"
    training_path = destination / "training.csv"
    coverage_path = destination / "coverage.json"
    manifest_path = destination / "manifest.json"
    _write_csv(classified_path, classified_rows, all_columns)
    _write_csv(training_path, training_rows, all_columns)

    eligible_count = sum(record["status"] == "eligible" for record in classified)
    dirty_count = len(classified) - eligible_count
    covered_positions = [
        item["position"] for item in coverage if item["status"] == "covered"
    ]

    coverage_path.write_text(
        json.dumps(
            {
                "policy_version": selected_policy.version,
                "source_sha256": audit["source_sha256"],
                **coverage_details,
                "covered_positions": covered_positions,
                "eligible_count": eligible_count,
                "dirty_count": dirty_count,
                "training_sample_count": len(training_rows),
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "training_sha256": _sha256(training_path),
        "samples_sha256": _sha256(classified_path),
        "evaluation_context": context,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": audit["database"],
        "source_sha256": audit["source_sha256"],
        "read_only": True,
        "policy_version": selected_policy.version,
        "policy": asdict(selected_policy),
        "anchor_ids": anchor_ids,
        "feature_columns": feature_columns,
        "label_columns": label_columns,
        "source_counts": audit["counts"],
        "legacy_reconciliation": {
            key: audit["reconciliation"].get(key)
            for key in (
                "normalized", "legacy", "matched", "normalized_only",
                "legacy_only", "ambiguous", "closed",
            )
        },
        "classified_count": len(classified),
        "eligible_count": eligible_count,
        "dirty_count": dirty_count,
        "training_sample_count": len(training_rows),
        "training_sample_ids": [row["sample_id"] for row in training_rows],
        "coverage": {
            **coverage_details,
            "covered_positions": covered_positions,
        },
        "campaign_positions": campaign_positions,
        "csv_columns": all_columns,
        "coverage_report": "coverage.json",
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "classified_csv": str(classified_path.resolve()),
        "training_csv": str(training_path.resolve()),
        "coverage_report": str(coverage_path.resolve()),
        "manifest": str(manifest_path.resolve()),
        "source_sha256": audit["source_sha256"],
        "policy_version": selected_policy.version,
        "feature_columns": feature_columns,
        "label_columns": label_columns,
        "eligible_count": eligible_count,
        "dirty_count": dirty_count,
        "training_sample_count": len(training_rows),
        "covered_positions": covered_positions,
        "coverage": coverage,
        "content_sha256": _sha256(training_path),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Copia SQLite detenida")
    parser.add_argument("--output-dir", required=True, help="Directorio de artefactos")
    args = parser.parse_args()
    result = derive_dataset(args.db, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
