# Pure Tcl math. No PrimeTime commands; independently testable.
namespace eval ::ptx {
    variable derived_types [dict create \
        startpoint_transition text endpoint_transition text \
        launch_clock_pin text \
        tlaunch_ns time tcapture_ns time tck2q_ns time tdata_ns time \
        tdata_plus_ck2q_ns time phase_shift_ns time \
        slack_recomputed_ns time slack_error_ns time \
        data_status text launch_network_status text capture_network_status text \
        phase_status text slack_check_status text]
    foreach role {data launch capture} {
        dict set derived_types si_${role}_observed_sum_ns time
        dict set derived_types si_${role}_complete_sum_ns time
        dict set derived_types si_${role}_observed_count number
        dict set derived_types si_${role}_missing_count number
        dict set derived_types si_${role}_unclassified_count number
        dict set derived_types si_${role}_status text
    }
}

proc ::ptx::point_indices {points name} {
    set found {}
    set i 0
    foreach point $points {
        if {$name ne {} && [get $point object_name] eq $name} {lappend found $i}
        incr i
    }
    return $found
}

proc ::ptx::difference {points left right} {
    if {$left < 0 || $right < $left || $right >= [llength $points]} {return {}}
    set a [get [lindex $points $left] arrival_native_ns]
    set b [get [lindex $points $right] arrival_native_ns]
    if {$a eq {} || $b eq {}} {return {}}
    return [expr {$b - $a}]
}

proc ::ptx::with_step_delays {points} {
    set result {}
    set previous {}
    foreach point $points {
        set value [get $point arrival_native_ns]
        set delta {}
        if {$value ne {} && $previous ne {}} {set delta [expr {$value - $previous}]}
        dict set point point_arrival_delta_ns $delta
        lappend result $point
        set previous $value
    }
    return $result
}

proc ::ptx::is_input {point} {
    return [expr {[get $point direction] in {in input}}]
}

proc ::ptx::is_output {point} {
    return [expr {[get $point direction] in {out output}}]
}

# Detect CK/Q using exact objects and their owning sequential cell, never /CK regex.
proc ::ptx::data_boundaries {path} {
    set points [dict get $path data_points]
    set result [dict create ck -1 q -1 end -1 status missing_boundary]
    set ends [point_indices $points [dict get $path endpoint]]
    if {[llength $ends] != 1} {dict set result status ambiguous_or_missing_endpoint; return $result}
    set end [lindex $ends 0]
    dict set result end $end
    if {[get $path launch_is_latch] ne "0"} {
        dict set result status latch_or_unknown_launch_type
        return $result
    }
    set starts [point_indices $points [dict get $path startpoint]]
    set ck -1
    set q -1
    if {[llength $starts] == 1} {
        set start [lindex $starts 0]
        set p [lindex $points $start]
        set cell [get $p cell_name]
        if {$cell ne {} && [get $p cell_is_sequential] eq "1"} {
            if {[is_input $p] && [get $p is_clock_pin] eq "1" && [get $path launch_clock] ne {}} {set ck $start}
            if {[is_output $p]} {set q $start}
        }
    }
    # If startpoint is a cell or Q pin, use a UNIQUE known clock pin of that cell.
    if {$ck < 0} {
        set cell [dict get $path startpoint]
        if {$q >= 0} {set cell [get [lindex $points $q] cell_name]}
        set candidates {}
        for {set i 0} {$i < $end} {incr i} {
            set p [lindex $points $i]
            if {[get $p cell_name] eq $cell && [get $p is_clock_pin] eq "1" && [is_input $p]} {
                lappend candidates $i
            }
        }
        if {[llength $candidates] == 1} {set ck [lindex $candidates 0]}
    }
    if {$ck >= 0 && $q < 0} {
        set cell [get [lindex $points $ck] cell_name]
        set candidates {}
        for {set i [expr {$ck + 1}]} {$i < $end} {incr i} {
            set p [lindex $points $i]
            if {$cell ne {} && [get $p cell_name] eq $cell && [is_output $p]} {lappend candidates $i}
        }
        if {[llength $candidates] == 1} {set q [lindex $candidates 0]}
    }
    dict set result ck $ck
    dict set result q $q
    if {$ck >= 0 && $q > $ck && $end > $q} {
        dict set result status ok
    } elseif {$q >= 0 && $end > $q} {
        dict set result status q_to_endpoint_only
    } else {dict set result status unsupported_or_missing_ck_q}
    return $result
}

