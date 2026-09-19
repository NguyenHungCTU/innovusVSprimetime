"""Pure normalization and metric functions. No EDA tool or GUI dependency."""
import csv
from pathlib import Path
from numeric import CAP_SCALE, TIME_SCALE, difference, number, read_json, rounded

METRICS = (
    "slack_ns", "tlaunch_ns", "tcapture_ns", "tck2q_ns", "tdata_ns",
    "tdata_plus_ck2q_ns", "phase_shift_ns", "si_data_ns", "si_launch_ns", "si_capture_ns",
    "cppr_native_ns", "uncertainty_native_ns", "arrival_native_ns", "required_native_ns",
)
IDENTITY = ("startpoint", "endpoint", "launch_clock", "capture_clock", "launch_edge", "capture_edge",
            "launch_edge_ns", "capture_edge_ns", "startpoint_transition", "endpoint_transition")


def typed_csv(path, types):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Invalid CSV header: " + str(path))
        if set(types) - set(reader.fieldnames):
            raise ValueError("Missing CSV fields: " + str(path))
        rows = []
        for row in reader:
            if None in row or None in row.values():
                raise ValueError("Malformed CSV row: " + str(path))
            for key, kind in types.items():
                value = row[key]
                if value == "":
                    row[key] = None
                elif kind in ("time", "cap", "number"):
                    row[key] = number(value)
                elif kind == "bool":
                    if value not in ("0", "1"):
                        raise ValueError("Invalid CSV bool: " + value)
                    row[key] = value == "1"
            rows.append(row)
        return rows


def read_pt(directory):
    """Read existing V1 output without importing or modifying the V1 code."""
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest.get("complete") is not True or str(manifest.get("schema_version", "")).split(".")[0] != "1":
        raise ValueError("Expected a complete PT V1 export directory")
    if (directory / "timing.json").is_file():
        data = read_json(directory / "timing.json")
        if data.get("metadata") != manifest["metadata"] or data.get("schema_version") != manifest["schema_version"]:
            raise ValueError("PT timing.json and manifest disagree")
    else:
        paths = typed_csv(directory / "paths.csv", manifest["path_field_types"])
        by_id = {p["path_id"]: p for p in paths}
        for path in paths:
            path["data_points"], path["clock_paths"] = [], []
        chains = {}
        for point in typed_csv(directory / "points.csv", manifest["point_field_types"]):
            path_id, role = point.pop("path_id"), point.pop("segment")
            chain_index = int(point.pop("chain_index"))
            if path_id not in by_id:
                raise ValueError("Orphan timing point: " + path_id)
            if role == "data":
                by_id[path_id]["data_points"].append(point)
            elif role in ("launch", "capture"):
                key = (path_id, role, chain_index)
                if key not in chains:
                    chains[key] = {"segment": role, "points": []}
                    by_id[path_id]["clock_paths"].append(chains[key])
                chains[key]["points"].append(point)
            else:
                raise ValueError("Unknown segment: " + str(role))
        data = {"schema_version": manifest["schema_version"], "metadata": manifest["metadata"], "paths": paths}
    if len(data["paths"]) != manifest["path_count"]:
        raise ValueError("PT path_count differs from manifest")
    if data["metadata"].get("time_unit") != "ns" or data["metadata"].get("capacitance_unit") != "pf":
        raise ValueError("PT V1 must contain normalized ns / pf")
    seen = set()
    for path in data["paths"]:
        path_id = path.get("path_id")
        if not path_id or path_id in seen:
            raise ValueError("Missing or duplicate PT path_id")
        seen.add(path_id)
        for key in ("analysis_type", "pba_mode", "design_revision", "comparison_context"):
            if path.get(key) != data["metadata"].get(key):
                raise ValueError("PT path/metadata disagree: " + key)
        if not path.get("startpoint") or not path.get("endpoint"):
            raise ValueError("PT path missing startpoint/endpoint")
        for points in [path.get("data_points", [])] + [c["points"] for c in path.get("clock_paths", [])]:
            if [int(p["index"]) for p in points] != list(range(1, len(points) + 1)):
                raise ValueError("Invalid PT point order in " + path_id)
    return data


def edge(value):
    if value is None:
        return None
    return {"r": "rise", "rising": "rise", "rise": "rise", "f": "fall", "falling": "fall", "fall": "fall"}.get(str(value).lower())


