"""Minimal offline evaluation provenance, read from the already read-only connection."""
import math


def evaluation_context(conn, samples, anchor_ids, audit):
    blockers = []
    area_ids = {s["area_id"] for s in samples}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    area, anchors, sessions = None, [], []
    if len(area_ids) != 1:
        blockers.append("derivar una sola área por export")
    elif {"areas", "esp32", "collection_sessions"} <= tables:
        area_id = next(iter(area_ids))
        row = conn.execute("SELECT id, ancho, alto FROM areas WHERE id=?", (area_id,)).fetchone()
        area = dict(row) if row else None
        anchor_columns = {r[1] for r in conn.execute("PRAGMA table_info(esp32)")}
        if "n_pathloss" in anchor_columns:
            anchors = [dict(r) for r in conn.execute(
                "SELECT node_id, pos_x, pos_y, rssi_1m, n_pathloss FROM esp32 WHERE area_id=? ORDER BY node_id", (area_id,))]
        for row in conn.execute("SELECT * FROM collection_sessions WHERE area_id=? ORDER BY id", (area_id,)):
            source = dict(row)
            sessions.append({**{key: source.get(key) for key in (
                "id", "area_id", "campaign_id", "finished_at", "orientation", "environment_tag", "layout_version", "node_schema_hash")},
                "independence_evidence_present": bool(str(source.get("independence_evidence") or "").strip()),
                "obstacles_documented": bool(source.get("obstacle_description") or source.get("obstacle_photo_ref"))})
    else:
        blockers.append("faltan tablas de contexto físico")
    if area is None or (area["ancho"], area["alto"]) != (4, 2):
        blockers.append("se requiere un área de 4 × 2 m")
    if len(anchors) != 3 or [a["node_id"] for a in anchors] != anchor_ids:
        blockers.append("se requieren tres anchors coincidentes con el export")
    invalid_calibration = False
    for anchor in anchors:
        try:
            n = float(anchor.get("n_pathloss"))
            valid = math.isfinite(n) and .1 <= n <= 10
        except (TypeError, ValueError, OverflowError):
            valid = False
        # Preserve the raw value in SQLite, but keep the derived JSON finite.
        anchor["n_pathloss"] = n if valid else None
        invalid_calibration |= not valid
    if invalid_calibration:
        blockers.append("registrar calibración n_pathloss por anchor antes de comparar círculos")
    audit_ok = (audit.get("integrity_check") == "ok"
                and not audit.get("foreign_key_violations")
                and not audit.get("missing_required_tables"))
    if not audit_ok:
        blockers.append("auditoría SQLite pendiente o fallida")
    return {"version": 1, "audit_ok": audit_ok, "blockers": blockers,
            "area": area, "anchors": anchors, "sessions": sessions,
            "baseline_calibration": "snapshot_at_export"}
