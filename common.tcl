namespace eval ::ptx {
    variable config {}
    variable coverage {}
    variable topology_cache {}
}

proc ::ptx::finite {value} {
    if {![string is double -strict $value]} {return 0}
    if {[regexp -nocase {nan|inf} $value]} {return 0}
    if {[catch {expr {abs(double($value)) < Inf}} ok]} {return 0}
    return $ok
}

proc ::ptx::time_scale {unit} {
    return [dict get {s 1e9 ms 1e6 us 1e3 ns 1.0 ps 1e-3 fs 1e-6} $unit]
}

proc ::ptx::cap_scale {unit} {
    return [dict get {f 1e12 nf 1e3 pf 1.0 ff 1e-3} $unit]
}

proc ::ptx::get {record key {fallback {}}} {
    if {[dict exists $record $key]} {return [dict get $record $key]}
    return $fallback
}

proc ::ptx::count_attribute {class attr status {amount 1}} {
    variable coverage
    set key [list $class $attr $status]
    dict incr coverage $key $amount
    if {[dict get $coverage $key] == 0} {dict unset coverage $key}
}

# JSON is typed explicitly: a Tcl list/dict/string is never auto-guessed.
proc ::ptx::json_string {s} {
    set out {"}
    foreach c [split $s {}] {
        scan $c %c n
        switch -- $c {
            "\"" {append out {\"}}
            "\\" {append out {\\}}
            default {
                if {$n < 32} {append out [format {\u%04x} $n]} else {append out $c}
            }
        }
    }
    append out {"}
    return $out
}

proc ::ptx::json_number {v} {
    if {$v eq {}} {return null}
    if {![finite $v]} {error "Non-finite JSON number: $v"}
    return [format %.17g [expr {double($v)}]]
}

proc ::ptx::json_scalar {v type} {
    if {$v eq {}} {return null}
    switch -- $type {
        time - cap - number {return [json_number $v]}
        bool {if {$v} {return true}; return false}
        default {return [json_string $v]}
    }
}

proc ::ptx::json_object {encoded_dict} {
    set items {}
    dict for {key value} $encoded_dict {lappend items "[json_string $key]:$value"}
    return "\{[join $items ,]\}"
}

proc ::ptx::json_strings {items} {
    set out {}
    foreach item $items {lappend out [json_string $item]}
    return "\[[join $out ,]\]"
}

proc ::ptx::json_text_dict {record} {
    set out {}
    dict for {k v} $record {dict set out $k [json_string $v]}
    return [json_object $out]
}

proc ::ptx::csv_row {channel values} {
    set quoted {}
    foreach v $values {lappend quoted "\"[string map [list \" \"\"] $v]\""}
    puts $channel [join $quoted ,]
}

proc ::ptx::open_utf8 {path} {
    set fd [open $path w]
    fconfigure $fd -encoding utf-8 -translation lf
    return $fd
}

proc ::ptx::write_text {path text} {
    set fd [open_utf8 $path]
    set code [catch {puts $fd $text} result options]
    close $fd
    if {$code} {return -options $options $result}
}
