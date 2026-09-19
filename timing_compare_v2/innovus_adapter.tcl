# ALL native queries live here. This file never sets SI, SDC, units or views.
proc ::iv2::name_of {object} {
    if {$object eq {}} {return {}}
    if {![catch {get_property $object hierarchical_name} name] && $name ne {}} {return $name}
    if {![catch {get_object_name $object} name] && $name ne {}} {return $name}
    error "Cannot resolve object name: $object"
}

proc ::iv2::read_property {object kind property} {
    set record [dict create property $property kind $kind status unavailable value {} raw {} message {}]
    if {$property eq {}} {dict set record status disabled; return $record}
    if {[catch {get_property $object $property} raw]} {
        dict set record message $raw
        return $record
    }
    dict set record raw $raw
    if {$raw eq {}} {dict set record status empty; return $record}
    set value $raw
    if {[catch {
        if {$kind eq "name"} {
            # Clock names may already be plain strings in some releases.
            if {[catch {name_of $raw} value]} {
                if {[regexp {^0x[[:xdigit:]]+$} $raw]} {error "Unresolved object handle $raw"}
                set value $raw
            }
        } elseif {$kind in {time cap number}} {
            if {![string is double -strict $raw] || [regexp -nocase {nan|inf} $raw]} {
                error "Not a finite scalar: $raw"
            }
            set value [format %.17g $raw]
        }
    } message]} {
        dict set record status invalid
        dict set record message $message
        return $record
    }
    dict set record value $value
    dict set record status ok
    return $record
}

proc ::iv2::fields {object specs} {
    set result {}
    dict for {key spec} $specs {
        lassign $spec kind property
        dict set result $key [read_property $object $kind $property]
    }
    return $result
}

proc ::iv2::exact_object {name} {
    # Escape the tool's glob syntax too: Tcl list quoting alone does NOT make
    # a bus name such as U/reg[3]/D an exact pattern.
    set pattern [string map [list \\ \\\\ * \\* ? \\? \[ \\\[ \] \\\]] $name]
    set found {}
    foreach cmd {get_pins get_ports} {
        set objects [uplevel #0 [list $cmd -quiet $pattern]]
        foreach_in_collection obj $objects {
            if {[name_of $obj] eq $name} {lappend found $obj}
        }
    }
    if {[llength $found] != 1} {error "Expected exactly one pin/port '$name'; found [llength $found]"}
    return [lindex $found 0]
}

proc ::iv2::query {target cfg} {
    set from [exact_object [dict get $target query_from]]
    set to [exact_object [dict get $target query_to]]
    set limit [expr {[dict get $cfg candidate_limit] + 1}]
    set cmd [list report_timing -collection -from $from -to $to \
        -max_paths $limit -nworst $limit -path_type full_clock]
    if {[dict get $target analysis_type] eq "max"} {lappend cmd -late} else {lappend cmd -early}
    # Deliberately no slack < 0 filter: a PT violation may meet timing here.
    if {[dict get $cfg view] ne {}} {lappend cmd -view [dict get $cfg view]}
    if {[dict get $cfg retime] ne "none"} {lappend cmd -retime [dict get $cfg retime]}
    set paths [uplevel #0 $cmd]
    return [dict create command $cmd paths $paths]
}

proc ::iv2::point_json {point index} {
    variable point_fields
    variable object_fields
    variable point_object_property
    set values [fields $point $point_fields]
    set object [get_property $point $point_object_property]
    set name [name_of $object]
    set objects [fields $object $object_fields]
    dict for {key value} $objects {dict set values $key $value}
    return [jo [dict create index $index name [js $name] fields [jfields $values]]]
}

proc ::iv2::points_json {points} {
    set result {}
    set i 0
    foreach_in_collection point $points {lappend result [point_json $point [incr i]]}
    return [ja $result]
}

proc ::iv2::candidate_json {path index} {
    variable path_fields
    variable points_property
    variable clock_path_properties
    variable clock_collection_kind
    set values [fields $path $path_fields]
    set points [points_json [get_property $path $points_property]]
    set chains {}
    set clock_status {}
    dict for {role property} $clock_path_properties {
        set role_chains {}
        set status ok
        if {[catch {
            if {$property eq {}} {error "Clock collection property is disabled"}
            set collection [get_property $path $property]
            if {[sizeof_collection $collection] == 0} {error "Empty clock collection"}
            if {[dict get $clock_collection_kind $role] eq "points"} {
                lappend role_chains [points_json $collection]
            } else {
                foreach_in_collection chain $collection {
                    lappend role_chains [points_json [get_property $chain $points_property]]
                }
            }
        } message]} {set status $message; set role_chains {}}
        dict set chains $role [ja $role_chains]
        dict set clock_status $role $status
    }
    return [jo [dict create candidate_index $index fields [jfields $values] \
        points $points clock_paths [jo $chains] clock_status [jstrings $clock_status]]]
}

proc ::iv2::probe {path} {
    # Interactive debug only: uses the REAL object/property list of your release.
    variable points_property
    variable point_object_property
    puts "--- Timing path properties ---"
    report_property $path
    foreach_in_collection point [get_property $path $points_property] {
        puts "--- First timing point properties ---"
        report_property $point
        puts "--- Pin/port properties ---"
        report_property [get_property $point $point_object_property]
        break
    }
}
