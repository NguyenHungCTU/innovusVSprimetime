#!/usr/bin/env python3
"""
PrimeTime parser - buoc 1: doc mot report va lay cac gia tri can debug.

Muc tieu cua file nay:
  1. Doc header cua moi timing path.
  2. Doc dong format "Point ... Incr Path" de biet report co cot nao.
  3. Bat dau doc detail sau dong gach ngang ngay duoi Point header.
  4. Tim launch clock row, endpoint data row va tinh:

       tlaunch          = launch_begin.Path - clock_source_latency.Incr
       tdata_plus_tck2q = endpoint.Path     - launch_begin.Path

  5. Giu raw data va debug log de sua format de dang.

Chua tinh tcapture trong version nay. Khong compare voi Innovus.

Chay:
  python3 pt_parser_step1_simple.py pt_setup.rpt \
      --unit ns --out-dir pt_parse_out --max-paths 10

Output:
  pt_parse_out/paths_raw.json
  pt_parse_out/parse_debug.log

Python 3.6+, chi dung standard library.
"""

from __future__ import print_function

import argparse
import gzip
import json
import os
import re
import sys


# =============================================================================
# SECTION 1 - FORMAT CONFIG: SUA PHAN NAY KHI REPORT FORMAT DOI
# =============================================================================

NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

# Khong lay so nam trong ten pin/cell, vi du U12, data[3], A[31:0].
NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_./\[\]:])(" + NUM + r")(?![A-Za-z0-9_./\[\]:])"
)

PATH_START_RE = re.compile(r"^\s*Startpoint\s*:", re.I)
PATH_END_RE = re.compile(r"^\s*slack(?:\s*\([^)]*\))?\s+", re.I)

HEADER_PATTERNS = {
    "startpoint": re.compile(r"^\s*Startpoint\s*:\s*(?P<value>\S+)", re.I),
    "endpoint": re.compile(r"^\s*Endpoint\s*:\s*(?P<value>\S+)", re.I),
    "path_group": re.compile(r"^\s*Path Groups?\s*:\s*(?P<value>.+?)\s*$", re.I),
    "path_type": re.compile(r"^\s*Path Type\s*:\s*(?P<value>max|min)\b", re.I),
    "scenario": re.compile(r"^\s*Scenario\s*:\s*(?P<value>\S+)", re.I),
}

# Tat ca occurrence deu duoc giu; khong overwrite dong dau bang dong cuoi.
TERM_PATTERNS = [
    ("data_arrival", re.compile(r"^\s*data arrival time\b", re.I)),
    ("data_required", re.compile(r"^\s*data required time\b", re.I)),
    ("slack", re.compile(r"^\s*slack(?:\s*\([^)]*\))?\b", re.I)),
    ("cppr", re.compile(r"^\s*clock reconvergence pessimism\b", re.I)),
    ("uncertainty", re.compile(r"^\s*(?:inter[- ]clock |clock )uncertainty\b", re.I)),
    ("clock_jitter", re.compile(r"^\s*clock jitter\b", re.I)),
    ("setup", re.compile(r"^\s*library setup time\b", re.I)),
    ("hold", re.compile(r"^\s*library hold time\b", re.I)),
    ("recovery", re.compile(r"^\s*library recovery time\b", re.I)),
    ("removal", re.compile(r"^\s*library removal time\b", re.I)),
    ("clock_source_latency", re.compile(r"^\s*clock source latency\b", re.I)),
    ("clock_network_delay", re.compile(r"^\s*clock network delay\b", re.I)),
    ("input_external_delay", re.compile(r"^\s*input external delay\b", re.I)),
    ("output_external_delay", re.compile(r"^\s*output external delay\b", re.I)),
    ("max_delay", re.compile(r"^\s*max_delay\b", re.I)),
    ("min_delay", re.compile(r"^\s*min_delay\b", re.I)),
]

CLOCK_EDGE_RE = re.compile(
    r"^\s*clock\s+(?P<clock>.+?)\s+"
    r"\((?P<edge>rise|fall)\s+edge\)\s*(?P<tail>.*?)\s*$",
    re.I,
)

