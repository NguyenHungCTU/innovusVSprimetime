#!/usr/bin/env python3
"""Python 3.6+ standard-library reader and strict comparison for schema 1.x.

No GUI dependency. Import load_dataset(), summarize(), compare_datasets() from
Tk, web backend, notebook or a future Innovus adapter.
"""
import argparse
import collections
import csv
import json
import math
from pathlib import Path


def read_json(path):
    def reject_constant(value):
        raise ValueError("Non-finite JSON value: " + value)
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream, parse_constant=reject_constant)


def read_csv(path, types):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("Duplicate CSV columns: " + str(path))
        if set(types) - set(headers):
            raise ValueError("Missing CSV columns: " + str(set(types) - set(headers)))
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed CSV row in " + str(path))
            for name, kind in types.items():
                value = row[name]
                if value == "":
                    row[name] = None
                elif kind in ("time", "cap", "number"):
                    row[name] = float(value)
                elif kind == "bool":
                    if value not in ("0", "1"):
                        raise ValueError("Invalid CSV boolean: " + value)
                    row[name] = value == "1"
            rows.append(row)
        return rows


def load_dataset(directory):
    """Load a COMPLETE export directory. JSON preferred, CSV-only also supported."""
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest.get("complete") is not True:
        raise ValueError("Export is not complete")
    if str(manifest.get("schema_version", "")).split(".")[0] != "1":
        raise ValueError("Unsupported schema_version")
    if (directory / "timing.json").is_file():
        data = read_json(directory / "timing.json")
        if data.get("schema_version") != manifest["schema_version"]:
            raise ValueError("Schema differs between timing.json and manifest")
        if data.get("metadata") != manifest["metadata"]:
            raise ValueError("Metadata differs between timing.json and manifest")
    else:
        paths = read_csv(directory / "paths.csv", manifest["path_field_types"])
        by_id = {p["path_id"]: p for p in paths}
        for p in paths:
            p["data_points"], p["clock_paths"] = [], []
        chains = {}
        points = read_csv(directory / "points.csv", manifest["point_field_types"])
        for point in points:
            path_id = point.pop("path_id")
            segment = point.pop("segment")
            chain_index = int(point.pop("chain_index"))
            point["net_names"] = json.loads(point.pop("net_names_json"))
            if path_id not in by_id:
                raise ValueError("Point refers to an unknown path_id: " + path_id)
            if segment == "data":
                by_id[path_id]["data_points"].append(point)
            elif segment in ("launch", "capture"):
                key = (path_id, segment, chain_index)
                if key not in chains:
                    chains[key] = {"segment": segment, "chain_index": chain_index, "points": []}
                    by_id[path_id]["clock_paths"].append(chains[key])
                chains[key]["points"].append(point)
            else:
                raise ValueError("Unknown point segment: " + segment)
        data = {"schema_version": manifest["schema_version"], "metadata": manifest["metadata"], "paths": paths}
    data["manifest"] = manifest
    validate_dataset(data)
    return data


def check_typed_fields(record, types):
    for name, kind in types.items():
        if name not in record:
            raise ValueError("Missing field: " + name)
        value = record[name]
        if value is None:
            continue
        if kind in ("time", "cap", "number"):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError("Invalid numeric field: " + name)
        elif kind == "bool":
            if not isinstance(value, bool):
                raise ValueError("Invalid boolean field: " + name)
        elif not isinstance(value, str):
            raise ValueError("Invalid text field: " + name)


def validate_dataset(data):
    manifest = data["manifest"]
    metadata = data["metadata"]
    if metadata.get("time_unit") != "ns" or metadata.get("capacitance_unit") != "pf":
        raise ValueError("Expected normalized ns / pf units")
    if len(data["paths"]) != manifest["path_count"]:
        raise ValueError("Path count differs from manifest")
    seen = set()
    for path in data["paths"]:
        check_typed_fields(path, manifest["path_field_types"])
        if not path.get("path_id") or path["path_id"] in seen:
            raise ValueError("Missing or duplicate path_id")
        seen.add(path["path_id"])
        for name in ("run_id", "comparison_context", "scenario", "design_revision", "analysis_type", "pba_mode"):
            if path[name] != metadata[name]:
                raise ValueError("Path metadata mismatch: " + name)
        if not path.get("startpoint") or not path.get("endpoint"):
            raise ValueError("Missing startpoint / endpoint")
        chains = [path["data_points"]] + [c["points"] for c in path["clock_paths"]]
        for points in chains:
            for expected_index, point in enumerate(points, 1):
                check_typed_fields(point, manifest["point_field_types"])
                if point["index"] != expected_index:
                    raise ValueError("Point order/index is invalid")
    return data


def summarize(data):
    result = {}
    groups = collections.defaultdict(list)
    for path in data["paths"]:
        groups[path["path_group"]].append(path)
    for group, paths in sorted(groups.items()):
        slacks = [p["slack_ns"] for p in paths if p["slack_ns"] is not None]
        result[group] = {
            "exported_paths": len(paths),
            "violating_exported_paths": sum(s < 0 for s in slacks),
            "worst_exported_slack_ns": min(slacks) if slacks else None,
            "si_data_complete_paths": sum(p["si_data_status"] == "complete" for p in paths),
            "slack_check_mismatches": sum(p["slack_check_status"] == "mismatch" for p in paths),
        }
    # These are SAMPLE statistics, not design WNS/TNS/violation endpoint totals.
    return {"run_id": data["metadata"]["run_id"], "path_count": len(data["paths"]), "groups": result}


