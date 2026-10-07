"""Reproducible offline comparison CLI; only writes the requested report."""
import argparse
import json
from pathlib import Path
import sys

# Support both python -m tools.compare_positioning and direct invocation.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from positioning import DatasetError, compare, load_export, make_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="Synthetic data; not a real benchmark")
    source.add_argument("--training", type=Path, help="Validated training.csv")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--reviewed-context", action="store_true", help="Operator reviewed physical independence and calibration")
    parser.add_argument("--mode", choices=["group", "spatial"], default="group")
    parser.add_argument("--hold-position", nargs=2, type=float, default=[2, 1], metavar=("X", "Y"))
    parser.add_argument("--neighbors", type=int, default=5)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.demo:
            dataset = make_demo()
        else:
            if args.manifest is None or not args.reviewed_context:
                parser.error("--training requires --manifest and --reviewed-context")
            if args.output.resolve() in {args.training.resolve(), args.manifest.resolve()}:
                parser.error("El reporte no puede sobrescribir un archivo de entrada.")
            dataset = load_export(args.training.read_bytes(), args.manifest.read_bytes())
        report = compare(dataset, args.mode, args.hold_position, args.neighbors, args.max_depth)
        # Exclusive create protects existing exports/results, including symlink targets.
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (DatasetError, OSError) as exc:
        parser.error(str(exc))
    print(f"Comparación {dataset.provenance['kind']}: {args.output}")


if __name__ == "__main__":
    main()
