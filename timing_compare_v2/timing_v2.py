#!/usr/bin/env python3
"""PT-golden ordered Innovus collection / comparison. Python 3.6+, stdlib only."""
import argparse
import collections
import csv
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

from dataset import (IDENTITY, METRICS, expected_identity, mapped, normalize_innovus,
                     normalize_pt, read_pt, topology, base_row)
from numeric import CAP_SCALE, TIME_SCALE, difference, json_text, number, read_json, rounded, write_json

VERSION = "2.0.0"
DEFAULT_SEMANTICS = {"si_delta_contract": "unverified", "cppr_factor": None,
                     "uncertainty_factor": None, "native_times_comparable": False}
CSV_ID = ("target_id", "golden_index", "source_path_id", "analysis_type", "golden_path_group", "view", "status")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def new_directory(path):
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise ValueError("Output directory is not empty: " + str(path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_csv(path, columns, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (format(value, "f") if hasattr(value, "as_tuple") else value)
                             for key, value in row.items()})


def paths_csv(path, rows):
    columns = list(CSV_ID) + list(IDENTITY) + list(METRICS) + [name + "_status" for name in METRICS]
    flat = []
    for row in rows:
        out = {key: row.get(key) for key in CSV_ID}
        out.update({key: row["identity"].get(key) for key in IDENTITY})
        out.update({key: row["metrics"].get(key) for key in METRICS})
        out.update({key + "_status": row["metric_status"].get(key) for key in METRICS})
        flat.append(out)
    write_csv(path, columns, flat)


def tcl_word(value):
    """Quote Tcl syntax, including literal $, brackets, backslashes and newlines."""
    value = "" if value is None else str(value)
    for old, new in (("\\", "\\\\"), ('"', '\\"'), ("$", "\\$"), ("[", "\\["), ("]", "\\]"), ("\n", "\\n"), ("\r", "\\r")):
        value = value.replace(old, new)
    return '"' + value + '"'


def tcl_dict(values):
    return "[dict create " + " ".join(tcl_word(k) + " " + tcl_word(v) for k, v in values.items()) + "]"


def validate_semantics(profile):
    if set(profile) - set(DEFAULT_SEMANTICS):
        raise ValueError("Unknown semantic profile fields")
    result = dict(DEFAULT_SEMANTICS)
    result.update(profile)
    if result["si_delta_contract"] not in ("unverified", "receiver_net_delta"):
        raise ValueError("si_delta_contract must be unverified or receiver_net_delta")
    for name in ("cppr_factor", "uncertainty_factor"):
        if result[name] is not None:
            result[name] = number(result[name])
            if result[name] not in (number("1"), number("-1")):
                raise ValueError(name + " must be null, 1 or -1")
    if type(result["native_times_comparable"]) is not bool:
        raise ValueError("native_times_comparable must be boolean")
    return result


def validate_mapping(mapping):
    if not isinstance(mapping, dict) or set(mapping) - {"pins", "clocks"}:
        raise ValueError("Name map must contain only pins / clocks dictionaries")
    for section in mapping.values():
        if not isinstance(section, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v for k, v in section.items()):
            raise ValueError("Name mappings must be nonempty string -> string")
        if len(set(section.values())) != len(section):
            raise ValueError("Many-to-one name mapping is ambiguous")
    return mapping


def prepare(args):
    quantum, tolerance = number(args.quantum_ns), number(args.tolerance_ns)
    if quantum is None or quantum < number("1e-12") or quantum > 1 or tolerance is None or tolerance < 0:
        raise ValueError("Require 1e-12 <= quantum-ns <= 1 and tolerance-ns >= 0")
    if quantum.normalize().as_tuple().digits != (1,):
        raise ValueError("quantum-ns must be a power of ten, e.g. 0.000001")
    if args.candidate_limit < 1 or (args.max_paths is not None and args.max_paths < 1):
        raise ValueError("Path limits must be positive integers")
    source = read_pt(args.pt)
    pba = source["metadata"].get("pba_mode")
    if pba not in ("none", "path", "exhaustive"):
        raise ValueError("Unknown PT pba_mode; do not silently assume GBA")
    if (pba == "none") != (args.retime == "none"):
        raise ValueError("PT/Innovus GBA/PBA mismatch: choose --retime consistent with PT pba_mode")
    mapping = validate_mapping(read_json(args.name_map) if args.name_map else {})
    semantics = validate_semantics(read_json(args.semantics) if args.semantics else {})
    paths = source["paths"]
    if args.group:
        for pattern in args.group:
            if not any(fnmatch.fnmatchcase(p.get("path_group") or "", pattern) for p in paths):
                raise ValueError("No PT path group matches " + pattern)
        paths = [p for p in paths if any(fnmatch.fnmatchcase(p.get("path_group") or "", pattern) for pattern in args.group)]
    if args.max_paths is not None:
        paths = paths[:args.max_paths]
    if not paths:
        raise ValueError("No PT paths selected")
    for path in paths:
        if path["analysis_type"] not in ("max", "min"):
            raise ValueError("Only max/min path analysis is supported")
    rows = [normalize_pt(p, i, quantum, tolerance) for i, p in enumerate(paths, 1)]
    job = new_directory(args.job)
    config = {"view": args.view or "", "candidate_limit": args.candidate_limit, "retime": args.retime,
              "time_unit": args.time_unit, "cap_unit": args.cap_unit}
    job_id = hashlib.sha256(json_text({"paths": paths, "config": config, "mapping": mapping,
                                      "semantics": semantics, "quantum_ns": quantum, "match": args.match}).encode("utf-8")).hexdigest()
    config["job_id"] = job_id
    golden = {"schema_version": "2.0", "job_id": job_id, "tool": "PrimeTime", "time_unit": "ns",
              "quantum_ns": quantum, "source_metadata": source["metadata"], "paths": rows}
    write_json(job / "golden.json", golden)
    paths_csv(job / "golden_paths.csv", rows)
    targets = []
    for row in rows:
        targets.append({"target_id": row["target_id"], "golden_index": row["golden_index"],
                        "query_from": mapped(row["boundaries"].get("launch_ck") or row["identity"]["startpoint"], mapping),
                        "query_to": mapped(row["identity"]["endpoint"], mapping), "analysis_type": row["analysis_type"]})
    lines = ["# Generated by timing_v2.py prepare. Query order is the PT export order.",
             "namespace eval ::iv2 {}", "set ::iv2::job_config " + tcl_dict(config), "set ::iv2::targets {}"]
    lines += ["lappend ::iv2::targets " + tcl_dict(target) for target in targets]
    (job / "targets.tcl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(job / "job.json", {"version": VERSION, "job_id": job_id, "config": config,
               "quantum_ns": quantum, "tolerance_ns": tolerance, "match": args.match,
               "mapping": mapping, "semantics": semantics, "golden_sha256": digest(job / "golden.json"),
               "targets": targets, "targets_sha256": digest(job / "targets.tcl")})
    print("Prepared %d PT targets in %s" % (len(rows), job))
    print("Innovus: source innovus_collect.tcl; iv2::run %s/targets.tcl %s/innovus_raw.jsonl" % (job, job))


