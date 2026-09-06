# Perfboard optimizer v0.4

A portfolio search for organized, manually finishable ALU layouts. Four distinct active layouts have independent checkpoints and live SVG exports. Previous releases and run directories are untouched. Extract this release into its own folder and start a new run.

## Install and start

From the folder containing optimize_alu.py:

```powershell
python -m pip install -r requirements.txt
python optimize_alu.py --fresh --blank-routing --workers 12
```

For a named experiment:

```powershell
python optimize_alu.py --fresh --blank-routing --run runs/experiment-04 --workers 12
python optimize_alu.py --resume --run runs/experiment-04 --workers 12
```

Without `--run`, every command targets `runs/alu`; the program does not remember the last named experiment. `--fresh` requires an empty/new directory and never deletes an existing run. `--blank-routing` regenerates pin escapes and the physical junction plan from current settings. The initial ALU has 170 disconnected sections and zero hard violations. No completed board or old optimized checkpoint is included.

If changing `connector_escape_cells` from 1 to 2, also change **U_BUS initial x from 5 to 6** in config/alu.json for the supplied placement. Longer J_BUS stubs otherwise enter U_BUS. Use a new run and `--blank-routing` after changing physical geometry. The supplied defaults remain 1.

## Watch all four layouts live

After startup, open:

```text
runs/alu/portfolio/live.html
```

This local page displays all active SVGs and refreshes every **15 seconds**. It needs no web server or internet connection. With a custom run, use its portfolio/live.html instead.

Stable SVG paths:

```text
runs/alu/layouts/layout-1/exports/best.svg
runs/alu/layouts/layout-2/exports/best.svg
runs/alu/layouts/layout-3/exports/best.svg
runs/alu/layouts/layout-4/exports/best.svg
```

Changed layouts are exported at the refresh interval. Unchanged layouts keep their current SVG. Pressing S and clean shutdown force all four exports. Timestamped copies are retained in each layout's exports/snapshots folder. SVGs contain editable vector geometry. Illustrator may require reopening/reloading to see a file updated externally; the live HTML page refreshes automatically.

The separate **Unfinished-connections** group circles loose endpoints and joins them with labelled magenta dashed lines. These are guides, NOT wire routes. Hide this group to inspect appearance. A net split into k disconnected sections gets k-1 guides, not every possible pair. The corresponding endpoint data is in unfinished-connections.json. See examples/unfinished-guide-demo/preview.png for a small illustration.

The overall best remains separately available at `exports/best.svg`. The four slots show the best result of each current placement family, not every temporary routing mutation or immature scout trial.

## How the search works

With 12 workers, workers 0-7 route the four slots in pairs, and workers 8-11 are continuous placement scouts. Routing workers stay in their assigned placement family: they may change routing, equivalent gate/mux channels and allowed connector pin order, but they do not drift IC placements or adopt another slot's overall best. A replaced slot receives a new generation ID and its routing workers switch to that generation.

Scouts propose functional group exchanges, group movement toward connected groups, spreading groups into board zones, and internal tightening. Group exchanges preserve relative positions and rotations inside each group. All proposals are checked against physical rules before receiving routing time. Up to three bounded batches can seek a distinct arrangement; failed placement attempts do not become valid boards. Initial slots are similarly generated as distinct valid arrangements. If that cannot be done within the bounded attempts, startup reports the problem rather than silently duplicating slots.

The explicit groups pair AND, OR, XOR, B conditioning, adders, and mux ICs. Bus and flag circuitry form additional groups. Inter-group attraction is derived from shared signal nets, excluding power/constants and broadly shared control nets. A separate crowding cost encourages breathing room rather than one dense cluster. These are soft organizational preferences; body overlap, escape rules, pin assignments, electrical equivalence, and physical junction construction remain hard rules.

Each scout alternative receives **300 scored candidates** before admission is considered. Each initial/replacement active slot also receives **300 routing candidates in total across its routing workers** before it can be replaced. Scout trial counts and active-layout counts survive pause, save, and resume.

Admission considers finish merit, meaningful placement diversity, and a bounded progress bonus based on unresolved sections closed per 100 candidates. Thus progress is normalized by scored work, not unadjusted wall-clock time. The bonus allocates exploration opportunity; it does not change a board's displayed finish merit. A candidate can fail admission even after its fair trial. Scouts continue with new alternatives indefinitely; they never permanently converge onto one global best.

## Finish merit and visual quality

Lower **manual-finish merit** is better. Unlike earlier versions, unresolved count is not an absolute first priority among valid boards. A visually better board may win despite more open connections. Every accepted board still has zero hard violations.

Default merit terms in `portfolio.merit_weights`:

| Term | Weight | Meaning |
|---|---:|---|
| unresolved | 8 | Disconnected sections still needing work |
| remaining_distance | 0.1 | Total grid Manhattan distance of unfinished guides |
| bundle_exposure | 100 | Normalized exposed bundle edges, phased in as connectivity develops |
| submodule_spread | 0.8 | IC spread inside functional groups |
| related_group_distance | 3 | Connection-weighted distance between groups |
| group_crowding | 2 | Penalty for packing group centers too closely |
| bends | 0.2 | Actual top-wire corners |
| wire_length | 0.025 | Top plus underside grid edges |

