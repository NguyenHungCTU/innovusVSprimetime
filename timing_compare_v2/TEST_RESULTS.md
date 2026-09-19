# Verification — V2.0.0

Date: 2026-09-18.

Command: `python3 -m unittest discover -s tests -v`

Result: **18 tests passed, 0 skipped**, Python 3.12.14 and Tcl 9.0.4 (headless tkinter interpreter).

Coverage:

- Reversed WNS ranking and shuffled raw records still preserve PT target order.
- Missing/query-ambiguous/truncated candidates retain their golden slots.
- Positive Innovus slack remains eligible for comparison.
- Native identity checks include clocks, edge types/times and data topology.
- Exact name mapping and Tcl quoting/glob escaping for bus pins.
- ps-to-ns conversion, floating point tails, signed rounding and exact JSON numeric output.
- Actual arrival/required reference mismatches remain visible.
- Setup/hold slack formula; PT hold phase uses capture open edge.
- SI semantic gating, signed net delta sum, and incomplete SI remains null.
- Multiple views, duplicate golden identities, stale jobs and incomplete JSONL.
- Tcl collector with mocked native collection commands through actual JSONL and Python comparison.

Additional verification:

- All Python sources parse under Python 3.6 grammar. This is syntax verification, not an execution test on Python 3.6.
- PT update snippets from `PT_V1_UPDATE_NOTES.md` were applied to an isolated temporary V1 copy. Its mock exporter completed without a supplied scenario, preserved numeric provenance and passed its slack check. The V2 reader accepted both resulting JSON and CSV exports. Original V1 files were not modified.
- V2 prepare was also run against the existing V1 synthetic export.

No licensed PrimeTime/Innovus instance was available. Tests validate pipeline behavior, arithmetic and collection handling under the mock contract; they do not establish that every optional native property name exists or has the intended SI/clock semantics in a particular installed EDA release. See README's probe and mapping instructions.
