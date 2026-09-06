# v0.4 verification

38 unit tests passed. They cover inherited electrical/physical checks and storage, plus functional-group relationships, distinct portfolio initialization, per-layout SVGs and unfinished guides, backup recovery, fair evaluation budgets, diversity, stale-generation rejection, merit/progress admission, retired-layout preservation hooks, and protection against favoring empty wiring.

Bounded process checks passed:
- Two-worker pause, save, resume, clean quit, run lock, corrupt global-best recovery, counters, SVG and diagnostics.
- Twelve-worker portfolio lifecycle with 84 candidates across three sessions: all four live SVG/snapshot paths, partial scout-trial resume, four completed scout trials, retained portfolio state and multi-layout diagnostics.
- SIGINT safe stop followed by resume.
- New portfolio worker with a permanently full notification queue: one candidate, durable state/status and clean exit.
- Legacy v3 explorer save/resume regression (portfolio disabled).

The supplied ALU seed passed all 524,288 combinational cases and 8,192 flag-state cases. It has 170 disconnected sections and zero hard violations; this is a starting point, not a completed board. See tests/fresh-seed-validation.json.

The small unfinished-guide example was rendered and visually inspected. Packaging is checked with CRC and per-file SHA-256 hashes. No long placement/routing search or new worker-throughput benchmark was run. Historical benchmark data predates v0.4.
