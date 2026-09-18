"""Run: python3 -m unittest discover -s tests -v

Uses tkinter.Tcl() headlessly; no Tk window or display is created.
The optional Tcl interpreter dependency is only for tests, not timing_data.py.
"""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import tkinter
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import timing_data as td


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.t = tkinter.Tcl()
        self.t.call("source", str(ROOT / "pt_export.tcl"))
        self.t.call("source", str(ROOT / "tests" / "mock_pt.tcl"))
        self.t.call("mock::setup")
        self.t.call("set", "cfg", self.t.call("mock::config", str(self.root / "run")))

    def tearDown(self):
        self.tmp.cleanup()

    def run_export(self, edit="", name="run"):
        self.t.call("dict", "set", "cfg", "output_dir", str(self.root / name))
        if edit:
            self.t.eval(edit)
        self.t.eval("ptx::run $cfg")
        return td.load_dataset(self.root / name)

    def test_end_to_end_numeric_semantics(self):
        data = self.run_export()
        p = data["paths"][0]
        expected = {"tlaunch_ns": .300, "tcapture_ns": .330, "tck2q_ns": .095,
                    "tdata_ns": 2.172, "tdata_plus_ck2q_ns": 2.267,
                    "phase_shift_ns": 2., "slack_ns": -.215,
                    "si_data_complete_sum_ns": .09, "si_launch_complete_sum_ns": .06,
                    "si_capture_complete_sum_ns": .02}
        for key, value in expected.items():
            self.assertAlmostEqual(p[key], value, places=10, msg=key)
        self.assertEqual(p["data_points"][0]["arrival_native_ns"], 0.)
        self.assertEqual(p["slack_check_status"], "ok")
        self.assertEqual(p["calculations"]["launch"]["root_index"], 1)
        self.assertEqual(p["calculations"]["data"]["ck_index"], 1)
        # No double counting of launch CK SI into data SI.
        self.assertEqual(p["si_data_observed_count"], 2)

    def test_missing_attribute_is_null_not_zero(self):
        p = self.run_export("dict unset ::mock::objects p2 annotated_delay_delta")["paths"][0]
        self.assertEqual(p["si_data_status"], "partial")
        self.assertIsNone(p["si_data_complete_sum_ns"])
        self.assertAlmostEqual(p["si_data_observed_sum_ns"], .06)
        self.assertEqual(p["si_data_missing_count"], 1)
        self.assertIsNone(p["data_points"][2]["si_delta_native_ns"])
        self.assertEqual(p["data_points"][2]["attributes"]["si_delta_native_ns"]["status"], "unavailable")
        self.assertIsNone(p["data_points"][1]["capacitance_pf"])

    def test_real_zero_is_preserved_and_negative_si_not_abs(self):
        p = self.run_export("dict set ::mock::objects p2 annotated_delay_delta 0; dict set ::mock::objects p4 annotated_delay_delta -0.06")["paths"][0]
        self.assertEqual(p["si_data_status"], "complete")
        self.assertAlmostEqual(p["si_data_complete_sum_ns"], -.06)
        self.assertEqual(p["data_points"][2]["si_delta_native_ns"], 0.)

    def test_hold_slack_sign(self):
        p = self.run_export("""
            dict set cfg delay_type min
            dict set ::mock::objects path0 path_type min
            dict set ::mock::objects path0 arrival 0.200
            dict set ::mock::objects path0 required 0.240
            dict set ::mock::objects path0 slack -0.040
            dict set ::mock::objects path0 endpoint_clock_open_edge_value 0
            dict set ::mock::objects path0 endpoint_clock_close_edge_value 0
        """)["paths"][0]
        self.assertAlmostEqual(p["slack_recomputed_ns"], -.040)
        self.assertEqual(p["phase_shift_ns"], 0)

    def test_explicit_ps_conversion_and_query_cutoff(self):
        data = self.run_export("""
            dict set cfg input_time_unit ps
            dict set cfg slack_lesser_than_ns -0.2
            set time_attrs {slack arrival required transition annotated_delay_delta
                startpoint_clock_latency endpoint_clock_latency
                startpoint_clock_open_edge_value endpoint_clock_open_edge_value
                endpoint_clock_close_edge_value common_path_pessimism
                clock_uncertainty endpoint_setup_time_value}
            dict for {id attrs} $::mock::objects {
                foreach attr $time_attrs {
                    if {[dict exists $attrs $attr]} {
                        dict set ::mock::objects $id $attr [expr {[dict get $attrs $attr] * 1000.0}]
                    }
                }
            }
        """)
        self.assertAlmostEqual(data["paths"][0]["tdata_ns"], 2.172)
        self.assertEqual(float(self.t.eval("dict get [lindex $::mock::queries 0] -slack_lesser_than")), -200.)

    def test_csv_json_escaping_and_round_trip(self):
        special = 'top/a[3],"b"\\c$foo;\n日本語\t🚀'
        self.t.call("dict", "set", "::mock::objects", "Q", "full_name", special)
        data = self.run_export()
        self.assertEqual(data["paths"][0]["data_points"][1]["object_name"], special)
        (self.root / "run" / "timing.json").unlink()
        csv_data = td.load_dataset(self.root / "run")
        self.assertEqual(csv_data["paths"][0]["data_points"][1]["object_name"], special)
        result = td.compare_datasets(data, csv_data)
        self.assertEqual(result["counts"], {"matched": 1})
        self.assertTrue(all(v["delta_ns"] in (None, 0) for v in result["rows"][0]["metrics"].values()))

    def test_csv_only_and_json_only(self):
        csv_data = self.run_export("dict set cfg formats {csv}", "csv")
        json_data = self.run_export("dict set cfg formats {json}", "json")
        self.assertEqual(len(csv_data["paths"]), 1)
        self.assertFalse((self.root / "csv" / "timing.json").exists())
        self.assertFalse((self.root / "json" / "paths.csv").exists())
        self.assertEqual(td.compare_datasets(csv_data, json_data)["counts"], {"matched": 1})

    def test_group_dedup_limit_and_nworst(self):
        data = self.run_export("""
            dict set cfg path_groups {reg* *}
            dict set cfg max_paths_per_group 2
            dict set cfg nworst 2
            mock::object path1 [dict get $::mock::objects path0]
            mock::object path2 [dict get $::mock::objects path0]
            mock::object path3 [dict replace [dict get $::mock::objects path0] path_group other]
            mock::object group1 {full_name other}
            set ::mock::paths {path0 path1 path2 path3}
            set ::mock::groups {group0 group1}
        """)
        self.assertEqual(len(data["paths"]), 3)
        self.assertEqual(int(self.t.eval("llength $::mock::queries")), 2)
        self.assertEqual(td.compare_datasets(data, data)["counts"], {"matched": 1, "ambiguous": 1})

    def test_empty_selection_is_valid(self):
        data = self.run_export("dict set cfg slack_lesser_than_ns -1.0")
        self.assertEqual(data["paths"], [])
        self.assertTrue(data["manifest"]["complete"])

    def test_bad_group_and_config_fail_before_writing(self):
        with self.assertRaises(tkinter.TclError):
            self.run_export("dict set cfg path_groups {does_not_exist}")
        self.assertFalse((self.root / "run").exists())
        with self.assertRaises(tkinter.TclError):
            self.run_export("dict set cfg path_groups {*}; dict set cfg input_time_unit {}")

    def test_existing_output_is_not_overwritten(self):
        self.run_export()
        before = (self.root / "run" / "timing.json").read_bytes()
        with self.assertRaises(tkinter.TclError):
            self.run_export()
        self.assertEqual((self.root / "run" / "timing.json").read_bytes(), before)

    def test_slack_mismatch_retains_partial_only(self):
        with self.assertRaises(tkinter.TclError):
            self.run_export("dict set ::mock::objects path0 required 2.0")
        self.assertFalse((self.root / "run").exists())
        partials = list(self.root.glob("run.partial-*"))
        self.assertEqual(len(partials), 1)
        self.assertTrue((partials[0] / "ERROR.txt").is_file())
        self.assertFalse((partials[0] / "manifest.json").exists())
        p = self.run_export("dict set cfg fail_on_slack_mismatch 0", "diagnostic")["paths"][0]
        self.assertEqual(p["slack_check_status"], "mismatch")

    def test_ambiguous_clock_paths_are_not_summed(self):
        p = self.run_export("dict set ::mock::objects path0 launch_clock_paths [mock::collection {lpath lpath}]")["paths"][0]
        self.assertIsNone(p["tlaunch_ns"])
        self.assertEqual(p["launch_network_status"], "ambiguous_clock_paths")
        self.assertEqual(len(p["clock_paths"]), 3)

    def test_missing_clock_api_and_ideal_clock(self):
        p = self.run_export("dict unset ::mock::objects path0 launch_clock_paths; dict set ::mock::objects path0 endpoint_clock_is_propagated false")["paths"][0]
        self.assertIsNone(p["tlaunch_ns"])
        self.assertIsNone(p["tcapture_ns"])
        self.assertEqual(p["capture_network_status"], "ideal_clock")
        self.assertEqual(p["launch_clock_paths_status"], "unavailable")

    def test_generated_clock_source_excludes_master_segment(self):
        p = self.run_export("dict set ::mock::objects clock sources [mock::collection {BZ}]")["paths"][0]
        self.assertAlmostEqual(p["tlaunch_ns"], .1)
        self.assertEqual(p["calculations"]["launch"]["root"], "top/u_clkbuf/Z")

    def test_latch_decomposition_not_fabricated(self):
        p = self.run_export("dict set ::mock::objects path0 startpoint_is_level_sensitive true")["paths"][0]
        self.assertIsNone(p["tck2q_ns"])
        self.assertIsNone(p["phase_shift_ns"])
        self.assertEqual(p["data_status"], "latch_or_unknown_launch_type")

    def test_q_only_does_not_claim_ck2q(self):
        p = self.run_export("""
            dict set ::mock::objects path0 startpoint [mock::collection {Q}]
            dict set ::mock::objects path0 points [mock::collection {p1 p2 p3 p4}]
        """)["paths"][0]
        self.assertAlmostEqual(p["tdata_ns"], 2.172)
        self.assertIsNone(p["tdata_plus_ck2q_ns"])
        self.assertIsNone(p["tck2q_ns"])

    def test_nonfinite_optional_fields_become_null(self):
        p = self.run_export("dict set ::mock::objects p2 transition NaN; dict set ::mock::objects path0 common_path_pessimism Inf")["paths"][0]
        self.assertIsNone(p["cppr_native_ns"])
        self.assertIsNone(p["data_points"][2]["slew_ns"])
        self.assertEqual(p["attributes"]["cppr_native_ns"]["status"], "invalid")

    def test_consumer_rejects_incomplete_and_wrong_context(self):
        data = self.run_export()
        other = copy.deepcopy(data)
        other["metadata"]["comparison_context"] = "different_corner"
        with self.assertRaises(ValueError):
            td.compare_datasets(data, other)
        manifest_file = self.root / "run" / "manifest.json"
        manifest = td.read_json(manifest_file)
        manifest["complete"] = False
        manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            td.load_dataset(self.root / "run")

    def test_compare_topology_and_missing_identity(self):
        data = self.run_export()
        other = copy.deepcopy(data)
        other["paths"][0]["data_points"][2]["object_name"] = "different_cell/A"
        self.assertEqual(td.compare_datasets(data, other)["counts"], {"missing_candidate": 1, "missing_reference": 1})
        row = td.compare_datasets(data, other, "endpoints")["rows"][0]
        self.assertEqual(row["status"], "matched")
        self.assertFalse(row["topology_equal"])
        other["paths"][0]["startpoint_transition"] = None
        self.assertIn("missing_identity", td.compare_datasets(data, other)["counts"])

    def test_extra_field_is_exported_without_writer_changes(self):
        data = self.run_export("""
            dict set ::ptx::point_fields voltage_v {number voltage}
            dict set ::mock::objects p2 voltage 0.72
        """)
        self.assertEqual(data["paths"][0]["data_points"][2]["voltage_v"], .72)
        (self.root / "run" / "timing.json").unlink()
        self.assertEqual(td.load_dataset(self.root / "run")["paths"][0]["data_points"][2]["voltage_v"], .72)

    def test_cross_tool_native_signs_are_not_assumed_equivalent(self):
        data = self.run_export()
        other = copy.deepcopy(data)
        other["metadata"]["tool"] = "Innovus"
        metrics = td.compare_datasets(data, other)["rows"][0]["metrics"]
        self.assertEqual(metrics["cppr_native_ns"]["status"], "requires_semantic_mapping")
        self.assertIsNone(metrics["cppr_native_ns"]["delta_ns"])
        self.assertEqual(metrics["slack_ns"]["delta_ns"], 0.)

    def test_edge_identity_ignores_float_representation_noise(self):
        data = self.run_export()
        other = copy.deepcopy(data)
        other["paths"][0]["capture_open_edge_ns"] += 1e-14
        self.assertEqual(td.compare_datasets(data, other)["counts"], {"matched": 1})


if __name__ == "__main__":
    unittest.main()