IDENTITY_FIELDS = (
    "comparison_context", "analysis_type", "path_group", "startpoint", "endpoint",
    "launch_clock", "capture_clock", "launch_edge", "capture_open_edge",
    "capture_close_edge", "launch_edge_ns", "capture_open_edge_ns",
    "capture_close_edge_ns", "startpoint_transition", "endpoint_transition",
    "launch_is_latch", "capture_is_latch",
)
COMPARE_FIELDS = (
    "slack_ns", "arrival_ns", "required_ns", "tlaunch_ns", "tcapture_ns",
    "tck2q_ns", "tdata_ns", "tdata_plus_ck2q_ns", "phase_shift_ns",
    "cppr_native_ns", "uncertainty_native_ns", "setup_native_ns", "hold_native_ns",
    "si_data_complete_sum_ns", "si_launch_complete_sum_ns", "si_capture_complete_sum_ns",
)


def topology(path):
    return tuple((p["object_name"], p["transition"]) for p in path["data_points"])


def identity(path, match_mode):
    if any(path.get(k) is None for k in ("startpoint_transition", "endpoint_transition")):
        return None
    for role in ("launch", "capture"):
        if path.get(role + "_clock") is not None:
            required = ("launch_edge", "launch_edge_ns") if role == "launch" else (
                "capture_open_edge", "capture_open_edge_ns", "capture_close_edge", "capture_close_edge_ns")
            if any(path.get(k) is None for k in required):
                return None
    # Round only edge identity to 1e-9 ns, eliminating binary conversion noise.
    # Exported metric values and the comparison deltas retain full precision.
    key = tuple(round(path[k], 9) if k.endswith("_ns") and path.get(k) is not None
                else path.get(k) for k in IDENTITY_FIELDS)
    if match_mode == "topology":
        if not path["data_points"] or any(p["transition"] is None for p in path["data_points"]):
            return None
        key += (topology(path),)
    return key


def compare_datasets(reference, candidate, match_mode="topology", tolerance_ns=1e-6):
    """Return candidate-minus-reference deltas. Ambiguous keys are never auto-paired.

    Both inputs must already use the same schema AND metric semantics. An Innovus
    adapter must normalize signs/definitions before using fields named *_native_ns.
    """
    if match_mode not in ("topology", "endpoints"):
        raise ValueError("Unknown match mode")
    if not math.isfinite(tolerance_ns) or tolerance_ns < 0:
        raise ValueError("tolerance_ns must be finite and >= 0")
    for name in ("comparison_context", "design_revision", "analysis_type", "pba_mode", "time_unit"):
        if reference["metadata"][name] != candidate["metadata"][name]:
            raise ValueError("Incompatible comparison metadata: " + name)
    buckets = [collections.defaultdict(list), collections.defaultdict(list)]
    rows = []
    for side, dataset in enumerate((reference, candidate)):
        for path in dataset["paths"]:
            key = identity(path, match_mode)
            if key is None:
                rows.append({"status": "missing_identity", "side": "reference" if side == 0 else "candidate", "path_id": path["path_id"]})
            else:
                buckets[side][key].append(path)
    for key in sorted(set(buckets[0]) | set(buckets[1]), key=repr):
        refs, cands = buckets[0][key], buckets[1][key]
        row = {"reference_path_ids": [p["path_id"] for p in refs], "candidate_path_ids": [p["path_id"] for p in cands]}
        if len(refs) > 1 or len(cands) > 1:
            row["status"] = "ambiguous"
        elif not refs or not cands:
            row["status"] = "missing_reference" if not refs else "missing_candidate"
        else:
            ref, cand = refs[0], cands[0]
            row.update(status="matched", topology_equal=topology(ref) == topology(cand),
                       reference_slack_check=ref["slack_check_status"],
                       candidate_slack_check=cand["slack_check_status"])
            metrics = {}
            for field in COMPARE_FIELDS:
                a, b = ref.get(field), cand.get(field)
                status = "available"
                if a is None or b is None:
                    status = "missing_value"
                if field.endswith("_native_ns") and reference["metadata"].get("tool") != candidate["metadata"].get("tool"):
                    status = "requires_semantic_mapping"
                delta = b - a if status == "available" else None
                metrics[field] = {"reference": a, "candidate": b, "delta_ns": delta,
                                  "status": status, "within_tolerance": None if delta is None else abs(delta) <= tolerance_ns}
            row["metrics"] = metrics
        rows.append(row)
    return {"comparison_schema_version": "1.0",
            "reference_metadata": reference["metadata"], "candidate_metadata": candidate["metadata"],
            "delta_convention": "candidate_minus_reference", "match_mode": match_mode,
            "tolerance_ns": tolerance_ns, "rows": rows,
            "counts": dict(collections.Counter(row["status"] for row in rows))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    for cmd in ("validate", "summary"):
        command = sub.add_parser(cmd)
        command.add_argument("directory")
    command = sub.add_parser("compare")
    command.add_argument("reference")
    command.add_argument("candidate")
    command.add_argument("--match", choices=("topology", "endpoints"), default="topology")
    command.add_argument("--tolerance-ns", type=float, default=1e-6)
    command.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.command:
        parser.error("choose validate, summary or compare")
    try:
        if args.command == "compare":
            result = compare_datasets(load_dataset(args.reference), load_dataset(args.candidate), args.match, args.tolerance_ns)
            # Refuse to overwrite a previous comparison.
            with Path(args.output).open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write("\n")
            print(json.dumps(result["counts"], ensure_ascii=False))
        else:
            data = load_dataset(args.directory)
            result = summarize(data) if args.command == "summary" else {"valid": True, "path_count": len(data["paths"])}
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, "ERROR: {}\n".format(error))


if __name__ == "__main__":
    main()
