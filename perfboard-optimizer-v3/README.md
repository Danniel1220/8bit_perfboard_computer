# Perfboard optimizer v3 — placement exploration and signal bundles

This version starts from the configured ALU component placement with **blank routing**. No old best checkpoint or migrated run is included. Your previous optimizer folder and run remain separate.

The initial display has **170 disconnected sections**: that is the expected count when only mandatory pin escapes exist. It is not comparable to the old run's one remaining section. The ALU logic remains unchanged and passes all 524,288 combinational cases and 8,192 flag-state cases.

## What changes in v3

The best checkpoint remains monotonic: unresolved count first, physical validity required, then visual quality. Individual explorer workers may deliberately discard wiring and accept a much worse starting score to develop a new arrangement. This does not replace the saved best. Other workers continue refining layouts.

By default, workers 2, 5, 8, and 11 (zero-based IDs) are explorers in a 12-worker run. They attempt a different arrangement immediately and every 800 local candidates after that, with a protected 300-candidate routing period. During that period global adoption and elite restarts are suspended; 85% of attempts focus on repairing the alternative's wiring without another placement mutation. The remaining attempts retain ordinary placement/channel/routing mutations. Exploration does not promise a better outcome. After the grace period the normal adoption policy applies again.

Large changes include swapping two IC positions, cycling four IC positions, moving an individual IC anywhere within board dimensions, and translating a functional group by up to half the board dimensions. Each attempt is checked for bounds, bodies, capacitor overlap, pin exits, and all other physical rules. Up to 32 proposals are tried per restart; if none is valid, the worker keeps its current state. ICs marked fixed and connector edge assignments remain respected. This is a portfolio of broader rearrangements, not exhaustive placement enumeration or simultaneous random packing of every IC.

The configured signal families A, B, BX, SUM, AND, OR, XOR, AR, LOG, R, and BUS have a strong preference for adjacent parallel lanes. Final scoring penalizes exposed bundle edges: each top-wire unit edge wants a parallel peer one hole away on each side. Thus a continuous bus is preferred over isolated pairs. Mandatory escape regions and underside links are excluded. Existing bend and organization costs still apply. This is a soft bus preference, not a guarantee of perfect bit order, matching lengths, or aligned bends.

The router also adds a 2.5 cost to steps without adjacent parallel support when peer routing is available. Hard legality checks still take precedence, and all step costs remain positive. Final bundle separation has weight 4.0 (compared with wire-length weight 0.08). These are deliberately strong initial settings; no overnight performance or completion benchmark has been run for v3.

### Tuning v3

In `config/alu.json`:

| Setting | Default | Meaning |
|---|---:|---|
| `search.explorer_every` | 3 | Every third worker explores; 0 disables it, 1 enables it for every worker. With fewer than three workers, change this if you want explorers. |
| `search.exploration_initial_candidates` | 0 | Local candidate count before the first placement restart. |
| `search.exploration_interval_candidates` | 800 | Candidate spacing between placement restart attempts. |
| `search.exploration_grace_candidates` | 300 | Protected routing budget for a successful alternative. |
| `search.placement_restart_attempts` | 32 | Bounded placement proposals per restart. |
| `search.bundle_spacing_cells` | 1 | Desired distance between adjacent parallel lanes. |
| `search.bundle_route_penalty` | 2.5 | Inner-router penalty for unsupported steps. |
| `weights.bundle_separation` | 4.0 | Final quality weight for separated bundle edges. |

Bundle membership is explicit in `signal_bundles`; this does not change logical bit identities. Search settings and weights can change on resume. Changing bundle definitions changes the compatibility hash, so use a new run. The worker state preserves the remaining exploration budget and next restart count. Diagnostics include `placement_exploration` worker events, exploration attempt/success counters, and `organization.bundle_separation` in the best score. Regular SVG snapshots show the best result, not a temporarily worse explorer state.

### Changing escape settings before a new run

Use `--fresh --blank-routing --run runs/experiment-02` to regenerate mandatory pin stubs and the junction plan from your current settings. `--fresh` alone loads the supplied seed, whose escape lengths are both 1. If setting `connector_escape_cells` to 2 with the supplied placement, also change **U_BUS initial x from 5 to 6**: the longer J_BUS stub otherwise reaches its body. V3 retains the default of 1 and does not silently move components to repair an invalid starting configuration.

## Start a new run

Extract the complete ZIP into a **new folder**, beside your existing optimizer folder. Open a terminal in the new folder containing `optimize_alu.py`.

If your existing `python` already has the requirements installed:

```powershell
python optimize_alu.py --fresh --blank-routing --workers 12
```

