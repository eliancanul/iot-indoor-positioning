"""Offline RSSI fingerprinting. No database writes, MQTT clients or model files.

WkNN and a binary CART regression tree consume the same three RSSI medians.
Coordinates, session IDs and geometric errors are never inference features.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import io
import json
import math
import platform

import numpy as np
import sklearn
from sklearn.tree import DecisionTreeRegressor
from sklearn.preprocessing import StandardScaler

SEED = 2026
FEATURES = tuple(f"anchor_{i}_rssi_median" for i in range(1, 4))
METHODS = {"wknn": "Fingerprinting · WkNN", "tree": "Fingerprinting · Árbol de decisión", "circles": "Círculos · baseline"}


class DatasetError(ValueError):
    """Actionable input or readiness problem, safe to display to an operator."""


@dataclass
class RadioMap:
    rows: list[dict]
    anchors: list[dict]
    bounds: tuple[float, float]
    provenance: dict

    @property
    def X(self):
        return np.array([[row[key] for key in FEATURES] for row in self.rows], dtype=float)

    @property
    def y(self):
        return np.array([[row["x_real"], row["y_real"]] for row in self.rows], dtype=float)


def _number(value, name):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise DatasetError(f"{name}: se requiere un número finito.") from None
    if not math.isfinite(number):
        raise DatasetError(f"{name}: se requiere un número finito.")
    return number


def _load_export(csv_bytes, manifest_bytes):
    if len(csv_bytes) > 10_000_000 or len(manifest_bytes) > 2_000_000:
        raise DatasetError("El export excede el límite local (CSV 10 MB; manifiesto 2 MB).")
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(csv_bytes).hexdigest()
    if manifest.get("training_sha256") != digest:
        raise DatasetError("El hash de training.csv no coincide. Vuelve a derivar ambos archivos juntos.")
    context = manifest.get("evaluation_context", {})
    if context.get("version") != 1:
        raise DatasetError("Export antiguo: vuelve a ejecutar tools/derive_dataset.py sobre una copia detenida.")
    if context.get("blockers"):
        raise DatasetError("Gate pendiente: " + "; ".join(context["blockers"]))
    if manifest.get("policy_version") != "rssi-policy-v1":
        raise DatasetError("Se requiere rssi-policy-v1 para esta primera comparación.")
    if context.get("audit_ok") is not True:
        raise DatasetError("La auditoría de la fuente no está aprobada.")
    area = context["area"]
    bounds = (_number(area["ancho"], "ancho"), _number(area["alto"], "alto"))
    if bounds != (4.0, 2.0):
        raise DatasetError("El gate inicial requiere la cuadrícula de 4 × 2 metros.")
    anchors = context["anchors"]
    if len(anchors) != 3 or len({a["node_id"] for a in anchors}) != 3:
        raise DatasetError("Se requieren exactamente tres anchors distintos.")
    if [a["node_id"] for a in anchors] != manifest["anchor_ids"]:
        raise DatasetError("El orden de anchors no coincide con las features del export.")
    for anchor in anchors:
        for key in ("pos_x", "pos_y", "rssi_1m", "n_pathloss"):
            anchor[key] = _number(anchor[key], key)
        if not (-150 <= anchor["rssi_1m"] <= 0 and 0.1 <= anchor["n_pathloss"] <= 10):
            raise DatasetError("Calibración RSSI/path-loss inválida para el baseline.")
        if not (0 <= anchor["pos_x"] <= bounds[0] and 0 <= anchor["pos_y"] <= bounds[1]):
            raise DatasetError("Anchor fuera de los límites del área.")
    sessions = {str(s["id"]): s for s in context["sessions"]}
    if len(sessions) != len(context["sessions"]):
        raise DatasetError("El manifiesto contiene sesiones duplicadas.")
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    if len(reader.fieldnames or []) != len(set(reader.fieldnames or [])):
        raise DatasetError("El CSV contiene columnas duplicadas.")
    rows = list(reader)
    if len(rows) != 450:
        raise DatasetError("Se requieren 450 muestras: 30 por cada una de las 15 posiciones.")
    ids, cycles, positions, layouts, schemas = set(), set(), {}, set(), set()
    for row in rows:
        if row.get(None) is not None:
            raise DatasetError("CSV mal formado: hay celdas sin columna.")
        sample_id = row["sample_id"]
        if not sample_id or sample_id in ids:
            raise DatasetError("Los identificadores de muestra deben ser únicos.")
        ids.add(sample_id)
        session = sessions.get(row["session_id"])
        if not session or not all(session.get(key) for key in (
            "campaign_id", "finished_at", "environment_tag", "orientation", "layout_version",
            "independence_evidence_present", "obstacles_documented", "node_schema_hash",
        )):
            raise DatasetError("Cada muestra requiere una sesión cerrada con contexto físico completo.")
        if (str(session["area_id"]) != row["area_id"] or str(area["id"]) != row["area_id"]
                or str(session["campaign_id"]) != row["campaign_id"]):
            raise DatasetError("Área/campaña de la muestra no coincide con su sesión.")
        if any(row[key] != session[key] for key in ("layout_version", "environment_tag", "orientation")):
            raise DatasetError("Los metadatos del CSV no coinciden con la sesión.")
        if session["orientation"] not in ("north", "east", "south", "west", "unknown"):
            raise DatasetError("Orientación de sesión inválida.")
        layouts.add(session["layout_version"])
        schemas.add(session["node_schema_hash"])
        cycle = (row["session_id"], row["cycle_number"])
        if not row["cycle_number"] or cycle in cycles:
            raise DatasetError("Ciclo duplicado o vacío dentro de la sesión.")
        cycles.add(cycle)
        if row["status"] != "eligible" or row["capture_quality_status"] != "eligible" or row["dirty_reasons"]:
            raise DatasetError("El entrenamiento contiene muestras sucias.")
        if not (0 <= _number(row["window_skew_s"], "ventana") <= 20):
            raise DatasetError("La ventana de captura debe estar documentada y ser ≤20 segundos.")
        for i, feature in enumerate(FEATURES, 1):
            row[feature] = _number(row[feature], feature)
            if not -150 <= row[feature] <= 0:
                raise DatasetError("RSSI fuera de rango [-150, 0] dBm.")
            if (row[f"anchor_{i}_missing"] != "0" or
                    _number(row[f"anchor_{i}_reading_count"], "lecturas") != 10 or
                    not 0 <= _number(row[f"anchor_{i}_rssi_iqr"], "IQR") <= 10 or
                    not 0 <= _number(row[f"anchor_{i}_rssi_std"], "desviación") <= 6):
                raise DatasetError("Anchor ausente o estadísticas fuera de rssi-policy-v1.")
        point = tuple(_number(row[key], key) for key in ("x_real", "y_real"))
        row["x_real"], row["y_real"] = point
        if point not in {(float(x), float(y)) for x in range(5) for y in range(3)}:
            raise DatasetError("Posición fuera de la cuadrícula de referencia de 4 × 2 m.")
        positions.setdefault(point, []).append(row["session_id"])
    if len(layouts) != 1 or len(schemas) != 1:
        raise DatasetError("No mezcles versiones de layout o esquemas de anchors en un radio-map.")
    if len(positions) != 15 or any(len(s) != 30 or len(set(s)) < 3 for s in positions.values()):
        raise DatasetError("Cada posición requiere 30 muestras de al menos tres sesiones físicas.")
    if {str(i) for i in manifest["training_sample_ids"]} != ids:
        raise DatasetError("Los IDs seleccionados no coinciden con el manifiesto.")
    return RadioMap(rows, anchors, bounds, {
        "kind": "measured", "training_sha256": digest, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_sha256": manifest["source_sha256"],
        "policy": "rssi-policy-v1", "baseline_calibration": "snapshot_at_export",
    })


def load_export(csv_bytes: bytes, manifest_bytes: bytes) -> RadioMap:
    """Check integrity and readiness; hashes are not proof of physical truth."""
    try:
        return _load_export(csv_bytes, manifest_bytes)
    except DatasetError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, csv.Error) as exc:
        raise DatasetError("Export incompleto o mal formado. Vuelve a derivar CSV y manifiesto.") from exc


def make_demo() -> RadioMap:
    """Deterministic synthetic log-distance fixture; never represents real accuracy."""
    rng = np.random.default_rng(SEED)
    anchors = [dict(node_id=f"DEMO_{i}", pos_x=x, pos_y=y, rssi_1m=-48.0, n_pathloss=2.2)
               for i, (x, y) in enumerate(((0, 0), (4, 0), (0, 2)), 1)]
    rows = []
    for session in range(4):
        drift = rng.normal(0, 1.0, 3)
        for y in range(3):
            for x in range(5):
                for repeat in range(3):
                    signal = [-48 - 22 * math.log10(max(0.4, math.hypot(x-a["pos_x"], y-a["pos_y"])))
                              + drift[i] + rng.normal(0, 0.8) for i, a in enumerate(anchors)]
                    rows.append(dict(sample_id=f"demo-{len(rows)+1}", session_id=f"demo-session-{session}",
                                     campaign_id="demo-campaign", x_real=float(x), y_real=float(y),
                                     **dict(zip(FEATURES, signal))))
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return RadioMap(rows, anchors, (4.0, 2.0), {
        "kind": "synthetic", "training_sha256": digest, "generator": "log-distance-demo-v1",
        "seed": SEED, "baseline_calibration": "synthetic_generator",
    })


class FingerprintModel:
    """Strict complete-fingerprint inference; unknown/missing anchors never become zeros."""
    def __init__(self, method="wknn", k=5, max_depth=6):
        if method not in ("wknn", "tree") or not 1 <= k <= 50 or not 1 <= max_depth <= 20:
            raise DatasetError("Método o parámetros inválidos.")
        self.method, self.k, self.max_depth = method, int(k), int(max_depth)

    def fit(self, X, y, anchor_ids):
        X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
        if X.ndim != 2 or X.shape[1] != 3 or y.shape != (len(X), 2) or len(X) < 2:
            raise DatasetError("Se requieren al menos dos fingerprints completos para entrenar.")
        if not np.isfinite(X).all() or not np.isfinite(y).all() or (X < -150).any() or (X > 0).any():
            raise DatasetError("Features o coordenadas inválidas.")
        if len(set(anchor_ids)) != 3:
            raise DatasetError("Se requieren tres IDs de anchor distintos.")
        self.anchor_ids = tuple(anchor_ids)
        self.scaler = StandardScaler().fit(X)  # train only, never held-out captures
        self.X, self.y = self.scaler.transform(X), y.copy()
        self.min_rssi, self.max_rssi = X.min(axis=0), X.max(axis=0)
        if self.method == "tree":
            self.tree = DecisionTreeRegressor(max_depth=self.max_depth, min_samples_leaf=2, random_state=SEED)
            self.tree.fit(self.X, self.y)
        return self

    def predict(self, X):
        if not hasattr(self, "scaler"):
            raise DatasetError("Primero entrena el modelo con un radio-map validado.")
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != 3 or not np.isfinite(X).all() or (X < -150).any() or (X > 0).any():
            raise DatasetError("La consulta requiere tres RSSI finitos entre -150 y 0 dBm.")
        X = self.scaler.transform(X)
        if self.method == "tree":
            return self.tree.predict(X)
        predicted = []
        for query in X:
            distances = np.linalg.norm(self.X - query, axis=1)
            exact = distances <= 1e-12
            if exact.any():
                predicted.append(self.y[exact].mean(axis=0))
            else:
                neighbors = np.argsort(distances, kind="stable")[:self.k]
                predicted.append(np.average(self.y[neighbors], axis=0, weights=1/distances[neighbors]))
        return np.asarray(predicted)

    def locate(self, readings):
        if not hasattr(self, "anchor_ids"):
            raise DatasetError("Primero entrena el modelo.")
        if set(readings) != set(self.anchor_ids):
            raise DatasetError("Falta un anchor o hay IDs desconocidos; no se puede estimar.")
        values = np.array([_number(readings[i], i) for i in self.anchor_ids])
        position = self.predict([values])[0]
        outside = bool(((values < self.min_rssi) | (values > self.max_rssi)).any())
        return {"position": position.tolist(), "outside_training_rssi": outside,
                "warning": "RSSI fuera del rango observado; posición no validada." if outside else None}


def split_dataset(dataset, mode="group", held_position=(2.0, 1.0), seed=SEED):
    if mode not in ("group", "spatial"):
        raise DatasetError("Partición desconocida.")
    rows = dataset.rows
    group_key = "campaign_id" if len({r["campaign_id"] for r in rows}) >= 2 else "session_id"
    groups = sorted({r[group_key] for r in rows})
    if len(groups) < 2:
        raise DatasetError("Se requieren al menos dos grupos independientes para evaluar.")
    test_group = str(np.random.default_rng(seed).choice(groups))
    held_position = tuple(held_position)
    if mode == "spatial" and held_position not in {tuple(p) for p in dataset.y}:
        raise DatasetError("La posición reservada no existe en el dataset.")
    train, test, unused = [], [], []
    for i, row in enumerate(rows):
        held = (row["x_real"], row["y_real"]) == held_position
        if row[group_key] != test_group and (mode != "spatial" or not held):
            train.append(i)
        elif row[group_key] == test_group and (mode != "spatial" or held):
            test.append(i)
        else:
            unused.append(i)
    if len(train) < 2 or not test:
        raise DatasetError("La partición no deja suficientes muestras de entrenamiento y prueba.")
    return np.array(train), np.array(test), {
        "mode": mode, "seed": seed, "group_by": group_key, "test_group": test_group,
        "held_position": list(held_position) if mode == "spatial" else None,
        "train_ids": [rows[i]["sample_id"] for i in train],
        "test_ids": [rows[i]["sample_id"] for i in test],
        "unused_ids": [rows[i]["sample_id"] for i in unused],
        "limitation": "Una sola campaña: el holdout es por sesión, no demuestra generalización entre campañas."
                      if group_key == "session_id" else "Holdout entre campañas; confirma su independencia física.",
    }


def error_metrics(errors):
    values = np.asarray(errors, dtype=float)
    return {"n": len(values), "mean_m": float(values.mean()) if len(values) else None,
            "median_m": float(np.median(values)) if len(values) else None,
            "p90_m": float(np.quantile(values, .9)) if len(values) else None}


def compare(dataset, mode="group", held_position=(2.0, 1.0), k=5, max_depth=6):
    # The legacy implementation is reused exactly; no MQTT connection is created.
    from mqtt_manager import circulos, disRSSI
    train, test, split = split_dataset(dataset, mode, held_position)
    X, y = dataset.X, dataset.y
    predictions = {}
    for method in ("wknn", "tree"):
        model = FingerprintModel(method, k=k, max_depth=max_depth).fit(
            X[train], y[train], [a["node_id"] for a in dataset.anchors])
        predictions[method] = model.predict(X[test])
    circles = []
    for row in X[test]:
        distances = [disRSSI(v, a["rssi_1m"], a["n_pathloss"]) for v, a in zip(row, dataset.anchors)]
        point = circulos(distances, dataset.anchors, area_bounds=dataset.bounds)
        circles.append(point if point is not None else [np.nan, np.nan])
    predictions["circles"] = np.asarray(circles)
    common = np.logical_and.reduce([np.isfinite(p).all(axis=1) for p in predictions.values()])
    metrics, samples = {}, []
    for method, positions in predictions.items():
        available = np.isfinite(positions).all(axis=1)
        errors = np.linalg.norm(positions-y[test], axis=1)
        metrics[method] = {**error_metrics(errors[common]), "available": int(available.sum()),
                           "test_total": len(test), "coverage": float(available.mean())}
        for j, index in enumerate(test):
            samples.append({"sample_id": dataset.rows[index]["sample_id"], "method": method,
                            "x_real": float(y[index, 0]), "y_real": float(y[index, 1]),
                            "x": float(positions[j, 0]) if available[j] else None,
                            "y": float(positions[j, 1]) if available[j] else None,
                            "error_m": float(errors[j]) if available[j] else None,
                            "common": bool(common[j])})
    return {"schema_version": 1, "provenance": dataset.provenance, "split": split,
            "features": list(FEATURES), "parameters": {"k": k, "max_depth": max_depth, "min_samples_leaf": 2},
            "versions": {"python": platform.python_version(), "numpy": np.__version__, "sklearn": sklearn.__version__},
            "metrics": metrics, "samples": samples,
            "metric_scope": "Intersección de muestras con predicción válida en los tres métodos; error euclídeo en metros."}