# Root-to-sink differences cancel the arrival reference. Expanded generated-clock
# master segments BEFORE the selected clock source are not counted as its network.
proc ::ptx::network_span {path role sink} {
    set result [dict create status missing_clock_points value {} points {} \
        chain_index {} root_index {} sink_index {} root {} sink $sink]
    if {$sink eq {}} {dict set result status missing_clock_sink; return $result}
    if {[get $path ${role}_is_propagated] eq "0"} {
        dict set result status ideal_clock
        return $result
    }
    set sources [get $path ${role}_clock_sources]
    if {![llength $sources]} {dict set result status missing_clock_sources; return $result}
    set candidates {}
    foreach chain [dict get $path clock_paths] {
        if {[dict get $chain segment] ne $role} {continue}
        set points [dict get $chain points]
        set ends [point_indices $points $sink]
        if {[llength $ends] != 1} {continue}
        set last [lindex $ends 0]
        set roots {}
        foreach name $sources {
            foreach idx [point_indices $points $name] {
                if {$idx <= $last} {lappend roots $idx}
            }
        }
        set roots [lsort -integer -unique $roots]
        if {[llength $roots] != 1} {continue}
        set first [lindex $roots 0]
        set value [difference $points $first $last]
        if {$value eq {}} {continue}
        lappend candidates [dict create status ok value $value \
            points [lrange $points $first $last] \
            chain_index [dict get $chain chain_index] \
            root_index [expr {$first + 1}] sink_index [expr {$last + 1}] \
            root [get [lindex $points $first] object_name] sink $sink]
    }
    if {[llength $candidates] == 1} {return [lindex $candidates 0]}
    if {[llength $candidates] > 1} {dict set result status ambiguous_clock_paths}
    return $result
}

# Only receiving points are candidates for PT's stage SI annotation. The first
# point is the segment boundary, so its incoming stage belongs to the previous segment.
proc ::ptx::si_summary {points} {
    set sum 0.0
    set observed 0
    set missing 0
    set unknown 0
    foreach point [lrange $points 1 end] {
        set class [get $point object_class]
        set direction [get $point direction]
        if {$class ni {pin port} || $direction ni {in input out output inout}} {
            incr unknown
            continue
        }
        set receiver [expr {($class eq "pin" && $direction in {in input inout}) ||
                            ($class eq "port" && $direction in {out output inout})}]
        if {!$receiver} {continue}
        set value [get $point si_delta_native_ns]
        if {$value eq {}} {incr missing; continue}
        incr observed
        set sum [expr {$sum + $value}]
    }
    set status complete
    if {$observed == 0} {set status unavailable}
    if {$observed > 0 && ($missing > 0 || $unknown > 0)} {set status partial}
    set observed_sum {}
    set complete_sum {}
    if {$observed > 0} {set observed_sum $sum}
    if {$status eq "complete"} {set complete_sum $sum}
    return [dict create observed_sum_ns $observed_sum complete_sum_ns $complete_sum \
        observed_count $observed missing_count $missing unclassified_count $unknown status $status]
}