POINT_HEADER_RE = re.compile(r"^\s*Point\b.*\bPath\b", re.I)
SEPARATOR_RE = re.compile(r"^\s*[-=]{3,}\s*$")
TRANSITION_RE = re.compile(r"(?:^|\s)([rf])(?=\s|$)", re.I)

# Gia tri timing thuong right-align voi cuoi ten cot. Cho phep lech nho do
# significant_digits khac nhau hoac report duoc can cot hoi khac.
COLUMN_END_TOLERANCE = 4

# Neu point bi wrap, dong dau thuong chi co "pin (cell)"; dong sau co cac so.
WRAPPED_POINT_RE = re.compile(
    r"^\s*(?P<point>\S+)(?:\s+\((?P<cell>[^)]*)\))?(?:\s+<-)?\s*$"
)

REQUIRED_HEADERS = ("startpoint", "endpoint", "path_group", "path_type")
REQUIRED_TERMS = ("data_arrival", "data_required", "slack")


# =============================================================================
# SECTION 2 - DOC FILE VA TACH TUNG PATH
# =============================================================================

def read_report(path):
    opener = gzip.open if path.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as stream:
        text = stream.read()
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")


def split_paths(text, max_paths=None):
    """Tach report tu Startpoint den slack, kem line number cua file goc."""
    paths = []
    current = None

    for line_no, line in enumerate(text.splitlines(), 1):
        if PATH_START_RE.match(line):
            if current:
                paths.append(current)
            current = {"start_line": line_no, "lines": []}

        if not current:
            continue

        current["lines"].append((line_no, line))

        if PATH_END_RE.match(line):
            paths.append(current)
            current = None
            if max_paths and len(paths) >= max_paths:
                return paths

    if current:
        paths.append(current)

    return paths[:max_paths] if max_paths else paths


# =============================================================================
# SECTION 3 - DOC SCHEMA COT DONG TU DONG "Point ... Path"
# =============================================================================

def normalize_column_name(name):
    """Dua label cot ve key JSON de doc/sua de hon."""
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    aliases = {
        "point": "point",
        "fanout": "fanout",
        "cap": "cap",
        "capacitance": "cap",
        "dtrans": "dtrans",
        "trans": "trans",
        "transition": "trans",
        "derate": "derate",
        "delta": "delta",
        "incr": "incr",
        "increment": "incr",
        "path": "path",
    }
    return aliases.get(key, key)


def parse_table_schema(line, line_no):
    """
    Vi du:
      Point      Cap  DTrans  Trans  Derate  Delta  Incr  Path

    Moi cot luu vi tri ket thuc label. PrimeTime right-align gia tri gan vi tri
    nay, nen ta co the biet 0.123 thuoc cot nao du cot co them/bot.
    """
    columns = []
    used_keys = {}

    for token in re.finditer(r"\S+", line):
        label = token.group(0)
        base_key = normalize_column_name(label)
        count = used_keys.get(base_key, 0) + 1
        used_keys[base_key] = count
        key = base_key if count == 1 else "{}_{}".format(base_key, count)
        columns.append({
            "label": label,
            "key": key,
            "start": token.start(),
            "end": token.end(),
            "value_anchor": token.end(),
        })

    keys = [column["key"] for column in columns]
    return {
        "line_no": line_no,
        "raw": line,
        "columns": columns,
        "keys": keys,
        "valid": bool(columns and columns[0]["key"] == "point" and "path" in keys),
    }


def get_number_matches(line):
    return list(NUMBER_RE.finditer(line))


