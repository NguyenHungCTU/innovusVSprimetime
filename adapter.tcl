# PrimeTime attribute/query boundary. Collection iteration also occurs in collect/run.
# No report text is parsed.
proc ::ptx::require_primetime {} {
    foreach cmd {get_timing_paths get_path_groups get_attribute get_object_name
                 sizeof_collection foreach_in_collection current_design} {
        if {![llength [info commands ::$cmd]]} {
            error "Missing '$cmd'. Source pt_export.tcl inside a loaded pt_shell session; plain tclsh cannot access the timing database."
        }
    }
    set design [current_design]
    if {$design eq {} || [sizeof_collection $design] != 1} {
        error "No single current_design. Load the design, or run inside a DMSA worker."
    }
    return [name_of $design]
}

proc ::ptx::name_of {object_or_name} {
    if {$object_or_name eq {}} {return {}}
    # Some native attributes are names, others are collections. Keep exact names.
    if {![catch {sizeof_collection $object_or_name} n]} {
        if {$n != 1} {error "Expected one object, received collection size $n"}
        # Full-name scalar avoids accidentally serializing a quoted one-name list.
        if {![catch {get_attribute -quiet $object_or_name full_name} full_name] && $full_name ne {}} {
            return $full_name
        }
        return [get_object_name $object_or_name]
    }
    return $object_or_name
}

proc ::ptx::names_of {collection} {
    set names {}
    if {$collection eq {}} {return $names}
    foreach_in_collection obj $collection {lappend names [name_of $obj]}
    return $names
}

proc ::ptx::raw_attribute {object class attr} {
    set value {}
    set message {}
    if {[catch {get_attribute -quiet $object $attr} value]} {
        set message $value
        set value {}
        set status unavailable
    } elseif {$value eq {}} {
        set status empty
    } else {
        set status ok
    }
    count_attribute $class $attr $status
    return [dict create value $value status $status message $message attribute $attr]
}

proc ::ptx::read_fields {object class specs} {
    variable config
    set values {}
    set sources {}
    dict for {field spec} $specs {
        lassign $spec type attr
        set read [raw_attribute $object $class $attr]
        set value [dict get $read value]
        if {[dict get $read status] eq "ok"} {
            set err [catch {
                switch -- $type {
                    time - cap - number {
                        if {![finite $value]} {error "Not a finite scalar number: $value"}
                        set scale 1.0
                        if {$type eq "time"} {set scale [time_scale [dict get $config input_time_unit]]}
                        if {$type eq "cap"} {set scale [cap_scale [dict get $config input_capacitance_unit]]}
                        set value [expr {double($value) * $scale}]
                        if {![finite $value]} {error "Value overflow after conversion"}
                    }
                    bool {
                        if {![string is boolean -strict $value]} {error "Not a boolean: $value"}
                        set value [expr {$value ? 1 : 0}]
                    }
                    name {set value [name_of $value]}
                    text {}
                    default {error "Unknown attribute type '$type'"}
                }
            } msg]
            if {$err} {
                dict set read status invalid
                dict set read message $msg
                set value {}
                count_attribute $class $attr ok -1
                count_attribute $class $attr invalid
            }
        }
        dict set values $field $value
        dict unset read value
        dict set sources $field $read
    }
    return [dict create values $values sources $sources]
}

proc ::ptx::read_collection {object class attr} {
    set read [raw_attribute $object $class $attr]
    if {[dict get $read status] eq "ok"} {
        if {[catch {sizeof_collection [dict get $read value]} n]} {
            dict set read value {}
            dict set read status invalid_collection
            dict set read message $n
            count_attribute $class $attr ok -1
            count_attribute $class $attr invalid_collection
        } elseif {$n == 0} {
            dict set read status empty
        }
    }
    return $read
}

proc ::ptx::select_groups {patterns} {
    # Enumerate once, then apply patterns to full names. Deduplicate overlapping patterns.
    set available [get_path_groups *]
    set selected {}
    set hits {}
    foreach pattern $patterns {dict set hits $pattern 0}
    foreach_in_collection group $available {
        set name [name_of $group]
        foreach pattern $patterns {
            if {[string match $pattern $name]} {
                dict set selected $name $group
                dict incr hits $pattern
            }
        }
    }
    dict for {pattern count} $hits {
        if {$count == 0} {error "Path-group pattern '$pattern' matched no groups. Available: [names_of $available]"}
    }
    return $selected
}

proc ::ptx::query_paths {group_name} {
    variable config
    set cmd [list get_timing_paths \
        -group $group_name \
        -delay_type [dict get $config delay_type] \
        -max_paths [dict get $config max_paths_per_group] \
        -nworst [dict get $config nworst] \
        -pba_mode [dict get $config pba_mode]]
    if {[dict get $config include_clock_paths]} {
        lappend cmd -path_type full_clock_expanded
    } else {
        lappend cmd -path_type full
    }
    set cutoff [dict get $config slack_lesser_than_ns]
    if {$cutoff ne {}} {
        set native_cutoff [expr {$cutoff / [time_scale [dict get $config input_time_unit]]}]
        lappend cmd -slack_lesser_than $native_cutoff
    }
    # List expansion preserves names containing spaces, brackets, dollar signs.
    # Do not retry after removing unsupported options: that changes selection semantics.
    set paths [uplevel #0 $cmd]
    return [dict create paths $paths command $cmd]
}

proc ::ptx::object_info {object} {
    variable topology_cache
    variable object_fields
    set name [name_of $object]
    if {[dict exists $topology_cache $name]} {return [dict get $topology_cache $name]}
    set read [read_fields $object object $object_fields]
    set record [dict get $read values]
    dict set record object_attributes [dict get $read sources]
    dict set record object_name $name
    dict set record cell_name {}
    dict set record cell_ref {}
    dict set record cell_is_sequential {}
    dict set record net_names {}
    if {[get $record object_class] eq "pin"} {
        if {![catch {get_cells -quiet -of_objects $object} cells] && $cells ne {} && [sizeof_collection $cells] == 1} {
            dict set record cell_name [name_of $cells]
            set fields [read_fields $cells cell {cell_ref {text ref_name} cell_is_sequential {bool is_sequential}}]
            dict for {k v} [dict get $fields values] {dict set record $k $v}
        }
    }
    if {![catch {get_nets -quiet -of_objects $object} nets] && $nets ne {}} {
        dict set record net_names [names_of $nets]
    }
    dict set topology_cache $name $record
    return $record
}

proc ::ptx::clock_sources {path role} {
    variable collection_attributes
    set clock_read [read_collection $path timing_path [dict get $collection_attributes ${role}_clock]]
    if {[dict get $clock_read status] ne "ok"} {return {}}
    set clock [dict get $clock_read value]
    if {[sizeof_collection $clock] != 1} {return {}}
    set sources [read_collection $clock clock [dict get $collection_attributes clock_sources]]
    if {[dict get $sources status] ne "ok"} {return {}}
    return [names_of [dict get $sources value]]
}

proc ::ptx::snapshot_app_variables {} {
    variable app_variables
    set result {}
    foreach name $app_variables {
        set value {}
        set status unavailable
        if {[llength [info commands ::get_app_var]] && ![catch {get_app_var $name} value]} {
            set status ok
        } elseif {[info exists ::$name]} {
            set value [set ::$name]
            set status ok
        } else {set value {}}
        dict set result $name [dict create value $value status $status]
    }
    return $result
}
