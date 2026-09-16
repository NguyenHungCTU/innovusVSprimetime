#!/usr/bin/env python3
"""
STEP 1 - Doc PrimeTime report va lay RAW data.

Khong tinh launch/capture/data/phase.
Khong doi dau CPPR/uncertainty/setup/hold.
Khong compare voi Innovus.

Chay:
  python3 pt_parser_step1_simple.py pt_setup.rpt \
      --unit ns --out-dir pt_parse_out --max-paths 10

Output:
  pt_parse_out/paths_raw.json
  pt_parse_out/parse_debug.log

Neu report format thay doi, sua SECTION 1 truoc.
Python 3.6+, khong can pip/sudo.
"""

from __future__ import print_function

import argparse
import gzip
import json
import os
import re
import sys


# =============================================================================
# SECTION 1 - FORMAT CONFIG: NOI BAN SE SUA KHI REPORT THAY DOI
# =============================================================================

NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_./])(" + NUM + r")(?![A-Za-z0-9_./])"
)

# Mot path bat dau / ket thuc o dau?
PATH_START_RE = re.compile(r"^\s*Startpoint\s*:", re.I)
PATH_END_RE = re.compile(r"^\s*slack(?:\s*\([^)]*\))?\s+", re.I)

# Header dau path. Moi pattern phai co group ten la (?P<value>...).
HEADER_PATTERNS = {
    "startpoint": re.compile(r"^\s*Startpoint\s*:\s*(?P<value>\S+)", re.I),
    "endpoint": re.compile(r"^\s*Endpoint\s*:\s*(?P<value>\S+)", re.I),
    "path_group": re.compile(r"^\s*Path Groups?\s*:\s*(?P<value>.+?)\s*$", re.I),
    "path_type": re.compile(r"^\s*Path Type\s*:\s*(?P<value>max|min)\b", re.I),
    "scenario": re.compile(r"^\s*Scenario\s*:\s*(?P<value>\S+)", re.I),
}

# Label can lay. Tat ca occurrence duoc giu lai; khong overwrite.
TERM_PATTERNS = [
    ("data_arrival", re.compile(r"^\s*data arrival time\b", re.I)),
    ("data_required", re.compile(r"^\s*data required time\b", re.I)),
    ("slack", re.compile(r"^\s*slack(?:\s*\([^)]*\))?\b", re.I)),
    ("cppr", re.compile(r"^\s*clock reconvergence pessimism\b", re.I)),
    ("uncertainty", re.compile(r"^\s*(?:inter[- ]clock |clock )uncertainty\b", re.I)),
    ("clock_jitter", re.compile(r"^\s*clock jitter\b", re.I)),
    ("setup", re.compile(r"^\s*library setup time\b", re.I)),
    ("hold", re.compile(r"^\s*library hold time\b", re.I)),
    ("clock_source_latency", re.compile(r"^\s*clock source latency\b", re.I)),
    ("clock_network_delay", re.compile(r"^\s*clock network delay\b", re.I)),
    ("input_external_delay", re.compile(r"^\s*input external delay\b", re.I)),
    ("output_external_delay", re.compile(r"^\s*output external delay\b", re.I)),
    ("max_delay", re.compile(r"^\s*max_delay\b", re.I)),
    ("min_delay", re.compile(r"^\s*min_delay\b", re.I)),
]

# Vi du: clock CLK (rise edge) 0.000 0.000
CLOCK_EDGE_RE = re.compile(
    r"^\s*clock\s+(?P<clock>.+?)\s+"
    r"\((?P<edge>rise|fall)\s+edge\)\s*(?P<tail>.*?)\s*$",
    re.I,
)

# Header cua point table.
POINT_HEADER_RE = re.compile(r"^\s*Point\b.*\bPath\b", re.I)

# Point row co hoac khong co cell trong ngoac.
# Pattern khong cell yeu cau point chua '/', tranh match dong clock network delay.
POINT_PATTERNS = [
    re.compile(
        r"^\s*(?P<point>\S+)\s+\((?P<cell>[^)]*)\)\s*(?P<tail>.*?)\s*$"
    ),
    re.compile(
        r"^\s*(?P<point>\S+/\S+)\s+(?P<tail>.*?)\s*$"
    ),
]