def assign_values_to_columns(line, schema):
    """
    Gan numeric token vao cot co right-edge gan nhat.

    Khong dung "hai so cuoi". Neu report co Fanout/Cap/DTrans/... thi moi gia
    tri van vao dung key dua tren schema cua report do.
    """
    numeric_columns = [
        column for column in schema["columns"] if column["key"] != "point"
    ]
    values = {}
    assigned = []
    unmatched = []

    for match in get_number_matches(line):
        if not numeric_columns:
            unmatched.append(float(match.group(1)))
            continue

        candidates = sorted(
            numeric_columns,
            key=lambda column: abs(match.end() - column["value_anchor"]),
        )
        column = candidates[0]
        distance = abs(match.end() - column["value_anchor"])

        # Mot row khong duoc co hai numeric value trong cung mot cot.
        if distance <= COLUMN_END_TOLERANCE and column["key"] not in values:
            value = float(match.group(1))
            values[column["key"]] = value
            assigned.append({
                "column": column["key"],
                "value": value,
                "text": match.group(1),
                "start": match.start(),
                "end": match.end(),
                "anchor_distance": distance,
            })
        else:
            unmatched.append(float(match.group(1)))

    first_value_start = min(
        (item["start"] for item in assigned), default=None
    )
    return {
        "values": values,
        "numbers": [item["value"] for item in assigned],
        "assigned": assigned,
        "unmatched_numbers": unmatched,
        "first_value_start": first_value_start,
    }


def parse_row_columns(line, schema):
    data = assign_values_to_columns(line, schema)
    cut = data["first_value_start"]
    data["point_text"] = line[:cut].strip() if cut is not None else line.strip()
    data["incr"] = data["values"].get("incr")
    data["path"] = data["values"].get("path")
    return data


# =============================================================================
# SECTION 4 - NHAN DIEN TERM, CLOCK VA POINT ROW
# =============================================================================

def match_term(line):
    for name, pattern in TERM_PATTERNS:
        match = pattern.match(line)
        if match:
            return name, match
    return None, None


def point_identity(text):
    """Lay ten pin/port va cell tu phan ben trai cac cot numeric."""
    cleaned = text.strip()
    if not cleaned:
        return None

    match = WRAPPED_POINT_RE.match(cleaned)
    if not match:
        return None

    point = match.group("point")
    cell = match.group("cell")

    # Mot point row thuong la pin hierarchy, port (in/out), hoac co cell.
    # Dieu kien nay tranh nham prose/marker thanh point.
    is_port = cell is not None and cell.lower() in ("in", "out")
    if "/" not in point and cell is None and not is_port:
        return None

    return {"point": point, "cell": cell}


def make_point_event(line, line_no, schema, pending=None):
    """Parse point cung dong hoac ghep point bi wrap voi dong numeric ke tiep."""
    data = parse_row_columns(line, schema)
    identity = point_identity(data["point_text"])

    if pending and data["values"] and not identity and not data["point_text"]:
        identity = {"point": pending["point"], "cell": pending.get("cell")}
        data["wrapped_from_line"] = pending["line_no"]

    if not identity or not data["values"]:
        return None

    transitions = TRANSITION_RE.findall(line)
    data.update({
        "point": identity["point"],
        "cell": identity.get("cell"),
        "transition": transitions[-1].lower() if transitions else None,
        "line_no": line_no,
        "raw": line,
    })
    return data


def make_pending_point(line, line_no):
    """Neu line chi co ten point/cell, giu lai de ghep voi line sau."""
    identity = point_identity(line)
    if not identity:
        return None
    identity.update({"line_no": line_no, "raw": line})
    return identity


# =============================================================================
# SECTION 5 - CHON ROW VA TINH GIA TRI
# =============================================================================

def same_point(left, right):
    return left.rstrip("/") == right.rstrip("/")


def is_child_point(point, parent):
    parent = parent.rstrip("/")
    return point.startswith(parent + "/")


def parent_name(point):
    return point.rsplit("/", 1)[0] if "/" in point else None


