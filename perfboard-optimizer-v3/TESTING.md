# V3 validation

All 32 tests passed across the full-suite and focused follow-up checks. New coverage checks bus versus separated/pair scoring, rotation invariance, actual A* parallel-lane preference without illegal crossings, broader placement validity, fixed components, unchanged logic, and worker allocation.

The bounded explorer smoke test passed four total candidates across two worker sessions: a new placement was adopted locally, the 20-candidate test grace period counted down correctly, and the remaining budget and schedule survived save/resume. The two-worker integration test passed pause/save/resume/quit, run locking, corrupted-best recovery, counters, validation, SVG, and diagnostics.

The supplied v3 seed was revalidated: 524,288 ALU and 8,192 flag-state cases pass, 170 disconnected sections, zero hard violations. See tests/fresh-seed-validation.json. This is intentionally unfinished wiring, not a completed board.

No long optimization or new worker benchmark was performed. Historical benchmarks are not predictions for v3. Existing v2 folders/runs were not modified. V3 has new quality terms and bundle definitions, so use a new run rather than copying v2 checkpoints.