TRANSITION_RE = re.compile(r"(?:^|\s)([rf])(?=\s|$)", re.I)

REQUIRED_HEADERS = ("startpoint", "endpoint", "path_group", "path_type")
REQUIRED_TERMS = ("data_arrival", "data_required", "slack")


# =============================================================================
# SECTION 2 - DOC FILE VA TACH TUNG PATH
# =============================================================================

def read_report(path):
    opener = gzip.open if path.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")


def get_numbers(text):
    """Lay numeric token doc lap; khong lay so trong ten U123/A."""
    return [float(m.group(1)) for m in NUMBER_RE.finditer(text)]


def split_paths(text, max_paths=None):
    """Tach report tu Startpoint den slack. Giu line number cua report goc."""
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
# SECTION 3 - HAM EXTRACT MOT DONG
# =============================================================================

def numeric_data(tail):
    """
    Giu tat ca so raw.
    Hai field *_guess chi de debug format, CHUA phai timing value da xac nhan.
    """
    values = get_numbers(tail)
    return {
        "numbers": values,
        "incr_guess": values[-2] if len(values) >= 2 else None,
        "path_guess": values[-1] if values else None,
    }


def match_term(line):
    for name, pattern in TERM_PATTERNS:
        match = pattern.match(line)
        if match:
            return name, match
    return None, None


def parse_point(line):
    for pattern in POINT_PATTERNS:
        match = pattern.match(line)
        if not match:
            continue

        groups = match.groupdict()
        tail = groups.get("tail", "")
        data = numeric_data(tail)
        if not data["numbers"]:
            continue

        transitions = TRANSITION_RE.findall(tail)
        data.update({
            "point": groups.get("point"),
            "cell": groups.get("cell"),
            "transition": transitions[-1].lower() if transitions else None,
        })
        return data
    return None


# =============================================================================
# SECTION 4 - PARSE MOT PATH
# =============================================================================

def parse_path(block, path_id):
    result = {
        "path_id": path_id,
        "start_line": block["start_line"],
        "headers": {},
        "terms": {},
        "clock_edges": [],
        "points": {"launch_data": [], "capture_required": []},
        "unparsed_numeric_lines": [],
        "missing": [],
    }

    # 4.1 Lay header.
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

    # 4.2 State machine:
    # header -> launch_data -> capture_required -> final_summary
    section = "header"
    first_arrival_seen = False
    first_required_seen = False

    for line_no, line in block["lines"]:
        stripped = line.strip()

        if line_no in header_lines or not stripped or re.match(r"^[-=*]+$", stripped):
            continue

        if POINT_HEADER_RE.match(line):
            section = "launch_data"
            continue

        # Clock edge row.
        match = CLOCK_EDGE_RE.match(line)
        if match:
            if section == "header":
                section = "launch_data"  # fallback neu Point header bi wrap
            event = numeric_data(match.group("tail"))
            event.update({
                "clock": match.group("clock").strip(),
                "edge": match.group("edge").lower(),
                "section": section,
                "line_no": line_no,
                "raw": line,
            })
            result["clock_edges"].append(event)
            continue

        # Known timing term.
        term_name, term_match = match_term(line)
        if term_match:
            event = numeric_data(line[term_match.end():])
            event.update({"section": section, "line_no": line_no, "raw": line})
            result["terms"].setdefault(term_name, []).append(event)

            # Chuyen section SAU KHI luu dong marker.
            if term_name == "data_arrival" and not first_arrival_seen:
                first_arrival_seen = True
                section = "capture_required"
            elif term_name == "data_required" and not first_required_seen:
                first_required_seen = True
                section = "final_summary"
            continue

        # Pin/port row trong timing table.
        if section in ("launch_data", "capture_required"):
            point = parse_point(line)
            if point:
                point.update({"line_no": line_no, "raw": line})
                result["points"][section].append(point)
                continue

        # Dong co so nhung chua match: day la cho de debug/sua format.
        numbers = get_numbers(line)
        if numbers:
            result["unparsed_numeric_lines"].append({
                "section": section,
                "line_no": line_no,
                "numbers": numbers,
                "raw": line,
            })

    # 4.3 Chi check field co duoc extract hay khong; chua check timing equation.
    for name in REQUIRED_HEADERS:
        if name not in result["headers"]:
            result["missing"].append("header:" + name)
    for name in REQUIRED_TERMS:
        if not result["terms"].get(name):
            result["missing"].append("term:" + name)
    if len(result["clock_edges"]) < 2:
        result["missing"].append("clock_edges:<2")
    if not result["points"]["launch_data"]:
        result["missing"].append("points:launch_data")
    if not result["points"]["capture_required"]:
        result["missing"].append("points:capture_required")

    result["status"] = (
        "ERROR" if result["missing"]
        else "WARN" if result["unparsed_numeric_lines"]
        else "OK"
    )
    return result


