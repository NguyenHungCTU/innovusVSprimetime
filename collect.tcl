# Collection -> plain Tcl dictionaries. All PrimeTime calls go through adapter.tcl.
proc ::ptx::collect_points {collection} {
    variable point_fields
    set points {}
    set index 0
    foreach_in_collection point $collection {
        incr index
        set fields [read_fields $point timing_point $point_fields]
        set record [dict get $fields values]
        dict set record index $index
        dict set record attributes [dict get $fields sources]
        set object_read [read_collection $point timing_point object]
        if {[dict get $object_read status] ne "ok"} {
            error "timing_point.object is not available at index $index"
        }
        set record [dict merge $record [object_info [dict get $object_read value]]]
        lappend points $record
    }
    return $points
}

proc ::ptx::collect_path {path id group rank} {
    variable config
    variable path_fields
    variable collection_attributes
    set read [read_fields $path timing_path $path_fields]
    set record [dict get $read values]
    foreach required {startpoint endpoint} {
        if {[get $record $required] eq {}} {error "Path $id: required field '$required' unavailable"}
    }
    # Verify native group when available; never silently relabel a different group.
    set native_group [read_fields $path timing_path {path_group {name path_group}}]
    set actual_group [dict get $native_group values path_group]
    if {$actual_group ne {} && $actual_group ne $group} {
        error "Path $id: selected group '$group', returned group '$actual_group'"
    }
    foreach key {run_id comparison_context scenario design_revision} {
        dict set record $key [dict get $config $key]
    }
    dict set record path_id $id
    dict set record group_rank $rank
    dict set record path_group $group
    dict set record analysis_type [dict get $config delay_type]
    dict set record pba_mode [dict get $config pba_mode]
    dict set record attributes [dict get $read sources]

    set data [read_collection $path timing_path [dict get $collection_attributes data_points]]
    if {[dict get $data status] ne "ok"} {error "Path $id: timing points unavailable"}
    dict set record data_points [collect_points [dict get $data value]]

    set chains {}
    foreach role {launch capture} {
        dict set record ${role}_clock_sources [clock_sources $path $role]
        set status disabled
        if {[dict get $config include_clock_paths]} {
            set paths [read_collection $path timing_path [dict get $collection_attributes ${role}_clock_paths]]
            set status [dict get $paths status]
            set chain_index 0
            foreach_in_collection clock_path [dict get $paths value] {
                incr chain_index
                set point_read [read_collection $clock_path timing_path [dict get $collection_attributes clock_path_points]]
                set chain_points {}
                if {[dict get $point_read status] eq "ok"} {
                    set chain_points [collect_points [dict get $point_read value]]
                }
                lappend chains [dict create segment $role chain_index $chain_index \
                    status [dict get $point_read status] points $chain_points]
            }
        }
        dict set record ${role}_clock_paths_status $status
    }
    dict set record clock_paths $chains
    return $record
}
