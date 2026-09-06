# Local perfboard optimizer

A CPU multiprocessing placement and routing optimizer for your ALU. It includes your component artwork, the migrated netlist, the original 13-unresolved seed, and a validated 12-unresolved checkpoint found during short software tests. **The supplied ALU is still INCOMPLETE.** No hours-long optimization was performed.

## Quick Start — Windows PowerShell

Extract the entire ZIP to a writable folder. Open that folder in Terminal/PowerShell. Install 64-bit Python 3.11 or 3.12 if you do not already have it, then run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe optimize_alu.py --resume --workers 8
```

This resumes the included best checkpoint. Leave the terminal open. Press **P** to pause, **R** to resume, **S** to save now, or **Q** to save and quit. **Ctrl+C once** also saves and quits. Wait for “Search stopped safely” before closing the terminal.

Commands below use `python` for readability. Substitute `.\.venv\Scripts\python.exe` if your terminal has not activated the virtual environment. No environment activation or PowerShell execution-policy change is required with the explicit path.

## Everyday operation

Continue the default run for as long as you wish:

```powershell
python optimize_alu.py --resume --workers 8
```

Resume is also the default if you omit `--resume`. On startup the program shows the checkpoint path, previous score, accumulated scored-candidate count/search time, worker count, seed, and search strategy. All default paths are relative to the program's folder, not your terminal's current directory.

Start a separate search history from the original migrated 13-unresolved seed:

```powershell
python optimize_alu.py --fresh --run runs/experiment-01 --workers 8
```

`--fresh` requires a new or empty directory. It never deletes an existing run. Change the directory name for another experiment. Starting from good existing wiring is the normal workflow. If you specifically want configured component placement with no routed wires:

```powershell
python optimize_alu.py --fresh --blank-routing --run runs/blank-01 --workers 8
```

Choose worker count, dashboard rate, and diagnostic detail:

```powershell
python optimize_alu.py --resume --workers 4 --refresh-rate 5 --verbosity normal
python optimize_alu.py --resume --workers 8 --refresh-rate 3 --verbosity verbose
python optimize_alu.py --resume --workers 12 --refresh-rate 5 --verbosity trace
```

Stop the current process before starting another optimizer on the same run. An OS lock prevents concurrent writers; it releases automatically after a crash. Different run directories can be optimized independently. Changing worker count is supported: retained worker IDs restore their RNG/state, additional IDs begin from the global best, and unused worker files remain available for later sessions.

The bundled short benchmark recommends **12 workers** if `--workers` is omitted. **8 is a useful explicit starting choice while also using the PC.** Four workers use fewer resources. The samples measured throughput and process memory, not hardware cache misses or steady-state scalability; see TESTING.md. Re-measure locally before choosing your long-run setting:

```powershell
python optimize_alu.py --benchmark --benchmark-seconds 15
```

This runs separate short 4/8/12/16-worker trials and saves `benchmarks/recommendation.json`. It does not alter your main run. The automatic recommendation is the smallest count within 10% of the measured peak candidate throughput. Benchmark duration is per trial; startup, validation, and graceful shutdown add time. The GPU is unused.

## Pause, stop, and recovery

| Action | In the optimizer terminal | From a second terminal |
|---|---|---|
| Pause | P | `python optimize_alu.py --control pause` |
| Resume a paused process | R | `python optimize_alu.py --control resume` |
| Save immediately | S | `python optimize_alu.py --control save` |
| Save and quit | Q or Ctrl+C once | `python optimize_alu.py --control quit` |

For another run, add its directory, for example `--run runs/experiment-01`, to every control/validation/export command. Control requests are acknowledged by the running process; “request written” alone does not mean the action has finished. Send one command and wait for acknowledgment before another. Stale requests from a previous session are ignored.

Pause finishes and scores current candidates, writes worker states, and only then displays **paused (all workers checkpointed)**. Search counters stop advancing while paused. Resume keeps the processes and state in memory. On Windows the hotkeys require no Enter; on Unix terminals press Enter. If terminal hotkeys are unavailable, use the second-terminal commands.

Stop follows the same candidate-boundary approach. Routing checks stop requests regularly; the remaining scoring/checkpoint work may take a few seconds. A second Ctrl+C requests forced shutdown, retaining durable checkpoints but potentially losing the latest unsaved worker exploration. Closing the window or Task Manager termination is an unexpected stop, not the normal workflow.

After a crash or power failure, run the same resume command. Checkpoints have SHA-256 checksums and are written with temporary files, flush/fsync, and atomic replacement. Each new best first gets its own versioned archive, then updates `best.json`. Recovery examines the current best, retained best archives, and durable worker best proposals, rejects corrupt/physically invalid files, and selects the best valid candidate. If none survives, it reports recovery warnings and falls back to the configured seed. Keep periodic backups of the whole run folder against drive failure; atomic writes cannot protect against a failed drive.

Worker RNG and congestion history are saved every 30 seconds and at pause/stop. Global runtime counters are saved every 10 seconds and at best/save/stop events. After an abrupt crash the last few seconds of telemetry or unfinished exploration may be absent; already durable bests remain recoverable. Wall-time budgets and asynchronous scheduling mean resumed runs are not bit-for-bit deterministic. A worker failure safely stops the group and reports the error; restart with `--resume` after reviewing it.

## Overnight or multi-day runs

There is no default duration limit. Prevent Windows from sleeping while you want computation to continue, leave the terminal open, and use Q/Ctrl+C when you need the computer back. Pausing or stopping is normal and does not reset the search.

An optional timed session:

```powershell
python optimize_alu.py --resume --workers 8 --seconds 28800
```

This requests a stop after eight hours, then completes safe shutdown. It does not shut down Windows. To redirect console events instead of displaying the dashboard:

```powershell
python optimize_alu.py --resume --workers 8 --plain > terminal-session.txt
```

JSONL logs still contain diagnostic data in plain mode. Leave enough disk space for checkpoints and logs; their retention limits are described below.

## Inspecting, validating, and exporting

The optimizer also keeps a visual history in `runs/alu/exports/snapshots/`: one SVG at startup/resume, every five new-best checkpoints, and whenever you press **S** (or use `--control save`). Filenames include a UTC timestamp, checkpoint number, and unresolved count. The latest 40 snapshots are retained. `exports/best.svg` still updates on every new best. To change the interval or retention, add `"svg_snapshot_every": 5` and `"svg_snapshot_retention": 40` under `search` in your config; both must be positive integers. Existing configs work without adding these fields. Copying snapshots adds no placement/routing work.

While running, open `runs/alu/exports/best.svg` in Illustrator or a browser. It updates only when the global best improves, or when initially missing. The SVG contains editable vector components and wires, reference IDs, and net information. Save an Illustrator `.ai` copy through Illustrator if wanted; this tool exports SVG, not Illustrator's private native format. Reopen the SVG to see a later update.

The accompanying `connections.csv` is the authoritative physical connector/pin assignment after permutations. Never infer bit identity from connector position. Underneath power and constant ties are listed there; they are not top-side routed wires.

Validate without launching search:

```powershell
python optimize_alu.py --validate
```

This checks geometry, all required connections, protected escapes, canonical netlist equivalence, 524,288 ALU input/control combinations, and 8,192 flag-register/selector cases. The report goes into `runs/alu/reports/`.

| Exit code | Meaning |
|---|---|
| 0 | Complete and valid |
| 3 | Valid logic/physical constraints, but disconnected sections remain |
| 2 | Invalid input, invalid candidate, or command error |
| 1 | Search stopped after a worker failure |

**Exit code 3 is expected for the supplied ALU.** Read `status` and `complete` in the validation JSON. Complete requires zero disconnected sections and zero hard violations, with the logical checks passing. A visually convincing SVG does not imply completeness. The validator models connectivity and geometry; it does not model TTL propagation delays, power integrity, or manufacturing tolerances.

Export a separate review copy without searching:

```powershell
python optimize_alu.py --export-svg --output review-copy
```

This writes `best.svg`, candidate `best.json`, `validation.json`, `connections.csv`, and an export marker in `review-copy`. Without `--output`, it uses the run's `manual-export` directory. Manual SVG export checks physical/canonical validity; use `--validate` for an explicit full exhaustive report. Export JSON is a review artifact, not the checksummed resume envelope. The checkpoint is the source of truth; exports can always be regenerated. Export files are individually replaced, with `export-complete.json` written last, so a crash during export can leave an older/newer mixture until regenerated.

## Dashboard and counters

Rich displays an in-place colored dashboard, normally five updates/second. It shows accumulated search time, **fully scored candidate board states**, rolling candidates/sec and route attempts/sec, best unresolved/length/bends/crossings/visual cost, accepted/rejected/hard-invalid counts, checkpoint time, pause state, and recent important events. A new best highlights the candidate counter green.

The secondary table shows each worker's activity, candidate count/rate, plateau level, cumulative CPU seconds, and reported resident memory. Phase percentages describe summed worker work, not percentages of total system CPU. RSS sums include duplicated/shared pages and are not unique physical RAM usage. Rates are approximate rolling telemetry; the candidate counter increments only after mutation, bounded repair, and scoring finish. Internal A* expansions are never counted as candidates. Some candidates are fast rejected placements, so high candidates/sec alone is not proof of useful progress.

Telemetry is coarse (at most four worker updates/second); workers do not synchronize per route expansion. Rendering/export and coordinator validation can briefly delay a screen refresh. Redirected output automatically uses plain events. Install Rich for the intended display; the code also has a pip-vendored Rich fallback and a minimal ANSI fallback.

Normal logs include compact candidate outcomes and important events. Verbose also prints strategy changes in plain mode; trace adds per-candidate errors, unresolved nets, and congestion hot spots. Avoid leaving trace enabled indefinitely unless investigating a problem.

## Files, checkpoints, and diagnostics

```text
optimize_alu.py             Command-line entry point
config/alu.json             Board, netlist, constraints, groups, search settings
config/alu-seed.json        Original imported 13-unresolved candidate
assets/                    Your component artwork, self-contained SVGs
perfopt/                   Geometry, logic, router, workers, storage, UI, export
runs/alu/
  checkpoints/best.json    Checksummed best resume checkpoint
  checkpoints/best_*.json  Most recent 40 global-best archives
  workers/*.state.json     Worker RNG/current layout/congestion history
  workers/*.best.json      Durable worker best proposals
  runtime.json             Accumulated counters/search time
  config-used.json          Board definition used for this run
  settings.json             Latest session CLI settings
  exports/                  Automatic best SVG/JSON/CSV/validation
  reports/                  Explicit exhaustive validation reports
  logs/events.jsonl         Coordinator events
  logs/worker_*.jsonl       Scored-candidate history and worker events
  logs/best-history.jsonl   Compact global-best convergence history
  summaries/                Ten-minute diagnostic snapshots; latest 144
  profiles/                 Optional worker cProfile files
  last-session.json         Short performance/session report
```

Worker/event logs rotate at 20 MiB with three compressed backups per file. Best history rotates at 500 MiB with one backup. Checkpoint retention is configurable; summaries retain about a day at the default interval. Reports, manually created exports, diagnostic ZIPs, and separate benchmark run folders accumulate only when you explicitly create them. Archive/remove those manually when no longer needed. Do not delete active checkpoint files.

Package feedback for the next optimizer revision:

```powershell
python optimize_alu.py --export-diagnostics
python optimize_alu.py --export-diagnostics --output feedback.zip
```

The bundle includes the current best checkpoint, configuration/settings, runtime/session report, current validation/connection list, the latest 12 summaries, compact worker diagnostics, and the last 1 MiB of each current JSONL log. A manifest records file sizes/checksums. SVG artwork, full worker candidate copies, old archives, and huge intermediate data are omitted. Logs are intentionally tails; send rotated logs separately if we need an older plateau. Pause/save first for a stable snapshot, or export while running for a near-current view.

JSONL schema version 1 uses `timestamp` in UTC, `event`, and event-specific fields. Candidate records contain worker/seed, candidate count, mutation parameters and affected components, acceptance reason, score, route attempts/failure counts, phase timing, and plateau level. Trace includes unresolved nets and hot spots. Best-history records link score improvements to total candidates, search time, archive name, and export duration. Summaries aggregate mutation acceptance, route failures, worker activity, rates, and congestion history. This supports comparing algorithms across long runs without relying on screenshots.

## How search works and how to tune it

Each process has independent placement, routes, RNG, and congestion history. Workers mutate a good layout, retain unaffected wiring, remove newly illegal/dangling sections, run bounded A*, and try negotiated rip-up of obstructing wires. Strict routing reserves part of the attempt budget for negotiated repair. Candidates with hard violations are scored for diagnostics but never accepted or published. A coordinator validates proposals and atomically publishes the best; workers occasionally adopt it instead of synchronizing every iteration.

Placement moves, rotations, connector rail moves/order swaps, equivalent gate/mux channel swaps, commutative input swaps, group translations, and wire rip-up are available. Logical transformations rerun exhaustive ALU checks. Pure placement/routing uses canonical equivalence plus physical/connectivity validation. Larger mutation radii, altered probabilities, congestion-history decay, and elite restarts diversify plateaued workers. There is no guarantee a heuristic search will reach a complete or optimal board.

Global ranking is lexicographic: disconnected sections, hard violations, escape violations, weighted visual/routing cost, wire length, bends. Only hard-valid states enter the best pool. The visual cost combines group compactness, foreign-group wires, internal wires leaving their group, connector distance, dataflow, repeated-nibble alignment, length, bends, and crossings. Grouping can outweigh modest wire savings. These costs guide acceptance; they do not guarantee a particular visual style.

Edit `weights` and `search` in `config/alu.json` between sessions, then resume. Existing layouts are rescored. Other changes to the board/constraints/groups/netlist require a new run directory to prevent mixing incompatible checkpoints. See CONFIGURATION.md for schema details and extension limits.

Examples of bounded tuning overrides:

```powershell
python optimize_alu.py --resume --workers 8 --candidate-seconds 2 --plateau-seconds 180 --plateau-candidates 300 --summary-seconds 600
```

Increase `candidate_seconds`/`max_astar_nodes` if logs show frequent `search_budget` failures. Increase `max_route_attempts` if candidates hit the repair cap with time to spare. If almost all placement mutations are hard-invalid, reduce their probabilities or emphasize channel/routing changes. If unrelated group crossings dominate, increase `foreign_group_wire`; increase `symmetry` for repeated structure. Compare improvements per hour and diagnostics, not candidate rate alone. Keep the hard escape/body rules intact.

## Short tests and profiling

```powershell
python -m unittest discover -s tests -v
python tests/integration_smoke.py
python tests/interrupt_smoke.py
python optimize_alu.py --fresh --run runs/sanity-01 --workers 2 --max-candidates 6 --plain
python optimize_alu.py --resume --run runs/sanity-01 --workers 2 --max-candidates 2 --profile --plain
python -m pstats runs/sanity-01/profiles/worker_0.pstats
python optimize_alu.py --help
```

At the pstats prompt type `sort cumulative`, then `stats 20`, then `quit`. Profiles are opt-in and add overhead. The smoke tests use temporary directories and short candidate/time limits. The SIGINT test exercises the actual interrupt handler programmatically rather than synthesizing a keyboard press. Test searches may finish a small amount of scoring/checkpoint work after their time limit; they do not continue searching indefinitely.

Dependencies are NumPy, Rich, and optional-for-functionality psutil (installed by requirements for memory reporting). The package uses only Python's standard library otherwise; no Illustrator installation, Logisim process, network service, API key, GPU toolkit, or cloud session is needed at runtime.
