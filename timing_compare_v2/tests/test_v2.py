"""Synthetic tests only. Does not require a licensed EDA tool or real reports."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import timing_v2 as cli
from numeric import number, rounded, read_json, write_json
from dataset import read_pt, normalize_pt


def pt_fixture(path, count=2):
    path.mkdir()
    meta = dict(run_id="synthetic", comparison_context="test", design_revision="test",
                scenario="unspecified", pba_mode="none", analysis_type="max", time_unit="ns", capacitance_unit="pf")
    paths = []
    for i in range(count):
        launch, end = "top/L%d" % i, "top/E%d" % i
        def point(name, arrival, direction, seq=False, ck=False, si=None, index=1):
            return dict(index=index, object_name=name, arrival_native_ns=number(arrival), direction=direction,
                        object_class="port" if name == "CLK" else "pin", transition="rise",
                        cell_name=name.rsplit("/", 1)[0], cell_is_sequential=seq, is_clock_pin=ck,
                        slew_ns=number(".04"), capacitance_pf=None, si_delta_native_ns=number(si))
        points = [point(launch + "/CK", "10", "in", True, True, ".02"),
                  point(launch + "/Q", "10.1", "out", True, index=2),
                  point("top/B%d/A" % i, "10.3", "in", si=".03", index=3),
                  point("top/B%d/Z" % i, "10.6", "out", index=4),
                  point(end + "/D", "11.2", "in", True, si=".06", index=5)]
        clocks = [{"segment": "launch", "points": [point("CLK", "9.7", "in"), point(launch + "/CK", "10", "in", True, True, ".02", index=2)]},
                  {"segment": "capture", "points": [point("CLK", "20", "in"), point(end + "/CK", "20.33", "in", True, True, ".01", index=2)]}]
        p = dict(meta, path_id="P%d" % i, path_group="reg2reg", startpoint=launch + "/CK", endpoint=end + "/D",
                 launch_clock="CLK", capture_clock="CLK", launch_edge="rise", capture_close_edge="rise",
                 launch_edge_ns=0, capture_close_edge_ns=2, launch_is_latch=False, capture_is_latch=False,
                 launch_is_propagated=True, capture_is_propagated=True, capture_clock_pin=end + "/CK",
                 launch_clock_sources=["CLK"], capture_clock_sources=["CLK"], data_points=points, clock_paths=clocks,
                 slack_ns=number("-.2") + number(".1") * i, arrival_ns=number("1.2"),
                 required_ns=number("1.0") + number(".1") * i, cppr_native_ns=number(".025"), uncertainty_native_ns=number(".08"))
        paths.append(p)
    write_json(path / "timing.json", dict(schema_version="1.0", metadata=meta, paths=paths))
    write_json(path / "manifest.json", dict(schema_version="1.0", complete=True, metadata=meta, path_count=count))
    return paths


def raw_candidate(pt, index=1, slack="-.05", factor="1"):
    scale = number(factor)
    def field(value, kind="text"):
        if value is None:
            return dict(status="unavailable", kind=kind, value="", property="synthetic", raw="")
        if kind in ("time", "cap"):
            value = number(value) * scale
        return dict(status="ok", kind=kind, value=str(value), property="synthetic", raw=str(value))
    names = dict(startpoint=pt["startpoint"].replace("/CK", "/Q"), endpoint=pt["endpoint"],
                 launch_clock="CLK", capture_clock="CLK", launch_edge="rise", capture_edge="rise", view="SS")
    fields = {k: field(v) for k, v in names.items()}
    for k, v in dict(slack_ns=slack, arrival_native_ns="1.2", required_native_ns=number("1.2") + number(slack),
                     launch_edge_ns="0", capture_edge_ns="2", cppr_native_ns=".025", uncertainty_native_ns=".08").items():
        fields[k] = field(v, "time")
    def point(p):
        f = {k: field(p.get(k), "time") for k in ("arrival_native_ns", "slew_ns", "si_delta_native_ns")}
        if p.get("si_delta_native_ns") is not None:
            f["si_delta_native_ns"] = field(".005", "time")
        f.update({k: field(p.get(k)) for k in ("object_class", "direction", "transition")})
        return dict(name=p["object_name"], index=p["index"], fields=f)
    return dict(candidate_index=index, fields=fields, points=[point(p) for p in pt["data_points"]],
                clock_paths={c["segment"]: [[point(p) for p in c["points"]]] for c in pt["clock_paths"]})


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pt = self.root / "pt"
        self.paths = pt_fixture(self.pt)
        self.job = self.root / "job"
        self.raw = self.root / "raw.jsonl"
        self.out = self.root / "result"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(args) or 0

    def prepare(self, *args):
        self.assertEqual(self.run_cli(["prepare", "--pt", str(self.pt), "--job", str(self.job)] + list(args)), 0)
        return read_json(self.job / "job.json")

    def records(self, job):
        cfg = {k: str(v) for k, v in job["config"].items()}
        records = [dict(record_type="header", schema_version="2.0", job_id=job["job_id"], tool="Innovus", config=cfg)]
        for index, target in enumerate(job["targets"]):
            record = dict(target, record_type="target", status="ok", message="", truncated=False,
                          candidates=[raw_candidate(self.paths[index], slack="-.05" if index == 0 else "-.30")])
            records.append(record)
        records.append(dict(record_type="footer", complete=True, target_count=len(job["targets"])))
        return records

    def compare(self, records, *args):
        self.raw.write_text("\n".join(cli.json_text(r) for r in records) + "\n", encoding="utf-8")
        return self.run_cli(["compare", "--job", str(self.job), "--innovus", str(self.raw), "--out", str(self.out)] + list(args))

    def result(self):
        return read_json(self.out / "comparison.json")

    def test_reverse_wns_preserves_golden_order(self):
        records = self.records(self.prepare())
        records[1], records[2] = records[2], records[1]  # Raw order can also be shuffled.
        self.assertEqual(self.compare(records), 0)
        rows = self.result()["rows"]
        self.assertEqual([r["target_id"] for r in rows], ["T0000001", "T0000002"])
        self.assertEqual([r["status"] for r in rows], ["matched", "matched"])
        self.assertEqual(rows[0]["metrics"]["slack_ns"]["delta_ns"], number(".15"))
        self.assertEqual(rows[1]["metrics"]["slack_ns"]["delta_ns"], number("-.20"))
        self.assertEqual((self.out / "golden_paths.csv").read_text().splitlines()[0], (self.out / "innovus_paths.csv").read_text().splitlines()[0])

    def test_missing_target_retains_slot(self):
        records = self.records(self.prepare())
        records[1].update(status="not_found", candidates=[])
        self.assertEqual(self.compare(records, "--fail-unmatched"), 2)
        rows = read_json(self.out / "innovus.json")["paths"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "not_found")
        self.assertIsNone(rows[0]["metrics"]["slack_ns"])
        self.assertEqual(rows[1]["target_id"], "T0000002")

    def test_positive_innovus_slack_is_compared(self):
        records = self.records(self.prepare())
        records[1]["candidates"] = [raw_candidate(self.paths[0], slack=".05")]
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["rows"][0]["metrics"]["slack_ns"]["delta_ns"], number(".25"))

    def test_name_map_matches_observed_pin_names(self):
        mapping = {"pins": {}, "clocks": {}}
        for path in self.paths:
            for point in path["data_points"]:
                mapping["pins"][point["object_name"]] = point["object_name"].replace("top/", "chip/")
        name_map = self.root / "names.json"
        write_json(name_map, mapping)
        records = self.records(self.prepare("--name-map", str(name_map)))
        for record in records[1:-1]:
            candidate = record["candidates"][0]
            for field in ("startpoint", "endpoint"):
                candidate["fields"][field]["value"] = candidate["fields"][field]["value"].replace("top/", "chip/")
            for point in candidate["points"]:
                point["name"] = point["name"].replace("top/", "chip/")
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["counts"], {"matched": 2})

    def test_ambiguous_and_truncated_are_not_worst_rank_matched(self):
        records = self.records(self.prepare())
        records[1]["candidates"].append(raw_candidate(self.paths[0], index=2))
        records[2]["truncated"] = True
        self.assertEqual(self.compare(records), 0)
        self.assertEqual([r["status"] for r in self.result()["rows"]], ["ambiguous", "candidate_limit"])

    def test_identity_checks_clock_edge_and_topology(self):
        records = self.records(self.prepare())
        records[1]["candidates"][0]["fields"]["capture_edge"]["value"] = "fall"
        records[2]["candidates"][0]["points"][2]["name"] = "different/A"
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["counts"], {"no_matching_candidate": 2})

    def test_si_is_signed_and_needs_semantic_contract(self):
        profile = self.root / "semantics.json"
        write_json(profile, dict(si_delta_contract="receiver_net_delta"))
        records = self.records(self.prepare("--semantics", str(profile)))
        self.assertEqual(self.compare(records), 0)
        metric = self.result()["rows"][0]["metrics"]["si_data_ns"]
        self.assertEqual(metric["delta_ns"], number("-.08"))
        self.assertEqual(metric["status"], "available")
        self.assertEqual(self.result()["rows"][0]["metrics"]["tck2q_ns"]["pt_ns"], number(".1"))

    def test_unverified_si_and_raw_reference_do_not_auto_compare(self):
        records = self.records(self.prepare())
        self.assertEqual(self.compare(records), 0)
        metrics = self.result()["rows"][0]["metrics"]
        self.assertEqual(metrics["si_data_ns"]["status"], "requires_semantic_mapping")
        self.assertEqual(metrics["required_native_ns"]["status"], "requires_reference_mapping")

    def test_units_ps_are_converted_once(self):
        records = self.records(self.prepare("--time-unit", "ps"))
        for i in range(2):
            records[i + 1]["candidates"] = [raw_candidate(self.paths[i], factor="1000")]
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["rows"][0]["metrics"]["slack_ns"]["delta_ns"], number(".15"))

    def test_float_tail_does_not_create_false_slack_error(self):
        records = self.records(self.prepare())
        c = records[1]["candidates"][0]
        c["fields"]["required_native_ns"]["value"] = "1.1500000000000001"
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["rows"][0]["slack_check_innovus"]["status"], "ok")

    def test_real_reference_error_is_not_fixed_by_clock_offset_guess(self):
        records = self.records(self.prepare())
        records[1]["candidates"][0]["fields"]["required_native_ns"]["value"] = "0.15"
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["rows"][0]["slack_check_innovus"]["status"], "native_reference_mismatch")

    def test_multiple_views_need_explicit_selection(self):
        records = self.records(self.prepare())
        records[2]["candidates"][0]["fields"]["view"]["value"] = "FF"
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["counts"], {"multiple_views_select_view": 2})

    def test_stale_job_and_incomplete_records_rejected(self):
        records = self.records(self.prepare())
        records[0]["job_id"] = "stale"
        self.assertEqual(self.compare(records), 1)
        self.assertFalse(self.out.exists())
        records = self.records(read_json(self.job / "job.json"))[:-1]
        self.assertEqual(self.compare(records), 1)

    def test_duplicate_golden_identity_is_explicit(self):
        source = read_json(self.pt / "timing.json")
        source["paths"][1] = copy.deepcopy(source["paths"][0])
        source["paths"][1]["path_id"] = "duplicate"
        write_json(self.pt / "timing.json", source)
        self.paths = source["paths"]
        records = self.records(self.prepare())
        self.assertEqual(self.compare(records), 0)
        self.assertEqual(self.result()["counts"], {"duplicate_golden": 2})

    def test_missing_si_is_null_not_zero(self):
        records = self.records(self.prepare())
        records[1]["candidates"][0]["points"][-1]["fields"]["si_delta_native_ns"]["status"] = "unavailable"
        self.assertEqual(self.compare(records), 0)
        row = read_json(self.out / "innovus.json")["paths"][0]
        self.assertIsNone(row["metrics"]["si_data_ns"])
        self.assertEqual(row["si_coverage"]["data"]["status"], "partial")

    def test_hold_slack_has_reversed_formula(self):
        path = copy.deepcopy(self.paths[0])
        path.update(analysis_type="min", slack_ns=number(".2"), capture_open_edge="rise", capture_open_edge_ns=1)
        row = normalize_pt(path, 1, number(".000001"), number(".000001"))
        self.assertEqual(row["slack_check"]["status"], "ok")
        self.assertEqual(row["metrics"]["phase_shift_ns"], number("1"))

    def test_quantization_and_exact_json_number(self):
        self.assertEqual(rounded("0.0000005", number(".000001")), number(".000001"))
        self.assertEqual(rounded("-0.0000005", number(".000001")), number("-.000001"))
        self.assertEqual(cli.json_text(dict(x=number("0.300000"))), '{"x":0.300000}')


class TclCollectorTests(unittest.TestCase):
    setUp = PipelineTests.setUp
    tearDown = PipelineTests.tearDown
    run_cli = PipelineTests.run_cli
    prepare = PipelineTests.prepare
    result = PipelineTests.result
    # Run this particular test in a real Tcl interpreter; EDA commands are mocked.
    def test_tcl_collector_to_python_compare(self):
        try:
            import tkinter
        except ImportError:
            self.skipTest("tkinter/Tcl unavailable; Python tests still run")
        t = tkinter.Tcl()
        t.call("source", str(ROOT / "innovus_collect.tcl"))
        t.eval('''
namespace eval mock {variable db {}; variable paths {}; variable objects {}; variable queries {}}
proc get_property {object property} {return [dict get $::mock::db $object $property]}
proc get_object_name {object} {get_property $object hierarchical_name}
proc sizeof_collection {objects} {llength $objects}
proc foreach_in_collection {var objects body} {uplevel 1 [list foreach $var $objects $body]}
proc get_pins {quiet pattern} {
    set result {}
    dict for {name handle} $::mock::objects {
        if {[string match $pattern $name]} {lappend result $handle}
    }
    return $result
}
proc get_ports {args} {return {}}
proc report_timing {args} {
    lappend ::mock::queries $args
    if {[lsearch -exact $args -collection] < 0} {error "Expected -collection"}
    if {[lsearch -exact $args -max_slack] >= 0} {error "Unexpected slack filter"}
    set handle [lindex $args [expr {[lsearch -exact $args -from] + 1}]]
    return [dict get $::mock::paths $handle]
}
''')
        self.prepare()
        path_map = dict(startpoint="launching_point", endpoint="capturing_point", launch_clock="launching_clock",
                        capture_clock="capturing_clock", launch_edge="launching_clock_open_edge_type", capture_edge="capturing_clock_close_edge_type",
                        launch_edge_ns="launching_clock_open_edge_time", capture_edge_ns="capturing_clock_close_edge_time", view="view_name",
                        slack_ns="slack", arrival_native_ns="arrival_time", required_native_ns="required_time", cppr_native_ns="cppr_adjustment", uncertainty_native_ns="uncertainty")
        point_map = dict(arrival_native_ns="arrival", transition="transition_type", slew_ns="slew", si_delta_native_ns="delta_delay", capacitance_pf="load")
        counter = [0]
        def prop(obj, key, value):
            t.call("dict", "set", "::mock::db", obj, key, value)
        def add_points(points):
            handles = []
            for point in points:
                counter[0] += 1
                obj, handle = "obj%d" % counter[0], "point%d" % counter[0]
                prop(obj, "hierarchical_name", point["name"])
                prop(obj, "object_type", point["fields"]["object_class"]["value"])
                prop(obj, "direction", point["fields"]["direction"]["value"])
                t.call("dict", "set", "::mock::objects", point["name"], obj)
                prop(handle, "pin", obj)
                for field, native in point_map.items():
                    read = point["fields"].get(field, {})
                    if read.get("status") == "ok":
                        prop(handle, native, read["value"])
                handles.append(handle)
            return handles
        for i, path in enumerate(self.paths):
            candidate = raw_candidate(path)
            handle = "path%d" % i
            for field, native in path_map.items():
                prop(handle, native, candidate["fields"][field]["value"])
            prop(handle, "timing_points", tuple(add_points(candidate["points"])))
            for role in ("launch", "capture"):
                c = "%s_%d" % (role, i)
                prop(c, "timing_points", tuple(add_points(candidate["clock_paths"][role][0])))
                prop(handle, "launching_clock_path" if role == "launch" else "capturing_clock_path", (c,))
            start = t.call("dict", "get", t.getvar("::mock::objects"), path["startpoint"])
            t.call("dict", "set", "::mock::paths", start, (handle,))
        t.call("iv2::run", str(self.job / "targets.tcl"), str(self.raw))
        self.assertEqual(self.run_cli(["compare", "--job", str(self.job), "--innovus", str(self.raw), "--out", str(self.out)]), 0)
        self.assertEqual(self.result()["counts"], {"matched": 2})
        self.assertEqual(int(t.call("llength", t.getvar("::mock::queries"))), 2)
        hostile = 'top/reg[3]/Q $literal; "\\ \n'
        self.assertEqual(t.eval("set escaped " + cli.tcl_word(hostile)), hostile)
        self.assertEqual(json.loads(t.call("iv2::js", hostile)), hostile)
        prop("busobj", "hierarchical_name", "top/reg[3]/D")
        t.call("dict", "set", "::mock::objects", "top/reg[3]/D", "busobj")
        self.assertEqual(t.call("iv2::exact_object", "top/reg[3]/D"), "busobj")


if __name__ == "__main__":
    unittest.main()