def select_launch_begin_row(rows, startpoint):
    """
    Chon launch clock row.

    - Header la instance: lay child dau tien, thuong la CK/CP.
    - Header la Q/QN pin: lay sibling dau tien cung instance xuat hien truoc Q,
      thuong la CK/CP. Nhu vay endpoint - begin van gom ca tck2q.
    - Input port: dung exact row neu co.
    """
    exact_indexes = [
        index for index, row in enumerate(rows)
        if same_point(row["point"], startpoint)
    ]

    if exact_indexes:
        exact_index = exact_indexes[0]
        exact_row = rows[exact_index]
        parent = parent_name(startpoint)
        if parent:
            earlier_siblings = [
                row for row in rows[:exact_index]
                if parent_name(row["point"]) == parent
            ]
            if earlier_siblings:
                return earlier_siblings[0], "first earlier sibling of exact startpoint pin"
        return exact_row, "exact startpoint row"

    children = [row for row in rows if is_child_point(row["point"], startpoint)]
    if children:
        return children[0], "first child row of startpoint instance"

    # Fallback khi header/path naming khac nhe, de debug thay vi crash.
    start_parent = parent_name(startpoint)
    if start_parent:
        siblings = [
            row for row in rows if parent_name(row["point"]) == start_parent
        ]
        if siblings:
            return siblings[0], "fallback: first sibling of startpoint"

    return None, "not found"


def select_endpoint_row(rows, endpoint):
    """Endpoint data row: exact pin neu co, neu la instance thi child cuoi."""
    exact = [row for row in rows if same_point(row["point"], endpoint)]
    if exact:
        return exact[-1], "exact endpoint row"

    children = [row for row in rows if is_child_point(row["point"], endpoint)]
    if children:
        return children[-1], "last child row of endpoint instance"

    endpoint_parent = parent_name(endpoint)
    if endpoint_parent:
        siblings = [
            row for row in rows if parent_name(row["point"]) == endpoint_parent
        ]
        if siblings:
            return siblings[-1], "fallback: last sibling of endpoint"

    return None, "not found"


def select_capture_clock_row(rows, endpoint):
    """Chi chon raw capture clock row; version nay chua tinh tcapture."""
    # Thu endpoint nhu mot instance truoc (case pho bien: Endpoint: top/U_C).
    children = [row for row in rows if is_child_point(row["point"], endpoint)]
    if children:
        return children[0], "first capture child row of endpoint"

    exact = [row for row in rows if same_point(row["point"], endpoint)]
    if exact:
        return exact[0], "exact capture endpoint row"

    # Neu endpoint header la data pin (top/U_C/D), capture clock la sibling
    # (top/U_C/CK) nam duoi parent instance top/U_C.
    instance = parent_name(endpoint)
    if instance:
        siblings = [row for row in rows if is_child_point(row["point"], instance)]
        if siblings:
            return siblings[0], "first capture sibling of endpoint pin"

    return None, "not found"


def compact_row(row):
    if row is None:
        return None
    return {
        "line_no": row["line_no"],
        "point": row["point"],
        "cell": row.get("cell"),
        "transition": row.get("transition"),
        "values": row["values"],
        "incr": row.get("incr"),
        "path": row.get("path"),
        "raw": row["raw"],
    }


def first_term_in_section(result, name, section):
    for event in result["terms"].get(name, []):
        if event["section"] == section:
            return event
    return None


