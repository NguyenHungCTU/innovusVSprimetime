# EDIT THIS FILE when the installed PrimeTime attribute API differs.
# Format: output_field {type native_attribute}
# Types: time -> ns; cap -> pF; number; bool; text; name (one object or string).
# Optional attributes are probed, never silently replaced with zero.
# Check: man timing_path_attributes / man timing_point_attributes in YOUR release.
namespace eval ::ptx {
    variable path_fields [dict create \
        startpoint {name startpoint} \
        endpoint {name endpoint} \
        path_type_native {text path_type} \
        check_type_native {text check_type} \
        slack_ns {time slack} \
        arrival_ns {time arrival} \
        required_ns {time required} \
        launch_clock {name startpoint_clock} \
        capture_clock {name endpoint_clock} \
        capture_clock_pin {name endpoint_clock_pin} \
        launch_clock_latency_native_ns {time startpoint_clock_latency} \
        capture_clock_latency_native_ns {time endpoint_clock_latency} \
        launch_edge_ns {time startpoint_clock_open_edge_value} \
        launch_edge {text startpoint_clock_open_edge_type} \
        capture_open_edge_ns {time endpoint_clock_open_edge_value} \
        capture_open_edge {text endpoint_clock_open_edge_type} \
        capture_close_edge_ns {time endpoint_clock_close_edge_value} \
        capture_close_edge {text endpoint_clock_close_edge_type} \
        launch_is_latch {bool startpoint_is_level_sensitive} \
        capture_is_latch {bool endpoint_is_level_sensitive} \
        launch_is_propagated {bool startpoint_clock_is_propagated} \
        capture_is_propagated {bool endpoint_clock_is_propagated} \
        cppr_native_ns {time common_path_pessimism} \
        uncertainty_native_ns {time clock_uncertainty} \
        setup_native_ns {time endpoint_setup_time_value} \
        hold_native_ns {time endpoint_hold_time_value} \
        recovery_native_ns {time endpoint_recovery_time_value} \
        removal_native_ns {time endpoint_removal_time_value} \
        input_delay_native_ns {time startpoint_input_delay_value} \
        output_delay_native_ns {time endpoint_output_delay_value} \
        borrowed_native_ns {time time_borrowed_from_endpoint} \
        lent_native_ns {time time_lent_to_startpoint}]

    variable point_fields [dict create \
        arrival_native_ns {time arrival} \
        transition {text rise_fall} \
        slew_ns {time transition} \
        capacitance_pf {cap capacitance} \
        fanout {number fanout} \
        derate_native {number derate} \
        si_delta_native_ns {time annotated_delay_delta}]

    # Some optional point fields above are release dependent. Unsupported fields
    # remain null. Do NOT move to pin.max_* attributes: those are not path-specific.
    variable object_fields [dict create \
        object_class {text object_class} \
        direction {text direction} \
        is_clock_pin {bool is_clock_pin}]

    # The collector uses these separately because their values are collections.
    variable collection_attributes [dict create \
        data_points points \
        launch_clock_paths launch_clock_paths \
        capture_clock_paths capture_clock_paths \
        clock_path_points points \
        launch_clock startpoint_clock \
        capture_clock endpoint_clock \
        clock_sources sources]

    variable app_variables {
        sh_product_version si_enable_analysis
        timing_remove_clock_reconvergence_pessimism
        pba_recalculate_full_path si_xtalk_analysis_effort_level
        si_xtalk_delay_analysis_mode si_xtalk_composite_aggr_mode
        si_filter_per_aggr_noise_peak_ratio si_filter_accum_aggr_noise_peak_ratio
    }
}

