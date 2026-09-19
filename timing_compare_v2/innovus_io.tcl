# Small JSON writer, Tcl 8.5+. Raw scalar values are strings intentionally:
# Python Decimal performs unit conversion and calculation without float parsing.
proc ::iv2::js {value} {
    set value [string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t \b \\b \f \\f] $value]
    set out {}
    foreach c [split $value {}] {
        scan $c %c code
        if {$code < 32} {append out [format {\u%04x} $code]} else {append out $c}
    }
    return \"$out\"
}
proc ::iv2::jo {encoded_values} {
    set parts {}
    dict for {key value} $encoded_values {lappend parts "[js $key]:$value"}
    return \{[join $parts ,]\}
}
proc ::iv2::ja {encoded_values} {return \[[join $encoded_values ,]\]}
proc ::iv2::jstrings {values} {
    set d {}
    dict for {key value} $values {dict set d $key [js $value]}
    return [jo $d]
}
proc ::iv2::jfields {fields} {
    set d {}
    dict for {key value} $fields {dict set d $key [jstrings $value]}
    return [jo $d]
}