def calculate_basic_values(result):
    headers = result["headers"]
    startpoint = headers.get("startpoint", {}).get("value")
    endpoint = headers.get("endpoint", {}).get("value")
    launch_rows = result["points"]["launch_data"]
    capture_rows = result["points"]["capture_required"]

    launch_row, launch_reason = (None, "missing startpoint header")
    endpoint_row, endpoint_reason = (None, "missing endpoint header")
    capture_row, capture_reason = (None, "missing endpoint header")

    if startpoint:
        launch_row, launch_reason = select_launch_begin_row(launch_rows, startpoint)
    if endpoint:
        endpoint_row, endpoint_reason = select_endpoint_row(launch_rows, endpoint)
        capture_row, capture_reason = select_capture_clock_row(capture_rows, endpoint)

    source_event = first_term_in_section(
        result, "clock_source_latency", "launch_data"
    )

    launch_path = launch_row.get("path") if launch_row else None
    endpoint_path = endpoint_row.get("path") if endpoint_row else None
    source_latency_incr = source_event.get("incr") if source_event else None

    warnings = []
    tlaunch = None
    tdata_plus_tck2q = None

    if launch_row is None:
        warnings.append("Cannot calculate tlaunch: launch begin row not found")
    elif launch_path is None:
        warnings.append("Cannot calculate tlaunch: launch begin row has no Path value")

    if source_event is None:
        warnings.append("Cannot calculate tlaunch: launch clock source latency row not found")
    elif source_latency_incr is None:
        warnings.append("Cannot calculate tlaunch: clock source latency has no Incr value")

    if launch_path is not None and source_latency_incr is not None:
        tlaunch = launch_path - source_latency_incr

    if endpoint_row is None:
        warnings.append("Cannot calculate tdata_plus_tck2q: endpoint row not found")
    elif endpoint_path is None:
        warnings.append("Cannot calculate tdata_plus_tck2q: endpoint row has no Path value")
    elif launch_path is None:
        warnings.append("Cannot calculate tdata_plus_tck2q: launch Path value missing")
    else:
        tdata_plus_tck2q = endpoint_path - launch_path

    if capture_row is None:
        warnings.append("Capture clock row not found; tcapture remains raw/None")

    selected = {
        "launch_begin": {
            "reason": launch_reason,
            "row": compact_row(launch_row),
        },
        "endpoint_data": {
            "reason": endpoint_reason,
            "row": compact_row(endpoint_row),
        },
        "capture_clock_raw": {
            "reason": capture_reason,
            "row": compact_row(capture_row),
        },
        "clock_source_latency": source_event,
    }

    calculation = {
        "inputs": {
            "launch_begin_path": launch_path,
            "clock_source_latency_incr": source_latency_incr,
            "endpoint_path": endpoint_path,
        },
        "formulas": {
            "tlaunch": "launch_begin.Path - clock_source_latency.Incr",
            "tdata_plus_tck2q": "endpoint.Path - launch_begin.Path",
            "tcapture": "not calculated in this version",
        },
        "tlaunch": tlaunch,
        "tdata_plus_tck2q": tdata_plus_tck2q,
        "tcapture": None,
        "warnings": warnings,
    }
    return selected, calculation


# =============================================================================
# SECTION 6 - PARSE MOT PATH
# =============================================================================