def position(points, name):
    indices = [i for i, point in enumerate(points) if name and point["name"] == name]
    return indices[0] if len(indices) == 1 else None


def segment(points, start, end):
    a, b = position(points, start), position(points, end)
    return points[a:b + 1] if a is not None and b is not None and a <= b else []


def span(points):
    return difference(points[-1]["arrival_native_ns"], points[0]["arrival_native_ns"]) if points else None


def topology(points):
    return [(p["name"], p["transition"]) for p in points]


def pt_points(points):
    return [{"name": p["object_name"], "transition": edge(p.get("transition")),
             "arrival_native_ns": number(p.get("arrival_native_ns")),
             "slew_ns": number(p.get("slew_ns")), "capacitance_pf": number(p.get("capacitance_pf")),
             "si_delta_native_ns": number(p.get("si_delta_native_ns")),
             "object_class": p.get("object_class"), "direction": p.get("direction")}
            for p in points if p.get("object_class") != "net"]


def pt_boundary(path):
    """CK -> Q only with observed sequential-cell ownership; never suffix guessing."""
    points = path.get("data_points", [])
    original = path["startpoint"]
    ck, begin = None, original
    starts = [p for p in points if p.get("object_name") == original]
    if path.get("launch_is_latch") is False and len(starts) == 1:
        p = starts[0]
        if p.get("cell_is_sequential") is True and p.get("cell_name"):
            if p.get("direction") in ("in", "input") and p.get("is_clock_pin") is True:
                outputs = [q for q in points if q.get("cell_name") == p["cell_name"]
                           and q.get("direction") in ("out", "output")]
                if len(outputs) == 1:
                    ck, begin = original, outputs[0]["object_name"]
            elif p.get("direction") in ("out", "output"):
                clocks = [q for q in points if q.get("cell_name") == p["cell_name"] and q.get("is_clock_pin") is True]
                if len(clocks) == 1:
                    ck = clocks[0]["object_name"]
    # A cell-name startpoint is supported only when V1 recorded a validated CK/Q.
    if ck is None and path.get("data_status") == "ok" and path.get("launch_clock_pin"):
        clocks = [p for p in points if p.get("object_name") == path["launch_clock_pin"]
                  and p.get("cell_is_sequential") is True and p.get("is_clock_pin") is True]
        if len(clocks) == 1 and original in (clocks[0].get("cell_name"), clocks[0]["object_name"]):
            outputs = [p for p in points if p.get("cell_name") == clocks[0]["cell_name"]
                       and p.get("direction") in ("out", "output")]
            if len(outputs) == 1:
                ck, begin = clocks[0]["object_name"], outputs[0]["object_name"]
    return ck, begin


def pt_clock_segments(path, role, sink):
    candidates = []
    sources = path.get(role + "_clock_sources", [])
    if path.get(role + "_is_propagated") is False:
        return []
    for chain in path.get("clock_paths", []):
        if chain["segment"] != role:
            continue
        points = pt_points(chain["points"])
        roots = [source for source in sources if position(points, source) is not None]
        if len(roots) == 1:
            cropped = segment(points, roots[0], sink)
            if cropped:
                candidates.append(cropped)
    return candidates[0] if len(candidates) == 1 else []


def si_summary(points):
    """Incoming net delta at receivers; signed, no crosstalk double-counting."""
    observed, missing, unknown, values = 0, 0, 0, []
    for point in points[1:]:
        kind, direction = point.get("object_class"), point.get("direction")
        if kind not in ("pin", "port") or direction not in ("in", "input", "out", "output", "inout"):
            unknown += 1
            continue
        receiver = (kind == "pin" and direction in ("in", "input", "inout")) or (kind == "port" and direction in ("out", "output", "inout"))
        if receiver:
            value = point.get("si_delta_native_ns")
            if value is None:
                missing += 1
            else:
                observed += 1
                values.append(value)
    complete = observed > 0 and missing == 0 and unknown == 0
    return {"status": "complete" if complete else ("partial" if observed else "unavailable"),
            "sum_ns": sum(values) if complete else None,
            "observed_sum_ns": sum(values) if values else None,
            "observed": observed, "missing": missing, "unclassified": unknown}