def read_raw(path, job):
    with Path(path).open(encoding="utf-8") as stream:
        records = [json.loads(line, parse_float=number, parse_constant=lambda s: number(s)) for line in stream if line.strip()]
    if len(records) < 2 or records[0].get("record_type") != "header" or records[-1].get("record_type") != "footer":
        raise ValueError("Incomplete Innovus JSONL: missing header/footer")
    header, footer = records[0], records[-1]
    if header.get("schema_version") != "2.0" or header.get("job_id") != job["job_id"] or header.get("tool") != "Innovus":
        raise ValueError("Innovus file belongs to a different job or schema")
    for key, value in job["config"].items():
        if str(header.get("config", {}).get(key)) != str(value):
            raise ValueError("Innovus collector config differs from prepared job: " + key)
    if footer.get("complete") is not True or footer.get("target_count") != len(job["targets"]):
        raise ValueError("Incomplete target count")
    by_id = {}
    expected = {t["target_id"]: t for t in job["targets"]}
    for record in records[1:-1]:
        key = record.get("target_id")
        if record.get("record_type") != "target" or key not in expected or key in by_id:
            raise ValueError("Unknown or duplicate target record")
        target = expected[key]
        for field in ("golden_index", "query_from", "query_to"):
            if record.get(field) != target[field]:
                raise ValueError("Target changed: " + key + "/" + field)
        if record.get("status") not in ("ok", "not_found", "query_error"):
            raise ValueError("Unknown target status")
        if type(record.get("truncated")) is not bool or not isinstance(record.get("candidates"), list):
            raise ValueError("Invalid candidate record")
        if record["status"] != "ok" and record["candidates"]:
            raise ValueError("Failed target contains candidates")
        by_id[key] = record
    if set(by_id) != set(expected):
        raise ValueError("Missing target record; collection did not complete")
    return header, by_id