Otherwise create a virtual environment and install the dependencies first:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe optimize_alu.py --fresh --blank-routing --workers 12
```

Commands below use `python`; substitute `.\.venv\Scripts\python.exe` when using that environment. There is no default time limit. The GPU is unused.

`--fresh` requires an empty/new run folder. It does not erase anything. The default is `runs/alu` inside this new program folder. For another experiment:

```powershell
python optimize_alu.py --fresh --run runs/experiment-02 --workers 12
```

## Pause, save, quit, and resume

Press **P** to pause, **R** to resume, **S** to save and capture an SVG snapshot, or **Q** to save and quit. **Ctrl+C once** also requests a safe stop. Wait for “Search stopped safely” before closing the terminal. A second interrupt forces termination, retaining already durable checkpoints.

Paused means all workers have finished their current candidates and checkpointed. Windows hotkeys need no Enter; Unix terminals require Enter. Alternatively, from a second terminal:

```powershell
python optimize_alu.py --control pause
python optimize_alu.py --control resume
python optimize_alu.py --control save
python optimize_alu.py --control quit
```

Add the same `--run` argument to these commands if you use a custom run. Wait for acknowledgement between commands. After stopping, continue with:

```powershell
python optimize_alu.py --resume --workers 12
```

Resume is also the default. You may change worker count between sessions. Only one coordinator can write to a run folder; an OS lock prevents collisions. Do not copy a v1/v2 checkpoint into the v3 run: physical rules differ, and compatibility checks intentionally reject it.

For overnight operation, prevent Windows from sleeping and leave the terminal open. Pause/stop when you want the computer back. Optional limits:

```powershell
python optimize_alu.py --resume --workers 8 --seconds 28800
python optimize_alu.py --fresh --run runs/sanity-01 --workers 2 --max-candidates 4 --plain
```

The time limit requests a stop; finishing validation/checkpoint work can take a few extra seconds.

## New hard physical rules

Edit `config/alu.json`, then restart the optimizer to apply settings. The shipped ALU uses:

```json
"ic_escape_cells": 1,
"connector_escape_cells": 1,
"physical_junctions": true
```

These are in the `constraints` object. Structural rule changes require another fresh run.

**IC escape N:** cells 1 through N exclude unrelated wires. Cells before N must remain straight and unbranched. A turn or branch may start on cell N itself. The mandatory stub ends at N; any continuation is ordinary routed wire. N=1 is the ALU default. Unused IC pins have no escape reservation. Underneath power/constants retain their existing first-cell no-turn clearance.

**JST clearance:** the first exposed cell beyond the connector housing is protected and must remain straight/unbranched. Branching becomes possible after it. With the default, the connector pin is followed by one cell through the housing margin, one protected exposed cell, then the first turn/branch location. Clearance applies in front of power/unused connector pins as well. All four board edges are supported.

**Physical T/+ junctions:** exactly one arm's wire reaches the central hole. Other arms terminate in distinct adjacent holes, linked underneath. There are three T choices, and the two shown + choices plus their rotations. Landing holes must be free of unrelated wiring, pins/bodies, and forbidden escape regions. Incoming non-owner arms must approach their landing holes straight. A mandatory escape cannot be shortened by substituting an underneath link. Interacting junctions cannot claim the same landing hole. A bounded local template solver selects a compatible arrangement or rejects the junction.

Logical connectivity is represented internally by a grid graph; a validated physical realization specifies which edges are top wires and which are underside links. The same realization drives validation and drawing. A graph junction dot alone is no longer sufficient. Ordinary allowed orthogonal crossings remain insulated, electrically separate crossings.

## SVGs and construction information

Open `runs/alu/exports/best.svg`. Thick coloured paths are the actual continuous top-side wires with real endpoint gaps. Thin dashed lines in the net's colour show adjacent-hole solder links in a separate **Underneath-connections** group, which you can hide in Illustrator. `examples/junction-templates.svg` illustrates the five discussed arrangements using the same physical-wire realization code.

Exports also contain:

- `best.json`: logical candidate, physical pin assignments, and validated junction plan.
- `physical-wires.json`: actual top-wire paths and underside junction links.
- `connections.csv`: IC/connector pin assignments and underneath constant ties.
- `underneath-connections.csv`: each branch solder link's two hole coordinates, zero-based.
- `validation.json`: completeness, physical errors, and functional-validation information.

The program exports editable SVG, not Illustrator's private `.ai` format. Open the SVG in Illustrator and save an `.ai` copy if wanted. Exports are updated for every global-best improvement; they are not rendered for every evaluated candidate.

SVG history lives in `runs/alu/exports/snapshots/`: startup/resume, every five new-best checkpoints, and manual S/save. Filenames include UTC time, checkpoint number, and unresolved count. Your requested ALU retention is **10,000**. In the `search` object:

```json
"svg_snapshot_every": 5,
"svg_snapshot_retention": 10000
```

Manually export without searching:

```powershell
python optimize_alu.py --export-svg --output review-copy
```

## Validation and completion

```powershell
python optimize_alu.py --validate
```

Reports go to `runs/alu/reports/`. Exit 0 means complete; exit 3 means valid but disconnected; exit 2 means invalid input/candidate or another command error. Exit 1 from a search means a worker failure. The fresh blank board returns 3, as expected.

Complete requires all nets connected, no hard geometry/escape/physical-junction violations, and preserved electrical logic. Exhaustive functional validation runs at startup and after logical transformations. Pure placement/routing uses lighter canonical/physical checks. These checks cover the configured digital behavior and geometric construction rules, not analogue timing or power integrity.

The adder/gate/mux architecture and flags are unchanged: arithmetic ADD/SUB, XOR, AND, OR; C from arithmetic carry-out, ZERO_N from the 74LS688, N=R7, ADD/SUB V from the 74LS151. The 74LS173 captures all four on enabled rising clocks and clears asynchronously; the 74LS153 selects the stored flag. See CONFIGURATION.md for signal roles and pin definitions.

## What the diagnostics changed

The overnight run showed roughly 63% routing time and very low acceptance of plain moves/rotations (0.7%/0.55%). The new default mutation mix spends more effort on routing, commutative inputs, connector order, and equivalent channels. Moves, rotations, group moves, and plateau diversification remain enabled. A local attachment check rejects impossible branch placements before wasting a complete A* route on them. This is a measured-data-informed starting policy, not a demonstrated speedup; the new rules need a fresh long-run baseline.

The original queue-full crash is fixed: worker notifications are nonblocking; critical pause/save/done/error status is also written to disk, and best proposals are already durable. The coordinator polls changed status/proposal files every two seconds as a fallback. A full telemetry queue no longer kills a worker or prevents process shutdown. Final candidate counters are recovered from durable worker states when necessary.

The historical 12-worker recommendation is retained for convenience. The old 4/8/12/16 benchmark is labelled v1 data and was not rerun for this release. Eight workers may suit concurrent desktop work. To benchmark the new rules yourself:

```powershell
python optimize_alu.py --benchmark --benchmark-seconds 15
```

## Telemetry, logs, and feedback

```powershell
python optimize_alu.py --resume --workers 12 --refresh-rate 5 --verbosity normal
python optimize_alu.py --resume --workers 8 --refresh-rate 3 --verbosity trace
```

The in-place Rich dashboard counts **fully scored candidate states**, not A* expansions. It shows rates, best score, worker activity, plateau levels, CPU seconds/RSS, and phase timing. Some candidates are fast rejects. Accepted counts include exploratory states, not only improvements. New-best time may indicate aesthetic improvement rather than a lower unresolved count.

`wire_length` counts total top and underside grid edges; `top_wire_length` and `underneath_links` are separately recorded. Bends now count actual continuous top-wire corners rather than arbitrary route-record boundaries. The historical v1/v2 bend totals therefore are not directly comparable.

Logs under `runs/alu/logs/` include `best-history.jsonl`, `events.jsonl`, and per-worker JSONL. Route-failure counters now include `junction_attachment` and `junction_clearance`. Summaries appear every ten minutes and retain the latest 144. Worker/event logs rotate at 20 MiB with three compressed backups. Best history rotates at 500 MiB with one backup. Manually created exports, reports, diagnostics ZIPs, and benchmark folders accumulate until you remove/archive them.

Press S, then export feedback:

```powershell
python optimize_alu.py --export-diagnostics --output feedback.zip
```

The bundle contains recent log tails (1 MiB each), latest summaries, best checkpoint, configuration/settings, validation, and physical-wire/underneath-link data. SVGs are not included: send selected snapshots separately. The full run folder retains more history than the compact bundle.

## Persistence and recovery

Current best: `runs/alu/checkpoints/best.json`. Versioned archives: `checkpoints/best_*.json` (40 by default). Worker RNG, current state, congestion history, and best proposals: `workers/`. Lifecycle acknowledgements: `workers/*.status.json`. Accumulated time/counters: `runtime.json`.

New bests use checksummed, flushed atomic writes, with a versioned copy written before replacing the current best. On resume, the program checks current best, retained archives, and worker proposals and selects the best valid candidate. A damaged current-best file can be recovered from those copies. If all are lost, it warns and falls back to the configured seed. Worker state is saved every 30 seconds and at pause/stop; global counters every ten seconds and at checkpoint events. A crash can lose recent unsaved exploration/counters. Atomic files cannot protect against drive failure, so retain normal backups for valuable runs.

Search/weight/colour changes can be used on resume. Board, netlist, groups, or physical-rule changes require a new run. RNG state is retained where practical, but time budgets and multiprocessing scheduling prevent exact replay.

## Tests

```powershell
python -m unittest discover -s tests -v
python tests/integration_smoke.py
python tests/interrupt_smoke.py
python tests/queue_pressure_smoke.py
python tests/exploration_smoke.py
```

Tests use temporary run directories and bounded short work. The pressure test deliberately leaves the IPC queue full while one worker evaluates one candidate and exits. No old checkpoint is migrated or replaced. Legacy config/seed files exist solely for v1 regression tests; normal execution uses `config/alu.json` and `config/alu-seed-v2.json`.