def base_row(target_id, index, path_id, analysis, group):
    return {"target_id": target_id, "golden_index": index, "source_path_id": path_id,
            "analysis_type": analysis, "golden_path_group": group, "view": None,
            "status": "ok", "identity": {}, "metrics": {}, "metric_status": {},
            "points": [], "clock_points": {"launch": [], "capture": []},
            "si_coverage": {}, "slack_check": {}, "native": {}, "boundaries": {}}


def calculate(row, ck, all_points, quantum, tolerance):
    metrics = row["metrics"]
    metrics["tdata_ns"] = span(row["points"])
    full = segment(all_points, ck, row["identity"].get("endpoint"))
    ck_to_q = segment(all_points, ck, row["identity"].get("startpoint"))
    metrics["tck2q_ns"] = span(ck_to_q)
    metrics["tdata_plus_ck2q_ns"] = span(full)
    for role, name in (("launch", "tlaunch_ns"), ("capture", "tcapture_ns")):
        metrics[name] = span(row["clock_points"][role])
    metrics["phase_shift_ns"] = (difference(row["identity"].get("capture_edge_ns"), row["identity"].get("launch_edge_ns"))
                                 if row["boundaries"].get("edge_triggered") else None)
    for role, points in [("data", row["points"]), ("launch", row["clock_points"]["launch"]), ("capture", row["clock_points"]["capture"])]:
        coverage = si_summary(points)
        row["si_coverage"][role] = coverage
        metrics["si_" + role + "_ns"] = coverage["sum_ns"]
    # Validate each tool's OWN reference convention; do not shift required by
    # launch edge to force agreement. A mismatch is exported, not concealed.
    a, r, s = (metrics.get(name) for name in ("arrival_native_ns", "required_native_ns", "slack_ns"))
    expected = difference(r, a) if row["analysis_type"] == "max" else difference(a, r)
    expected = rounded(expected, quantum)
    err = difference(expected, rounded(s, quantum))
    row["slack_check"] = {"recomputed_ns": rounded(expected, quantum), "error_ns": rounded(err, quantum),
                          "status": "missing_inputs" if err is None else ("ok" if abs(rounded(err, quantum)) <= tolerance else "native_reference_mismatch")}
    for name in METRICS:
        metrics[name] = rounded(metrics.get(name), quantum)
        row["metric_status"][name] = "available" if metrics[name] is not None else "unavailable"
    for points in [row["points"]] + list(row["clock_points"].values()):
        previous = None
        for point in points:
            arrival = point.get("arrival_native_ns")
            point["step_delay_ns"] = rounded(difference(arrival, previous), quantum)
            previous = arrival
            for name in ("arrival_native_ns", "slew_ns", "si_delta_native_ns"):
                point[name] = rounded(point.get(name), quantum)
    for name in ("launch_edge_ns", "capture_edge_ns"):
        row["identity"][name] = rounded(row["identity"].get(name), quantum)
    return row


def normalize_pt(path, index, quantum, tolerance):
    ck, begin = pt_boundary(path)
    points = pt_points(path.get("data_points", []))
    row = base_row("T%07d" % index, index, path["path_id"], path["analysis_type"], path.get("path_group"))
    row["native"] = {key: value for key, value in path.items() if key not in ("data_points", "clock_paths", "attributes", "calculations")}
    row["view"] = path.get("scenario")
    row["points"] = segment(points, begin, path["endpoint"])
    capture_prefix = "capture_open_edge" if path["analysis_type"] == "min" else "capture_close_edge"
    row["identity"] = {"startpoint": begin, "endpoint": path["endpoint"],
                       "launch_clock": path.get("launch_clock"), "capture_clock": path.get("capture_clock"),
                       "launch_edge": edge(path.get("launch_edge")), "capture_edge": edge(path.get(capture_prefix)),
                       "launch_edge_ns": number(path.get("launch_edge_ns")), "capture_edge_ns": number(path.get(capture_prefix + "_ns")),
                       "startpoint_transition": row["points"][0]["transition"] if row["points"] else None,
                       "endpoint_transition": row["points"][-1]["transition"] if row["points"] else None}
    for role, sink in (("launch", ck), ("capture", path.get("capture_clock_pin"))):
        row["clock_points"][role] = pt_clock_segments(path, role, sink)
    row["boundaries"] = {"original_startpoint": path["startpoint"], "launch_ck": ck, "data_begin": begin,
                         "capture_ck": path.get("capture_clock_pin"),
                         "edge_triggered": path.get("launch_is_latch") is False and path.get("capture_is_latch") is False}
    for name in ("slack_ns", "cppr_native_ns", "uncertainty_native_ns"):
        row["metrics"][name] = number(path.get(name))
    row["metrics"]["arrival_native_ns"] = number(path.get("arrival_ns"))
    row["metrics"]["required_native_ns"] = number(path.get("required_ns"))
    return calculate(row, ck, points, quantum, tolerance)