def parse_path(block, path_id):
    result = {
        "path_id": path_id,
        "start_line": block["start_line"],
        "headers": {},
        "table_schema": None,
        "terms": {},
        "clock_edges": [],
        "points": {"launch_data": [], "capture_required": []},
        "selected_rows": {},
        "calculation": {},
        "unparsed_numeric_lines": [],
        "missing": [],
    }

    # 6.1 Header cua timing path.
    header_lines = set()
    for line_no, line in block["lines"]:
        for name, pattern in HEADER_PATTERNS.items():
            if name in result["headers"]:
                continue
            match = pattern.match(line)
            if match:
                result["headers"][name] = {
                    "value": match.group("value").strip(),
                    "line_no": line_no,
                    "raw": line,
                }
                header_lines.add(line_no)

    # 6.2 State machine:
    # header -> wait_separator -> launch_data -> capture_required -> final_summary
    section = "header"
    pending_point = None
    first_arrival_seen = False
    first_required_seen = False
    saw_detail_separator = False

    for line_no, line in block["lines"]:
        stripped = line.strip()

        if line_no in header_lines or not stripped:
            continue

        if POINT_HEADER_RE.match(line):
            result["table_schema"] = parse_table_schema(line, line_no)
            section = "wait_separator"
            pending_point = None
            continue

        if section == "wait_separator":
            if SEPARATOR_RE.match(line):
                section = "launch_data"
                saw_detail_separator = True
            continue

        if section == "header":
            continue

        # Separator o cuoi detail/summary khong phai data row.
        if SEPARATOR_RE.match(line):
            pending_point = None
            continue

        schema = result["table_schema"]
        if not schema or not schema["valid"]:
            continue

        # Clock edge row.
        match = CLOCK_EDGE_RE.match(line)
        if match:
            event = parse_row_columns(line, schema)
            event.update({
                "clock": match.group("clock").strip(),
                "edge": match.group("edge").lower(),
                "section": section,
                "line_no": line_no,
                "raw": line,
            })
            result["clock_edges"].append(event)
            pending_point = None
            continue

        # Timing term: source latency, arrival, required, CPPR, uncertainty...
        term_name, term_match = match_term(line)
        if term_match:
            event = parse_row_columns(line, schema)
            event.update({"section": section, "line_no": line_no, "raw": line})
            result["terms"].setdefault(term_name, []).append(event)
            pending_point = None

            # Chuyen section SAU KHI da luu marker vao section hien tai.
            if term_name == "data_arrival" and not first_arrival_seen:
                first_arrival_seen = True
                section = "capture_required"
            elif term_name == "data_required" and not first_required_seen:
                first_required_seen = True
                section = "final_summary"
            continue

        # Point row binh thuong hoac numeric continuation cua wrapped point.
        if section in ("launch_data", "capture_required"):
            point = make_point_event(line, line_no, schema, pending=pending_point)
            if point:
                result["points"][section].append(point)
                pending_point = None
                continue

            row_data = parse_row_columns(line, schema)
            if not row_data["values"]:
                candidate = make_pending_point(line, line_no)
                if candidate:
                    pending_point = candidate
                    continue

        # Bat ky dong numeric nao chua parse se vao day de debug format.
        numeric = parse_row_columns(line, schema)
        if numeric["values"] or numeric["unmatched_numbers"]:
            result["unparsed_numeric_lines"].append({
                "section": section,
                "line_no": line_no,
                "values": numeric["values"],
                "unmatched_numbers": numeric["unmatched_numbers"],
                "raw": line,
            })
        pending_point = None

    # 6.3 Validate extraction structure.
    for name in REQUIRED_HEADERS:
        if name not in result["headers"]:
            result["missing"].append("header:" + name)
    for name in REQUIRED_TERMS:
        if not result["terms"].get(name):
            result["missing"].append("term:" + name)
    if not result["table_schema"]:
        result["missing"].append("table_schema:Point header")
    elif not result["table_schema"]["valid"]:
        result["missing"].append("table_schema:invalid Point/Path columns")
    if result["table_schema"] and not saw_detail_separator:
        result["missing"].append("table_separator:after Point header")
    if not result["points"]["launch_data"]:
        result["missing"].append("points:launch_data")

    result["selected_rows"], result["calculation"] = calculate_basic_values(result)

    result["status"] = (
        "ERROR" if result["missing"]
        else "WARN" if (
            result["unparsed_numeric_lines"] or result["calculation"]["warnings"]
        )
        else "OK"
    )
    return result


# =============================================================================
# SECTION 7 - OUTPUT JSON + DEBUG LOG
# =============================================================================