def match_reasons(golden, candidate, job):
    expected = expected_identity(golden, job["mapping"])
    actual = candidate["identity"]
    reasons = []
    for key in IDENTITY:
        a, b = expected.get(key), actual.get(key)
        if a is None or b is None:
            reasons.append("missing:" + key)
        elif a != b:
            reasons.append("different:" + key)
    if not candidate["view"]:
        reasons.append("missing:view")
    if job["config"]["view"] and candidate["view"] != job["config"]["view"]:
        reasons.append("different:view")
    pt_topo = [(mapped(p["name"], job["mapping"]), p["transition"]) for p in golden["points"]]
    same_topology = bool(pt_topo) and pt_topo == topology(candidate["points"])
    if job["match"] == "topology" and not same_topology:
        reasons.append("different:topology")
    return reasons, same_topology


def metric_comparison(ref, cand, field, semantics, tolerance, topology_equal):
    a, b = ref["metrics"].get(field), cand["metrics"].get(field)
    status = "available"
    if a is None or b is None:
        status = "missing_value"
    elif field.startswith("si_"):
        if semantics["si_delta_contract"] != "receiver_net_delta":
            status = "requires_semantic_mapping"
        elif field == "si_data_ns" and not topology_equal:
            status = "different_topology"
    elif field in ("cppr_native_ns", "uncertainty_native_ns"):
        factor = semantics[field.split("_")[0] + "_factor"]
        if factor is None:
            status = "requires_semantic_mapping"
        else:
            b *= factor
    elif field in ("arrival_native_ns", "required_native_ns"):
        if not semantics["native_times_comparable"]:
            status = "requires_reference_mapping"
        elif ref["slack_check"]["status"] != "ok" or cand["slack_check"]["status"] != "ok":
            status = "native_reference_mismatch"
    delta = difference(b, a) if status == "available" else None
    return {"pt_ns": a, "innovus_ns": b, "delta_ns": delta, "status": status,
            "within_tolerance": None if delta is None else abs(delta) <= tolerance}


def point_comparison(ref, cand, job, tolerance):
    result = []
    for role in ("data", "launch", "capture"):
        a = ref["points"] if role == "data" else ref["clock_points"][role]
        b = cand["points"] if role == "data" else cand["clock_points"][role]
        mapped_topo = [(mapped(p["name"], job["mapping"]), p["transition"]) for p in a]
        if not a or mapped_topo != topology(b):
            continue
        for index, (pa, pb) in enumerate(zip(a, b), 1):
            for field in ("step_delay_ns", "slew_ns", "si_delta_native_ns"):
                va, vb = pa.get(field), pb.get(field)
                status = "available" if va is not None and vb is not None else "missing_value"
                if field == "si_delta_native_ns" and status == "available" and job["semantics"]["si_delta_contract"] != "receiver_net_delta":
                    status = "requires_semantic_mapping"
                delta = difference(vb, va) if status == "available" else None
                result.append({"target_id": ref["target_id"], "golden_index": ref["golden_index"], "segment": role,
                               "point_index": index, "pt_pin": pa["name"], "innovus_pin": pb["name"], "metric": field,
                               "pt_ns": va, "innovus_ns": vb, "delta_ns": delta, "status": status,
                               "within_tolerance": None if delta is None else abs(delta) <= tolerance})
    return result


