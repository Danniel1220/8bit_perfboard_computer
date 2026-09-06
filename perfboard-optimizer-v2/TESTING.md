# Version 2 validation and diagnostics

The release starts from blank routing, with 170 disconnected sections and zero hard violations. All 524,288 combinational ALU and 8,192 sequential flag cases pass. The saved fresh-seed report is `tests/fresh-seed-validation.json`.

The suite covers the three T templates and rotated equivalents, four rotated + owner choices, forced bus-tap choices, blocked/shared landing holes, preservation of mandatory pin stubs, exact top/underneath graph reconstruction, inclusive IC escape lengths 1/2/3 in every rotation, exterior JST protection, stale plan rejection, physical SVG gaps and underside CSV, queue-full handling, and legacy logic/checkpoint regression cases. Snapshot interval/manual-save/retention checks are retained.

The short integration test covers two workers, true pause, save, resume, quit, exclusive run locking, deliberate corrupt-best recovery, counters, SVG/diagnostic export, and help. The queue-pressure test scores exactly one candidate with an intentionally undrained full IPC queue and checks clean exit plus durable state/status. SIGINT shutdown is exercised by the separate interrupt smoke test.

No long optimization or new worker-count benchmark was run. The historical benchmark shipped in `benchmarks/recommendation.json` predates these physical rules. Its 12-worker recommendation is provisional. No performance gain or completion time is claimed for the new rule set.

The diagnostics driving this release showed: 37 early pin-exit branches followed by unnecessary fixed tails; illegal-for-construction bus taps at connector fronts; 9 queue.Full worker failures; approximately 63% routing time; move/rotation acceptance around 0.7%/0.55%, compared with 17.4% for routing mutations. These justified explicit physical branches, shorter IC escapes, connector protection, durable nonblocking notifications, and a more routing/channel-focused initial mutation mix.

The original run is untouched. No migrated checkpoint is included, following the user's decision to restart from scratch. `MANIFEST.json` lists SHA-256 hashes for packaged files.
