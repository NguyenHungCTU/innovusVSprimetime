# TEST DOUBLE ONLY. Opaque collections deliberately are NOT Tcl lists of objects.
# This verifies exporter logic, not Synopsys attribute availability.
namespace eval ::mock {
    variable objects {}
    variable collections {}
    variable serial 0
    variable paths {}
    variable groups {}
    variable queries {}
}

proc ::mock::collection {ids} {
    variable serial
    variable collections
    set handle _mock_collection_[incr serial]
    dict set collections $handle $ids
    return $handle
}

proc ::mock::ids {handle} {
    variable collections
    if {$handle eq {}} {return {}}
    if {![dict exists $collections $handle]} {error "Not a collection: $handle"}
    return [dict get $collections $handle]
}

proc ::mock::object {id attributes} {
    variable objects
    dict set objects $id $attributes
    return [collection [list $id]]
}

proc ::sizeof_collection {handle} {return [llength [::mock::ids $handle]]}

proc ::foreach_in_collection {var handle body} {
    foreach id [::mock::ids $handle] {
        uplevel 1 [list set $var [::mock::collection [list $id]]]
        set code [catch {uplevel 1 $body} result options]
        if {$code == 3} {break}
        if {$code == 4} {continue}
        if {$code == 2} {return -code return $result}
        if {$code} {return -options $options $result}
    }
    return {}
}

proc ::get_attribute {args} {
    if {[lindex $args 0] eq "-quiet"} {set args [lrange $args 1 end]}
    lassign $args collection attr
    set ids [::mock::ids $collection]
    if {[llength $ids] != 1} {error "Mock scalar attribute read requires one object"}
    set id [lindex $ids 0]
    if {![dict exists $::mock::objects $id $attr]} {error "Attribute '$attr' not available on '$id'"}
    return [dict get $::mock::objects $id $attr]
}

proc ::get_object_name {handle} {return [get_attribute $handle full_name]}
proc ::get_cells {args} {
    set obj [lindex $args end]
    if {[catch {get_attribute $obj __cell} cells]} {return {}}
    return $cells
}
proc ::get_nets {args} {return {}}
proc ::current_design {} {return [::mock::collection {design}]}
proc ::get_path_groups {pattern} {return [::mock::collection $::mock::groups]}
proc ::get_app_var {name} {
    if {$name eq "sh_product_version"} {return MOCK_NOT_PRIMETIME}
    if {$name eq "si_enable_analysis"} {return true}
    error "Unavailable mock variable"
}

proc ::get_timing_paths {args} {
    lappend ::mock::queries $args
    set opt $args
    foreach k [dict keys $opt] {
        if {$k ni {-group -delay_type -max_paths -nworst -pba_mode -path_type -slack_lesser_than}} {error "Unexpected query flag: $k"}
    }
    set chosen {}
    set counts {}
    set ordered {}
    foreach id $::mock::paths {lappend ordered [list [dict get $::mock::objects $id slack] $id]}
    foreach entry [lsort -real -index 0 $ordered] {
        lassign $entry slack id
        set attrs [dict get $::mock::objects $id]
        if {[dict get $attrs path_group] ne [dict get $opt -group]} {continue}
        if {[dict get $attrs path_type] ne [dict get $opt -delay_type]} {continue}
        if {[dict exists $opt -slack_lesser_than] && $slack >= [dict get $opt -slack_lesser_than]} {continue}
        set end [dict get $attrs endpoint]
        if {![dict exists $counts $end]} {dict set counts $end 0}
        if {[dict get $counts $end] >= [dict get $opt -nworst]} {continue}
        dict incr counts $end
        lappend chosen $id
        if {[llength $chosen] >= [dict get $opt -max_paths]} {break}
    }
    return [::mock::collection $chosen]
}

proc ::mock::pin {id name cell direction clockpin} {
    return [object $id [dict create full_name $name object_class pin \
        direction $direction is_clock_pin $clockpin __cell $cell]]
}

proc ::mock::point {id object arrival delta {edge rise}} {
    set attrs [dict create object $object arrival $arrival rise_fall $edge transition 0.040]
    if {$delta ne {}} {dict set attrs annotated_delay_delta $delta}
    return [object $id $attrs]
}

proc ::mock::setup {} {
    variable objects
    variable paths
    variable groups
    variable queries
    set objects {}
    set queries {}
    object design {full_name demo_top}
    set lc [object cellL {full_name top/u_launch ref_name DFF_X1 is_sequential true}]
    set cc [object cellC {full_name top/u_capture ref_name DFF_X1 is_sequential true}]
    set dc [object cellD {full_name top/u_logic ref_name BUF_X2 is_sequential false}]
    set bc [object cellB {full_name top/u_clkbuf ref_name BUF_X4 is_sequential false}]
    set ck [pin CK top/u_launch/CK $lc in true]
    set q [pin Q top/u_launch/Q $lc out false]
    set a [pin A top/u_logic/A $dc in false]
    set z [pin Z top/u_logic/Z $dc out false]
    set d [pin D top/u_capture/D $cc in false]
    set cck [pin CCK top/u_capture/CK $cc in true]
    set ba [pin BA top/u_clkbuf/A $bc in false]
    set bz [pin BZ top/u_clkbuf/Z $bc out false]
    set port [object CLK {full_name CLK object_class port direction in is_clock_pin false}]
    set clock [object clock [dict create full_name CLK sources $port]]
    point p0 $ck 0.000 0.040
    point p1 $q 0.095 {}
    point p2 $a 0.300 0.030
    point p3 $z 0.750 {}
    point p4 $d 2.267 0.060
    point l0 $port 10.000 {}
    point l1 $ba 10.120 0.020
    point l2 $bz 10.200 {}
    point l3 $ck 10.300 0.040
    point c0 $port 20.000 {}
    point c1 $ba 20.100 0.010
    point c2 $bz 20.210 {}
    point c3 $cck 20.330 0.010
    set lpath [object lpath [dict create points [collection {l0 l1 l2 l3}]]]
    set cpath [object cpath [dict create points [collection {c0 c1 c2 c3}]]]
    set attrs [dict create \
        startpoint $ck endpoint $d path_group reg2reg path_type max \
        slack -0.215 arrival 1.280 required 1.065 \
        startpoint_clock $clock endpoint_clock $clock endpoint_clock_pin $cck \
        startpoint_clock_latency -0.987 endpoint_clock_latency -0.820 \
        startpoint_clock_open_edge_type rise startpoint_clock_open_edge_value 0.0 \
        endpoint_clock_open_edge_type rise endpoint_clock_open_edge_value 2.0 \
        endpoint_clock_close_edge_type rise endpoint_clock_close_edge_value 2.0 \
        startpoint_is_level_sensitive false endpoint_is_level_sensitive false \
        startpoint_clock_is_propagated true endpoint_clock_is_propagated true \
        common_path_pessimism 0.025 clock_uncertainty 0.080 \
        endpoint_setup_time_value 0.060 \
        points [collection {p0 p1 p2 p3 p4}] \
        launch_clock_paths $lpath capture_clock_paths $cpath]
    object path0 $attrs
    set paths {path0}
    object group0 {full_name reg2reg}
    set groups {group0}
}

proc ::mock::config {output} {
    set cfg [::ptx::default_config]
    foreach {k v} {run_id mock_run comparison_context demo_func_ss design_revision demo_rev
                   scenario MOCK_SS input_time_unit ns input_capacitance_unit pf} {
        dict set cfg $k $v
    }
    dict set cfg output_dir $output
    return $cfg
}