proc ::ptx::calculate {path} {
    variable derived_types
    variable config
    dict for {name type} $derived_types {dict set path $name {}}
    dict set path data_points [with_step_delays [dict get $path data_points]]
    set chains {}
    foreach chain [dict get $path clock_paths] {
        dict set chain points [with_step_delays [dict get $chain points]]
        lappend chains $chain
    }
    dict set path clock_paths $chains
    set points [dict get $path data_points]
    foreach role {startpoint endpoint} {
        set found [point_indices $points [get $path $role]]
        if {[llength $found] == 1} {
            dict set path ${role}_transition [get [lindex $points [lindex $found 0]] transition]
        }
    }

    set boundary [data_boundaries $path]
    set ck [dict get $boundary ck]
    set q [dict get $boundary q]
    set end [dict get $boundary end]
    dict set path data_status [dict get $boundary status]
    set data_segment {}
    if {$ck >= 0} {dict set path launch_clock_pin [get [lindex $points $ck] object_name]}
    if {[dict get $boundary status] in {ok q_to_endpoint_only}} {
        dict set path tdata_ns [difference $points $q $end]
        if {$ck >= 0} {
            dict set path tck2q_ns [difference $points $ck $q]
            dict set path tdata_plus_ck2q_ns [difference $points $ck $end]
            set data_segment [lrange $points $ck $end]
        } else {set data_segment [lrange $points $q $end]}
        if {[get $path tdata_ns] eq {} || ($ck >= 0 && [get $path tdata_plus_ck2q_ns] eq {})} {
            dict set path data_status missing_point_arrival
        }
    }
    set data_audit [dict create status [dict get $boundary status]]
    foreach key {ck q end} {
        set idx [dict get $boundary $key]
        set external {}
        if {$idx >= 0} {set external [expr {$idx + 1}]}
        dict set data_audit ${key}_index $external
    }
    set calculations [dict create data $data_audit]

    foreach role {launch capture} metric {tlaunch_ns tcapture_ns} {
        set sink [get $path ${role}_clock_pin]
        set span [network_span $path $role $sink]
        dict set path $metric [dict get $span value]
        dict set path ${role}_network_status [dict get $span status]
        set si [si_summary [dict get $span points]]
        if {[dict get $span status] ne "ok"} {dict set si status [dict get $span status]}
        dict for {name value} $si {dict set path si_${role}_${name} $value}
        dict unset span points
        dict set calculations $role $span
    }
    set si [si_summary $data_segment]
    if {![llength $data_segment]} {dict set si status missing_data_boundary}
    dict for {name value} $si {dict set path si_data_${name} $value}

    # V1 phase is for edge-triggered paths only. Do not flatten latch borrowing.
    dict set path phase_status unsupported_or_missing_edges
    if {[get $path launch_is_latch] eq "0" && [get $path capture_is_latch] eq "0"} {
        set launch [get $path launch_edge_ns]
        set edge capture_close_edge_ns
        if {[get $path analysis_type] eq "min"} {set edge capture_open_edge_ns}
        set capture [get $path $edge]
        if {$launch ne {} && $capture ne {}} {
            dict set path phase_shift_ns [expr {$capture - $launch}]
            dict set path phase_status ok
        }
    }
    dict set path slack_check_status missing_inputs
    set a [get $path arrival_ns]
    set r [get $path required_ns]
    set s [get $path slack_ns]
    if {$a ne {} && $r ne {} && $s ne {}} {
        set calculated [expr {$r - $a}]
        if {[get $path analysis_type] eq "min"} {set calculated [expr {$a - $r}]}
        set error [expr {$calculated - $s}]
        dict set path slack_recomputed_ns $calculated
        dict set path slack_error_ns $error
        set status ok
        if {abs($error) > [dict get $config slack_tolerance_ns]} {set status mismatch}
        dict set path slack_check_status $status
        if {$status eq "mismatch" && [dict get $config fail_on_slack_mismatch]} {
            error "[get $path path_id]: slack does not equal arrival/required formula; error=$error ns. Inspect attribute semantics or statistical timing mode."
        }
    }
    dict set path calculations $calculations
    return $path
}
