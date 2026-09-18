proc ::ptx::validate_config {cfg} {
    set defaults [default_config]
    dict for {k v} $cfg {
        if {![dict exists $defaults $k]} {error "Unknown config key '$k' (possible typo)"}
    }
    set cfg [dict merge $defaults $cfg]
    foreach key {run_id output_dir comparison_context scenario design_revision} {
        if {[dict get $cfg $key] in {{} CHANGE_ME}} {error "Set config '$key' explicitly"}
    }
    foreach key {max_paths_per_group nworst progress_every} {
        set v [dict get $cfg $key]
        if {![string is integer -strict $v] || $v < 1} {error "$key must be a positive integer"}
    }
    if {[dict get $cfg nworst] > [dict get $cfg max_paths_per_group]} {error "nworst must not exceed max_paths_per_group"}
    if {[dict get $cfg delay_type] ni {max min}} {error "delay_type must be max or min"}
    if {[dict get $cfg pba_mode] ni {none path exhaustive}} {error "pba_mode must be none, path or exhaustive"}
    if {[dict get $cfg session_kind] ni {single worker}} {error "DMSA manager is not supported. Run in each worker with its own output directory."}
    if {[dict get $cfg input_time_unit] ni {s ms us ns ps fs}} {error "Set input_time_unit from report_units (s/ms/us/ns/ps/fs)"}
    if {[dict get $cfg input_capacitance_unit] ni {f nf pf ff}} {error "Set input_capacitance_unit from report_units (f/nf/pf/ff)"}
    foreach key {include_clock_paths fail_on_slack_mismatch} {
        set v [dict get $cfg $key]
        if {![string is boolean -strict $v]} {error "$key must be boolean"}
        dict set cfg $key [expr {$v ? 1 : 0}]
    }
    set cutoff [dict get $cfg slack_lesser_than_ns]
    if {$cutoff ne {} && ![finite $cutoff]} {error "slack_lesser_than_ns must be finite or {}"}
    set tolerance [dict get $cfg slack_tolerance_ns]
    if {![finite $tolerance] || $tolerance < 0} {error "slack_tolerance_ns must be finite and >= 0"}
    if {![llength [dict get $cfg path_groups]]} {error "path_groups cannot be empty"}
    if {![llength [dict get $cfg formats]]} {error "formats cannot be empty"}
    foreach format [dict get $cfg formats] {if {$format ni {json csv}} {error "Unknown format '$format'"}}
    return $cfg
}

proc ::ptx::run {cfg} {
    variable config
    variable coverage
    variable topology_cache
    set config [validate_config $cfg]
    set coverage {}
    set topology_cache {}
    set design [require_primetime]
    set output [file normalize [dict get $config output_dir]]
    if {[file exists $output]} {error "Output already exists: $output. Choose a new run directory; no files were overwritten."}
    set groups [select_groups [dict get $config path_groups]]
    set vars [snapshot_app_variables]
    set metadata [dict create run_id [dict get $config run_id] \
        comparison_context [dict get $config comparison_context] \
        scenario [dict get $config scenario] design $design \
        design_revision [dict get $config design_revision] \
        tool PrimeTime tool_version [dict get $vars sh_product_version value] \
        exported_at_utc [clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}] \
        time_unit ns capacitance_unit pf \
        input_time_unit [dict get $config input_time_unit] \
        input_capacitance_unit [dict get $config input_capacitance_unit] \
        unit_source user_config pba_mode [dict get $config pba_mode] \
        analysis_type [dict get $config delay_type] session_kind [dict get $config session_kind] \
        notes [dict get $config notes]]
    set staging "${output}.partial-[pid]-[clock clicks]"
    file mkdir $staging
    set writer {}
    set count 0
    set group_results {}
    set code [catch {
        set writer [writer_open $staging $metadata]
        foreach group [lsort [dict keys $groups]] {
            puts "PTX: collecting group '$group'"
            set selected [query_paths $group]
            set rank 0
            foreach_in_collection path [dict get $selected paths] {
                incr rank
                incr count
                set id [format P%07d $count]
                set record [collect_path $path $id $group $rank]
                set native_type [get $record path_type_native]
                if {$native_type ne {} && ![string match "[dict get $config delay_type]*" $native_type]} {
                    error "Path $id has native type '$native_type', different from requested delay_type"
                }
                set cutoff [dict get $config slack_lesser_than_ns]
                set slack [get $record slack_ns]
                if {$cutoff ne {} && ($slack eq {} || $slack >= $cutoff)} {
                    error "Path $id does not satisfy the requested finite slack cutoff"
                }
                set record [calculate $record]
                set writer [writer_add $writer $record]
                if {$count % [dict get $config progress_every] == 0} {puts "PTX: exported $count paths"}
            }
            lappend group_results [dict create name $group count $rank \
                limit_reached [expr {$rank >= [dict get $config max_paths_per_group]}] \
                command [dict get $selected command]]
        }
        writer_close $writer
        set writer {}
        write_manifest $staging $metadata $group_results $count $vars
        if {[file exists $output]} {error "Output appeared during export; refusing to overwrite $output"}
        file rename $staging $output
    } result options]
    if {$code} {
        writer_abort $writer
        catch {write_text [file join $staging ERROR.txt] "$result\n\n[get $options -errorinfo]"}
        puts stderr "PTX: FAILED. Partial output retained at $staging"
        return -options $options $result
    }
    puts "PTX: COMPLETE: $count paths -> $output"
    return $output
}

# Small, read-only debugging entry point. Call AFTER setting ::ptx::config.
# Example: set ::ptx::config [ptx::validate_config $cfg]
#          set p [get_timing_paths -max_paths 1 -path_type full_clock_expanded]
#          ptx::inspect_path $p
proc ::ptx::inspect_path {path} {
    variable path_fields
    variable config
    set config [validate_config $config]
    set fields [read_fields $path timing_path $path_fields]
    dict for {field spec} $path_fields {
        puts [format {%-36s %-28s %-12s %s} $field [lindex $spec 1] \
            [dict get $fields sources $field status] [dict get $fields values $field]]
    }
    return $fields
}

proc ::ptx::inspect_points {path} {
    variable config
    variable point_fields
    variable collection_attributes
    set config [validate_config $config]
    set read [read_collection $path timing_path [dict get $collection_attributes data_points]]
    if {[dict get $read status] ne "ok"} {error "Timing points unavailable: $read"}
    set points [collect_points [dict get $read value]]
    foreach point $points {
        puts "POINT [dict get $point index]: [dict get $point object_name]"
        dict for {field spec} $point_fields {
            puts [format {  %-30s %-26s %-12s %s} $field [lindex $spec 1] \
                [dict get $point attributes $field status] [get $point $field]]
        }
    }
    return $points
}