def innovus_value(record, key, cfg):
    prop = record.get("fields", {}).get(key, {})
    if prop.get("status") != "ok":
        return None
    value = prop.get("value")
    kind = prop.get("kind")
    if kind in ("time", "cap", "number"):
        scale = "1"
        if kind == "time":
            scale = TIME_SCALE[cfg["time_unit"]]
        elif kind == "cap":
            scale = CAP_SCALE[cfg["cap_unit"]]
        return number(value) * number(scale)
    return value or None


def innovus_points(points, cfg):
    result = []
    for raw in points:
        p = {key: innovus_value(raw, key, cfg) for key in ("arrival_native_ns", "transition", "slew_ns", "capacitance_pf", "si_delta_native_ns", "object_class", "direction")}
        p["name"] = raw["name"]
        p["transition"] = edge(p["transition"])
        if p["object_class"] != "net":
            result.append(p)
    return result


def mapped(value, mapping, section="pins"):
    return mapping.get(section, {}).get(value, value)


def expected_identity(golden, mapping):
    result = dict(golden["identity"])
    for name in ("startpoint", "endpoint"):
        result[name] = mapped(result[name], mapping)
    for name in ("launch_clock", "capture_clock"):
        result[name] = mapped(result[name], mapping, "clocks")
    return result


def normalize_innovus(raw, golden, cfg, mapping, quantum, tolerance):
    row = base_row(golden["target_id"], golden["golden_index"], str(raw["candidate_index"]), golden["analysis_type"], golden["golden_path_group"])
    row["native"] = raw
    values = {key: innovus_value(raw, key, cfg) for key in raw["fields"]}
    if golden["analysis_type"] == "min":
        values["capture_edge"] = values.get("capture_open_edge")
        values["capture_edge_ns"] = values.get("capture_open_edge_ns")
    expected = expected_identity(golden, mapping)
    points = innovus_points(raw["points"], cfg)
    # Independent native start/end identity must agree with a known CK/Q pair.
    # Merely finding golden pins somewhere in a different candidate is not enough.
    ck = mapped(golden["boundaries"].get("launch_ck"), mapping)
    begin = values.get("startpoint")
    if ck and begin == ck and position(points, expected["startpoint"]) is not None:
        begin = expected["startpoint"]
    end = values.get("endpoint")
    row["view"] = values.get("view")
    row["points"] = segment(points, begin, end)
    row["identity"] = {key: values.get(key) for key in IDENTITY}
    row["identity"].update(startpoint=begin, endpoint=end, launch_edge=edge(values.get("launch_edge")), capture_edge=edge(values.get("capture_edge")),
                           startpoint_transition=row["points"][0]["transition"] if row["points"] else None,
                           endpoint_transition=row["points"][-1]["transition"] if row["points"] else None)
    row["boundaries"] = {"original_startpoint": values.get("startpoint"), "launch_ck": ck, "data_begin": begin,
                         "capture_ck": mapped(golden["boundaries"].get("capture_ck"), mapping),
                         "edge_triggered": golden["boundaries"].get("edge_triggered", False)}
    for role in ("launch", "capture"):
        ref_points = golden["clock_points"][role]
        if ref_points:
            root, sink = (mapped(p["name"], mapping) for p in (ref_points[0], ref_points[-1]))
            chains = [innovus_points(c, cfg) for c in raw.get("clock_paths", {}).get(role, [])]
            # Full-clock timing_points can contain the launch chain. Use it only
            # with the exact known root/sink; never first-row-to-last-row guesses.
            if not chains and role == "launch":
                chains = [points]
            spans = [segment(chain, root, sink) for chain in chains]
            spans = [p for p in spans if p]
            if len(spans) == 1:
                row["clock_points"][role] = spans[0]
    for name in ("slack_ns", "arrival_native_ns", "required_native_ns", "cppr_native_ns", "uncertainty_native_ns"):
        row["metrics"][name] = values.get(name)
    return calculate(row, ck, points, quantum, tolerance)