def write_debug_log(path, parsed_paths):
    with open(path, "w", encoding="utf-8") as stream:
        for item in parsed_paths:
            stream.write("=" * 96 + "\n")
            stream.write("PATH {} | start line {} | status={}\n".format(
                item["path_id"], item["start_line"], item["status"]
            ))

            stream.write("\n[HEADERS]\n")
            for name in HEADER_PATTERNS:
                value = item["headers"].get(name)
                if value:
                    stream.write("  {} = {}  (line {})\n".format(
                        name, value["value"], value["line_no"]
                    ))
                else:
                    stream.write("  {} = <NOT FOUND>\n".format(name))

            stream.write("\n[TABLE FORMAT]\n")
            schema = item["table_schema"]
            if not schema:
                stream.write("  <Point header not found>\n")
            else:
                stream.write("  line {}: {}\n".format(schema["line_no"], schema["raw"]))
                stream.write("  valid={} | keys={}\n".format(
                    schema["valid"], schema["keys"]
                ))
                for column in schema["columns"]:
                    stream.write(
                        "    {:14s} key={:14s} start={:3d} end/anchor={:3d}\n".format(
                            column["label"], column["key"], column["start"],
                            column["value_anchor"]
                        )
                    )

            stream.write("\n[CLOCK EDGES]\n")
            for event in item["clock_edges"]:
                stream.write(
                    "  line {} | {:18s} | {} {} | values={}\n".format(
                        event["line_no"], event["section"], event["clock"],
                        event["edge"], event["values"]
                    )
                )

            stream.write("\n[TERMS]\n")
            for name, unused_pattern in TERM_PATTERNS:
                for event in item["terms"].get(name, []):
                    stream.write(
                        "  {:22s} line {} | {:18s} | values={}\n".format(
                            name, event["line_no"], event["section"], event["values"]
                        )
                    )
                    stream.write("      {}\n".format(event["raw"]))

            stream.write("\n[POINT ROWS]\n")
            for section_name in ("launch_data", "capture_required"):
                rows = item["points"][section_name]
                stream.write("  {}: count={}\n".format(section_name, len(rows)))
                for point in rows:
                    stream.write(
                        "    line {} | point={} | cell={} | tran={} | values={}\n".format(
                            point["line_no"], point["point"], point["cell"],
                            point["transition"], point["values"]
                        )
                    )

            stream.write("\n[SELECTED ROWS]\n")
            for name in ("launch_begin", "endpoint_data", "capture_clock_raw"):
                selected = item["selected_rows"][name]
                stream.write("  {} | reason={}\n".format(name, selected["reason"]))
                stream.write("    {}\n".format(selected["row"] or "<NOT FOUND>"))
            source = item["selected_rows"].get("clock_source_latency")
            stream.write("  clock_source_latency\n")
            stream.write("    {}\n".format(source or "<NOT FOUND>"))

            stream.write("\n[CALCULATION]\n")
            calculation = item["calculation"]
            stream.write("  inputs = {}\n".format(calculation["inputs"]))
            stream.write("  tlaunch = {}\n".format(calculation["tlaunch"]))
            stream.write("  tdata_plus_tck2q = {}\n".format(
                calculation["tdata_plus_tck2q"]
            ))
            stream.write("  tcapture = {}\n".format(calculation["tcapture"]))
            stream.write("  warnings = {}\n".format(calculation["warnings"] or "<none>"))

            stream.write("\n[UNPARSED NUMERIC LINES]\n")
            if not item["unparsed_numeric_lines"]:
                stream.write("  <none>\n")
            for event in item["unparsed_numeric_lines"]:
                stream.write(
                    "  line {} | {} | values={} | unmatched={}\n".format(
                        event["line_no"], event["section"], event["values"],
                        event["unmatched_numbers"]
                    )
                )
                stream.write("      {}\n".format(event["raw"]))

            stream.write("\n[MISSING]\n")
            stream.write("  {}\n\n".format(item["missing"] or "<none>"))


def main():
    parser = argparse.ArgumentParser(
        description="Parse PrimeTime Point table and calculate basic timing values."
    )
    parser.add_argument("report", help="PrimeTime report (.rpt/.txt/.gz)")
    parser.add_argument("--unit", default="unknown", help="Metadata only; no conversion")
    parser.add_argument("--out-dir", default="pt_parse_out")
    parser.add_argument("--max-paths", type=int)
    args = parser.parse_args()

    if args.max_paths is not None and args.max_paths < 1:
        parser.error("--max-paths must be >= 1")

    report_path = os.path.abspath(args.report)
    out_dir = os.path.abspath(args.out_dir)

    try:
        text = read_report(report_path)
    except OSError as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 2

    blocks = split_paths(text, args.max_paths)
    if not blocks:
        print("ERROR: no path found. Check PATH_START_RE.", file=sys.stderr)
        return 2

    parsed = [parse_path(block, index + 1) for index, block in enumerate(blocks)]
    status_count = {
        name: sum(path["status"] == name for path in parsed)
        for name in ("OK", "WARN", "ERROR")
    }

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    json_path = os.path.join(out_dir, "paths_raw.json")
    log_path = os.path.join(out_dir, "parse_debug.log")

    output = {
        "schema": "pt_parser_step1_simple_v2",
        "source": report_path,
        "unit": args.unit,
        "note": (
            "Columns are mapped from the Point header. tcapture is intentionally "
            "not calculated in this version."
        ),
        "status_count": status_count,
        "paths": parsed,
    }

    with open(json_path, "w", encoding="utf-8") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    write_debug_log(log_path, parsed)

    print("Paths : {}".format(len(parsed)))
    print("Status: {}".format(status_count))
    print("JSON  : {}".format(json_path))
    print("Debug : {}".format(log_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
