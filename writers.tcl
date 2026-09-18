# Serialization only. Values are already normalized; no timing math here.
proc ::ptx::path_types {} {
    variable path_fields
    variable derived_types
    set types {path_id text run_id text comparison_context text scenario text
        design_revision text path_group text group_rank number analysis_type text pba_mode text}
    dict for {field spec} $path_fields {dict set types $field [lindex $spec 0]}
    dict for {field type} $derived_types {dict set types $field $type}
    foreach role {launch capture} {dict set types ${role}_clock_paths_status text}
    return $types
}

proc ::ptx::point_types {} {
    variable point_fields
    variable object_fields
    set types {index number object_name text cell_name text cell_ref text cell_is_sequential bool}
    dict for {field spec} $object_fields {dict set types $field [lindex $spec 0]}
    dict for {field spec} $point_fields {dict set types $field [lindex $spec 0]}
    dict set types point_arrival_delta_ns time
    return $types
}

proc ::ptx::encode_fields {record types} {
    set encoded {}
    dict for {field type} $types {dict set encoded $field [json_scalar [get $record $field] $type]}
    return $encoded
}

proc ::ptx::encode_sources {sources} {
    set out {}
    dict for {field info} $sources {dict set out $field [json_text_dict $info]}
    return [json_object $out]
}

proc ::ptx::encode_points {points} {
    set array {}
    foreach point $points {
        set encoded [encode_fields $point [point_types]]
        dict set encoded net_names [json_strings [get $point net_names]]
        dict set encoded attributes [encode_sources [get $point attributes]]
        dict set encoded object_attributes [encode_sources [get $point object_attributes]]
        lappend array [json_object $encoded]
    }
    return "\[[join $array ,]\]"
}

proc ::ptx::encode_path {path} {
    set out [encode_fields $path [path_types]]
    dict set out attributes [encode_sources [get $path attributes]]
    dict set out data_points [encode_points [get $path data_points]]
    foreach role {launch capture} {
        dict set out ${role}_clock_sources [json_strings [get $path ${role}_clock_sources]]
    }
    set array {}
    foreach chain [get $path clock_paths] {
        set encoded [encode_fields $chain {segment text chain_index number status text}]
        dict set encoded points [encode_points [dict get $chain points]]
        lappend array [json_object $encoded]
    }
    dict set out clock_paths "\[[join $array ,]\]"
    set audit {}
    dict for {role info} [get $path calculations] {
        set values {}
        dict for {k v} $info {
            set type text
            if {[string match *_index $k] || $k eq "value"} {set type number}
            dict set values $k [json_scalar $v $type]
        }
        dict set audit $role [json_object $values]
    }
    dict set out calculations [json_object $audit]
    return [json_object $out]
}

proc ::ptx::csv_fields {record types} {
    set row {}
    dict for {field type} $types {lappend row [get $record $field]}
    return $row
}

proc ::ptx::writer_open {directory metadata} {
    variable config
    set writer [dict create count 0 channels {}]
    # Register opened channels even if a later open fails.
    set code [catch {
        if {"json" in [dict get $config formats]} {
            set fd [open_utf8 [file join $directory timing.json]]
            dict lappend writer channels $fd
            dict set writer json $fd
            puts $fd "\{\"schema_version\":[json_string $::ptx::schema_version],\"metadata\":[json_text_dict $metadata],\"paths\":\["
        }
        if {"csv" in [dict get $config formats]} {
            set fd [open_utf8 [file join $directory paths.csv]]
            dict lappend writer channels $fd
            dict set writer paths $fd
            csv_row $fd [dict keys [path_types]]
            set fd [open_utf8 [file join $directory points.csv]]
            dict lappend writer channels $fd
            dict set writer points $fd
            csv_row $fd [concat {path_id segment chain_index} [dict keys [point_types]] {net_names_json}]
        }
    } result options]
    if {$code} {writer_abort $writer; return -options $options $result}
    return $writer
}

proc ::ptx::writer_add {writer path} {
    if {[dict exists $writer json]} {
        set fd [dict get $writer json]
        if {[dict get $writer count] > 0} {puts $fd ,}
        puts -nonewline $fd [encode_path $path]
    }
    if {[dict exists $writer paths]} {
        csv_row [dict get $writer paths] [csv_fields $path [path_types]]
        set chains [concat [list [dict create segment data chain_index 0 points [get $path data_points]]] [get $path clock_paths]]
        foreach chain $chains {
            foreach point [dict get $chain points] {
                set row [list [dict get $path path_id] [dict get $chain segment] [dict get $chain chain_index]]
                set row [concat $row [csv_fields $point [point_types]] [list [json_strings [get $point net_names]]]]
                csv_row [dict get $writer points] $row
            }
        }
    }
    dict incr writer count
    return $writer
}

proc ::ptx::writer_close {writer} {
    set code [catch {
        if {[dict exists $writer json]} {puts [dict get $writer json] "\n\]\}"}
        foreach fd [dict get $writer channels] {close $fd}
    } result options]
    if {$code} {writer_abort $writer; return -options $options $result}
}

proc ::ptx::writer_abort {writer} {
    foreach fd [get $writer channels] {catch {close $fd}}
}

proc ::ptx::write_manifest {directory metadata groups count variables} {
    variable config
    variable coverage
    set out [dict create schema_version [json_string $::ptx::schema_version] \
        producer [json_string "pt_collection/$::ptx::version"] \
        complete true path_count [json_number $count] \
        metadata [json_text_dict $metadata]]
    set selection {}
    dict for {k v} $config {
        set type text
        if {$k in {max_paths_per_group nworst slack_lesser_than_ns slack_tolerance_ns progress_every}} {set type number}
        if {$k in {include_clock_paths fail_on_slack_mismatch}} {set type bool}
        if {$k in {path_groups formats}} {
            dict set selection $k [json_strings $v]
        } else {dict set selection $k [json_scalar $v $type]}
    }
    dict set out selection [json_object $selection]
    set group_json {}
    foreach group $groups {
        set encoded [encode_fields $group {name text count number limit_reached bool}]
        dict set encoded command [json_strings [dict get $group command]]
        lappend group_json [json_object $encoded]
    }
    dict set out groups "\[[join $group_json ,]\]"
    set attrs {}
    set fd [open_utf8 [file join $directory attribute_coverage.csv]]
    set code [catch {
        csv_row $fd {class attribute status read_count}
        foreach key [lsort [dict keys $coverage]] {
            lassign $key class attr status
            set n [dict get $coverage $key]
            csv_row $fd [list $class $attr $status $n]
            lappend attrs [json_object [dict create class [json_string $class] attribute [json_string $attr] status [json_string $status] read_count [json_number $n]]]
        }
    } msg options]
    close $fd
    if {$code} {return -options $options $msg}
    dict set out attribute_reads "\[[join $attrs ,]\]"
    set maps {}
    foreach map {path_fields point_fields object_fields collection_attributes} {
        dict set maps $map [json_text_dict [set ::ptx::$map]]
    }
    dict set out attribute_map [json_object $maps]
    dict set out path_field_types [json_text_dict [path_types]]
    dict set out point_field_types [json_text_dict [point_types]]
    set vars {}
    dict for {name info} $variables {dict set vars $name [json_text_dict $info]}
    dict set out app_variables [json_object $vars]
    write_text [file join $directory manifest.json] [json_object $out]
}
