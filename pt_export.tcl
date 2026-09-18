# PrimeTime collection exporter. Source this file in pt_shell, not plain tclsh.
# Target language: Tcl 8.5+. No Tcllib / Python required inside PrimeTime.
namespace eval ::ptx {
    variable version 1.0.0
    variable schema_version 1.0
    variable root [file dirname [file normalize [info script]]]
}
foreach ptx_module {config attributes common adapter collect calculate writers run} {
    source [file join $::ptx::root ${ptx_module}.tcl]
}
unset ptx_module

