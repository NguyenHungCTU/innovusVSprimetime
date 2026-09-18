# Portable smoke test when tclsh 8.5+ is available. NO PrimeTime license needed.
set root [file dirname [file dirname [file normalize [info script]]]]
source [file join $root pt_export.tcl]
source [file join $root tests mock_pt.tcl]
mock::setup
set output [file join [pwd] mock_export_[pid]_[clock seconds]]
ptx::run [mock::config $output]
puts "MOCK ONLY: inspect $output using timing_data.py"