# =============================================================================
# SECTION 5 - OUTPUT JSON + DEBUG LOG
# =============================================================================

def write_debug_log(path, parsed_paths):
    with open(path, "w", encoding="utf-8") as f:
        for item in parsed_paths:
            f.write("=" * 90 + "\n")
            f.write("PATH {} | start line {} | status={}\n".format(
                item["path_id"], item["start_line"], item["status"]
            ))

            f.write("\n[HEADERS]\n")
            for name in HEADER_PATTERNS:
                value = item["headers"].get(name)
                if value:
                    f.write("  {} = {}  (line {})\n".format(
                        name, value["value"], value["line_no"]
                    ))
                else:
                    f.write("  {} = <NOT FOUND>\n".format(name))

            f.write("\n[CLOCK EDGES]\n")
            for event in item["clock_edges"]:
                f.write("  line {} | {} | {} {} | numbers={}\n".format(
                    event["line_no"], event["section"], event["clock"],
                    event["edge"], event["numbers"]
                ))

            f.write("\n[TERMS]\n")
            for name, unused_pattern in TERM_PATTERNS:
                for event in item["terms"].get(name, []):
                    f.write(
                        "  {:22s} line {} | {:18s} | numbers={} | "
                        "incr_guess={} | path_guess={}\n".format(
                            name, event["line_no"], event["section"],
                            event["numbers"], event["incr_guess"], event["path_guess"]
                        )
                    )
                    f.write("      {}\n".format(event["raw"]))

            f.write("\n[POINT ROWS]\n")
            for section in ("launch_data", "capture_required"):
                f.write("  {}: count={}\n".format(
                    section, len(item["points"][section])
                ))
                for point in item["points"][section]:
                    f.write(
                        "    line {} | point={} | cell={} | tran={} | numbers={} | "
                        "incr_guess={} | path_guess={}\n".format(
                            point["line_no"], point["point"], point["cell"],
                            point["transition"], point["numbers"],
                            point["incr_guess"], point["path_guess"]
                        )
                    )

            f.write("\n[UNPARSED NUMERIC LINES]\n")
            if not item["unparsed_numeric_lines"]:
                f.write("  <none>\n")
            for event in item["unparsed_numeric_lines"]:
                f.write("  line {} | {} | numbers={}\n".format(
                    event["line_no"], event["section"], event["numbers"]
                ))
                f.write("      {}\n".format(event["raw"]))

            f.write("\n[MISSING]\n")
            f.write("  {}\n\n".format(item["missing"] or "<none>"))


def main():
    parser = argparse.ArgumentParser(
        description="STEP 1: extract raw values from PrimeTime report_timing."
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
        "schema": "pt_parser_step1_simple_v1",
        "source": report_path,
        "unit": args.unit,
        "note": "Raw extraction only; *_guess fields are not validated timing values.",
        "status_count": status_count,
        "paths": parsed,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")
    write_debug_log(log_path, parsed)

    print("Paths : {}".format(len(parsed)))
    print("Status: {}".format(status_count))
    print("JSON  : {}".format(json_path))
    print("Debug : {}".format(log_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