def compare(args):
    directory = Path(args.job)
    job = read_json(directory / "job.json")
    if digest(directory / "golden.json") != job["golden_sha256"] or digest(directory / "targets.tcl") != job["targets_sha256"]:
        raise ValueError("Prepared golden/targets changed. Run prepare into a new job directory.")
    golden = read_json(directory / "golden.json")
    header, raw = read_raw(args.innovus, job)
    tolerance = number(args.tolerance_ns) if args.tolerance_ns is not None else job["tolerance_ns"]
    if tolerance is None or tolerance < 0:
        raise ValueError("Tolerance must be >= 0")
    quantum = job["quantum_ns"]
    rows, candidates, point_rows = [], [], []
    # A repeat of an identical PT path cannot establish independent 1:1 pairing.
    def golden_key(path):
        mapped_topo = [(mapped(p["name"], job["mapping"]), p["transition"]) for p in path["points"]]
        return json_text([path["analysis_type"], expected_identity(path, job["mapping"]), mapped_topo])
    duplicates = collections.Counter(golden_key(p) for p in golden["paths"])
    observed_views = set()
    normalized = {}
    for ref in golden["paths"]:
        record = raw[ref["target_id"]]
        cs = [normalize_innovus(c, ref, job["config"], job["mapping"], quantum, tolerance) for c in record["candidates"]]
        normalized[ref["target_id"]] = cs
        observed_views.update(c["view"] for c in cs if c["view"])
    for ref in golden["paths"]:
        record = raw[ref["target_id"]]
        row = {"target_id": ref["target_id"], "golden_index": ref["golden_index"], "pt_path_id": ref["source_path_id"],
               "status": record["status"], "query_message": record["message"], "topology_equal": None,
               "metrics": {}, "candidate_checks": []}
        accepted = []
        for candidate in normalized[ref["target_id"]]:
            reasons, same = match_reasons(ref, candidate, job)
            row["candidate_checks"].append({"candidate_index": candidate["source_path_id"], "reasons": reasons})
            if not reasons:
                accepted.append((candidate, same))
        chosen = None
        if record["status"] != "ok":
            pass
        elif record["truncated"]:
            row["status"] = "candidate_limit"
        elif not job["config"]["view"] and len(observed_views) > 1:
            row["status"] = "multiple_views_select_view"
        elif duplicates[golden_key(ref)] > 1:
            row["status"] = "duplicate_golden"
        elif len(accepted) > 1:
            row["status"] = "ambiguous"
        elif not accepted:
            row["status"] = "no_matching_candidate"
        else:
            chosen, same = accepted[0]
            row["status"], row["topology_equal"] = "matched", same
            row["slack_check_pt"], row["slack_check_innovus"] = ref["slack_check"], chosen["slack_check"]
            for metric in METRICS:
                row["metrics"][metric] = metric_comparison(ref, chosen, metric, job["semantics"], tolerance, same)
            point_rows.extend(point_comparison(ref, chosen, job, tolerance))
        if chosen is None:
            chosen = base_row(ref["target_id"], ref["golden_index"], None, ref["analysis_type"], ref["golden_path_group"])
            chosen["status"] = row["status"]
            chosen["metrics"] = {name: None for name in METRICS}
            chosen["metric_status"] = {name: row["status"] for name in METRICS}
        candidates.append(chosen)
        rows.append(row)
    out = new_directory(args.out)
    counts = dict(collections.Counter(r["status"] for r in rows))
    result = {"schema_version": "2.0", "job_id": job["job_id"], "delta_convention": "Innovus_minus_PrimeTime",
              "time_unit": "ns", "quantum_ns": quantum, "tolerance_ns": tolerance,
              "semantics": job["semantics"], "counts": counts, "observed_innovus_views": sorted(observed_views),
              "context_note": "Same netlist/constraints/corner/parasitics is a session prerequisite, not inferred from scenario names.",
              "rows": rows}
    write_json(out / "comparison.json", result)
    write_json(out / "golden.json", golden)
    innovus = {"schema_version": "2.0", "job_id": job["job_id"], "tool": "Innovus", "time_unit": "ns",
               "quantum_ns": quantum, "source_metadata": header, "paths": candidates}
    write_json(out / "innovus.json", innovus)
    paths_csv(out / "golden_paths.csv", golden["paths"])
    paths_csv(out / "innovus_paths.csv", candidates)
    wide_rows = []
    for ref, row in zip(golden["paths"], rows):
        flat = {"target_id": row["target_id"], "golden_index": row["golden_index"], "status": row["status"],
                "startpoint": ref["identity"]["startpoint"], "endpoint": ref["identity"]["endpoint"], "topology_equal": row["topology_equal"]}
        for name in METRICS:
            metric = row["metrics"].get(name, {})
            for key in ("pt_ns", "innovus_ns", "delta_ns", "status", "within_tolerance"):
                flat[name + "__" + key] = metric.get(key)
        wide_rows.append(flat)
    write_csv(out / "comparison.csv", list(wide_rows[0]), wide_rows)
    point_columns = ("target_id", "golden_index", "segment", "point_index", "pt_pin", "innovus_pin", "metric", "pt_ns", "innovus_ns", "delta_ns", "status", "within_tolerance")
    write_csv(out / "point_comparison.csv", point_columns, point_rows)
    write_json(out / "summary.json", {"counts": counts, "selected_pt_paths": len(rows),
        "slack_relaxed_paths": sum(r["metrics"].get("slack_ns", {}).get("delta_ns") is not None and r["metrics"]["slack_ns"]["delta_ns"] > tolerance for r in rows),
        "slack_tightened_paths": sum(r["metrics"].get("slack_ns", {}).get("delta_ns") is not None and r["metrics"]["slack_ns"]["delta_ns"] < -tolerance for r in rows)})
    print("Compare: %s; output: %s" % (json_text(counts), out))
    if args.fail_unmatched and any(row["status"] != "matched" for row in rows):
        return 2
    return 0


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command")
    a = sub.add_parser("prepare", help="PT V1 output -> ordered golden + Innovus target job")
    a.add_argument("--pt", required=True, help="PT V1 directory with manifest.json and timing.json or CSV")
    a.add_argument("--job", required=True, help="New/empty job directory")
    a.add_argument("--view", help="Optional Innovus analysis view; omit only for one observed view")
    a.add_argument("--group", action="append", help="PT path group glob; repeatable; keeps PT file order")
    a.add_argument("--max-paths", type=int, help="First N selected PT paths; never a new WNS sort")
    a.add_argument("--candidate-limit", type=int, default=50, help="Per start/end pair; collector requests limit+1 to detect truncation")
    a.add_argument("--match", choices=("topology", "endpoints"), default="topology", help="Both modes check clocks, edges and transitions")
    a.add_argument("--time-unit", choices=sorted(TIME_SCALE), default="ns", help="Actual Innovus get_property time unit; declaration only (default ns)")
    a.add_argument("--cap-unit", choices=sorted(CAP_SCALE), default="pf", help="Actual Innovus get_property capacitance unit (default pf)")
    a.add_argument("--retime", choices=("none", "path_slew_propagation"), default="none", help="Explicit reporting mode, must agree with PT GBA/PBA intent")
    a.add_argument("--quantum-ns", default="0.000001", help="Common numeric quantum in ns (default 1 fs)")
    a.add_argument("--tolerance-ns", default="0.000001", help="Comparison/slack-check tolerance in ns")
    a.add_argument("--name-map", help="Optional JSON of exact PT->Innovus pins/clocks name maps")
    a.add_argument("--semantics", help="Optional checked SI/CPPR/uncertainty/reference profile JSON")
    b = sub.add_parser("compare", help="Innovus raw candidates -> same schema exports + comparison")
    b.add_argument("--job", required=True)
    b.add_argument("--innovus", required=True, help="Complete innovus_raw.jsonl from iv2::run")
    b.add_argument("--out", required=True, help="New/empty result directory")
    b.add_argument("--tolerance-ns", help="Override metric tolerance; does not change path matching")
    b.add_argument("--fail-unmatched", action="store_true", help="Exit 2 after writing results if any target was not matched")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.command is None:
        p.print_help()
        return 0
    try:
        return prepare(args) if args.command == "prepare" else compare(args)
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
