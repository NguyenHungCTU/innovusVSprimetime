# One configuration dict per run. No timing settings are modified by the exporter.
proc ::ptx::default_config {} {
    return [dict create \
        output_dir ./pt_export_run \
        run_id pt_run_001 \
        comparison_context CHANGE_ME \
        scenario CHANGE_ME \
        design_revision CHANGE_ME \
        path_groups {*} \
        max_paths_per_group 100 \
        nworst 1 \
        delay_type max \
        slack_lesser_than_ns 0.0 \
        pba_mode none \
        input_time_unit {} \
        input_capacitance_unit {} \
        formats {json csv} \
        include_clock_paths 1 \
        slack_tolerance_ns 0.000001 \
        fail_on_slack_mismatch 1 \
        progress_every 100 \
        session_kind single \
        notes {}]
}