The guide distance is only a rough manual-work estimate: it does not establish that an unobstructed route exists. Visual organization and parallel bundles remain heuristics, not guarantees of perfect bus alignment or easy hand assembly. Unfinished wires remain explicitly unfinished.

The router retains v3's strong parallel-lane preference. Final scoring favors long continuous bundles over separated wires or isolated pairs. Bundle terms are phased in with connected fraction so very sparse initial wiring is not unfairly rewarded for having few exposed edges. Existing quality and bundle scores remain visible for comparison alongside finish merit.

## Worker selection and tuning

`--workers 12` gives eight routers plus four scouts. With eight workers, four route and four scout. With four workers, all route the four slots and there are no dedicated scouts. Fewer workers than slots leave some slots waiting; use at least four workers for four concurrently developed slots, and more than four for scouting. Twelve is a starting suggestion, not a new benchmark result.

In config/alu.json:

| Setting | Default | Meaning |
|---|---:|---|
| portfolio.slots | 4 | Active alternatives; changing this requires a new run |
| portfolio.scouts | 4 | Desired scouts; enough workers are reserved for slot routing first |
| portfolio.trial_candidates | 300 | Fair trial budget for scouts and active slots |
| portfolio.diversity_cells | 1.5 | Minimum placement difference; includes group centers and internal arrangement |
| portfolio.svg_seconds | 15 | Live export/page refresh interval |
| portfolio.progress_weight | 2 | Admission bonus per closed section per 100 candidates |
| portfolio.progress_bonus_cap | 80 | Maximum progress bonus |
| search.placement_restart_attempts | 48 | Proposals per bounded placement batch |
| search.bundle_route_penalty | 2.5 | Inner-router preference for adjacent parallel support |
| search.bundle_spacing_cells | 1 | Desired parallel lane spacing |
| search.svg_snapshot_retention | 10000 | Retained SVG snapshots per export family |
| search.checkpoint_retention | 40 | Retained overall-best checkpoint versions |

The v3 explorer_every/exploration_grace settings are legacy and do not control portfolio workers. Routing, bundle, merit weights, trial budget, and refresh settings can change on resume. Geometry, netlist, placement-group or signal-bundle definitions require a new run. Worker counts can change on resume; workers that change roles/slots initialize from their new assignment, while compatible workers retain state.

## Pause, save, quit

P pauses after in-flight bounded work, R resumes, S saves and forces exports, Q saves and quits. Ctrl+C once requests a safe stop; wait for 'Search stopped safely'. A second interrupt forces termination and retains the last durable files.

From another terminal, include the same --run for a named experiment:

```powershell
python optimize_alu.py --control pause
python optimize_alu.py --control save
python optimize_alu.py --control resume
python optimize_alu.py --control quit
```

There is no default time limit. For an optional bounded run, use `--seconds 3600` or `--max-candidates 10000`. Prevent the computer from sleeping during a long run.

## Checkpoints, archive and recovery

- `checkpoints/best.json`: overall best by finish merit, with versioned best_*.json backups.
- `portfolio/state.json` and `portfolio/state-backup.json`: checksummed portfolio state, generations and evaluated counts. A valid backup recovers a corrupt current state. If both are invalid the program stops rather than silently discarding the portfolio.
- `layouts/layout-N/checkpoints/best.json`: independent checkpoint for each active layout.
- `workers/worker_N.state.json`: current exploration/routing state, local best, RNG, counters and partial scout trial.
- `portfolio/archive/`: retired active layouts, including their checkpoint and SVG.
- `portfolio/evaluated/`: completed scout trials retained as checksummed candidate files, including non-admitted alternatives.
- `portfolio/status.json`: compact current layout telemetry.

Retired layouts and evaluated trial archives are not automatically deleted. Keep ordinary backups; interrupted work since the last durable save can be lost. To export a retired active layout, its folder already contains best.svg. Active layouts can also be exported through `--run runs/alu/layouts/layout-1 --export-svg --output exports/layout-1-review` while using this release's matching config.

Global best is monotonic by its merit rank; unresolved count itself may rise when appearance or remaining-work estimates improve. A slot's current-best rank improves within a generation, but replacing it starts a new generation. Retired generations remain archived.

## Telemetry and feedback

The dashboard lists all layout IDs/generations, open sections, finish merit, normalized bundle exposure, group spread, assigned worker IDs, evaluation/grace counts, progress and time since improvement. Worker rows show routing versus scouting, assigned layout or trial ID, and remaining trial budget. The plain output also prints layout summaries.

```powershell
python optimize_alu.py --export-diagnostics --output feedback.zip
```

Diagnostics include the four layout checkpoints, validation/unfinished-connection data, portfolio state, worker/trial counters and recent logs. SVGs themselves remain outside the compact feedback ZIP: send selected layout SVGs separately when useful. Worker profiling remains available with `--profile`.

## Verification

```powershell
python -m unittest discover -s tests -v
python tests/integration_smoke.py
python tests/portfolio_smoke.py
python tests/interrupt_smoke.py
```

The package includes 38 passing unit tests, bounded lifecycle checks, and full ALU/flag validation. No overnight optimization or new worker-throughput benchmark was run. The historical benchmark files predate v0.4 and are not performance predictions. This release has no promise of a completed board or faster candidates/sec; the aim is to explore useful alternatives more deliberately.
