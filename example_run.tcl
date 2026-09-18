# Run AFTER restore_session/read design, constraints, parasitics and update_timing.
# Example: pt_shell> source /absolute/path/pt_collection_v1/example_run.tcl
set ptx_dir [file dirname [file normalize [info script]]]
source [file join $ptx_dir pt_export.tcl]

set cfg [ptx::default_config]
dict set cfg output_dir ./pt_ss_setup_001
dict set cfg run_id pt_ss_setup_001
dict set cfg comparison_context revA_func_ss_0p72v_125c_rcworst
dict set cfg scenario FUNC_SS_RCWORST
dict set cfg design_revision revA
dict set cfg path_groups {reg2reg} ;# Tcl glob patterns; {*} selects all groups
dict set cfg max_paths_per_group 100
dict set cfg nworst 1
dict set cfg delay_type max       ;# max or min; use separate output runs
dict set cfg slack_lesser_than_ns 0.0 ;# {} = no slack filter
dict set cfg pba_mode none        ;# none / path / exhaustive; do not mix in comparison
dict set cfg input_time_unit ns   ;# Confirm using report_units in your session!
dict set cfg input_capacitance_unit pf
dict set cfg formats {json csv}

ptx::run $cfg

