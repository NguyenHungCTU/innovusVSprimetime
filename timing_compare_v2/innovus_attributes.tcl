# EDIT HERE for the get_property API of your installed Innovus/Tempus release.
# Each entry is: canonical_name {kind native_property}. No text-report parsing.
# Unsupported properties remain unavailable and are recorded in the raw JSONL.
namespace eval ::iv2 {
    variable path_fields [dict create \
        startpoint {name launching_point} \
        endpoint {name capturing_point} \
        launch_clock {name launching_clock} \
        capture_clock {name capturing_clock} \
        launch_edge {text launching_clock_open_edge_type} \
        capture_edge {text capturing_clock_close_edge_type} \
        capture_open_edge {text capturing_clock_open_edge_type} \
        launch_edge_ns {time launching_clock_open_edge_time} \
        capture_edge_ns {time capturing_clock_close_edge_time} \
        capture_open_edge_ns {time capturing_clock_open_edge_time} \
        view {text view_name} \
        slack_ns {time slack} \
        arrival_native_ns {time arrival_time} \
        required_native_ns {time required_time} \
        launch_latency_native_ns {time launching_clock_latency} \
        capture_latency_native_ns {time capturing_clock_latency} \
        cppr_native_ns {time cppr_adjustment} \
        uncertainty_native_ns {time uncertainty} \
        setup_native_ns {time setup} \
        hold_native_ns {time hold}]

    # arrival / transition_type / pin refer to TIMING POINTS, not pin.max_*.
    # Check delta_delay's meaning in your release: lumped net delta vs cell delta
    # vs combined delta are NOT interchangeable. We never change SI settings.
    variable point_fields [dict create \
        arrival_native_ns {time arrival} \
        transition {text transition_type} \
        slew_ns {time slew} \
        capacitance_pf {cap load} \
        si_delta_native_ns {time delta_delay}]
    variable object_fields [dict create \
        object_class {text object_type} \
        direction {text direction}]
    variable points_property timing_points
    variable point_object_property pin

    # These optional collection properties are RELEASE DEPENDENT. Use
    # report_property $path to find the appropriate names. Set an entry to {}
    # if your release has no separate clock path collection. Network/SI metrics
    # then remain null; native clock latency is still exported separately.
    variable clock_path_properties [dict create \
        launch launching_clock_path capture capturing_clock_path]
    # "path": property returns timing paths with timing_points.
    # "points": property returns timing points directly.
    variable clock_collection_kind [dict create launch path capture path]
}
