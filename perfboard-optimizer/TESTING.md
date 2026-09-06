# Delivery verification

The included `runs/alu/checkpoints/best.json` is the existing validated candidate, preserved without replacing or optimizing it during final packaging.

| Result | Value |
|---|---:|
| Disconnected sections | 12 |
| Hard physical violations | 0 |
| Protected pin-escape violations | 0 |
| Unique net wire edges | 6,488 |
| Bends | 467 |
| Combinational ALU cases passed | 524,288 |
| Flag register/selector cases passed | 8,192 |
| Completion status | INCOMPLETE |

The full saved validation result is `runs/alu/reports/delivery-validation.json`. The original imported 13-unresolved seed remains in `config/alu-seed.json`. No final packaging search was performed, and no better layout was sought.

## Checks completed before packaging

- Exhaustive ALU and flag validation of the included checkpoint.
- Two-worker execution with a small fixed candidate count.
- Resume with preserved cumulative counters.
- True pause: both workers checkpointed and candidate counts remained stationary.
- Save, resume, and clean quit via control commands.
- Recovery after deliberately corrupting the current-best checkpoint.
- Run-directory collision protection.
- SIGINT handler saved best/worker state and a subsequent resume succeeded.
- Twelve-worker save and subsequent resume, following the numeric worker-ID checksum fix.
- Manual SVG export, diagnostic ZIP export, help, and validation commands.
- A separate small connector-board example validated COMPLETE.
- Fresh blank-routing initialization with zero candidate evaluations.

The main regression suite covers the original seed, exhaustive behavior, invalid arithmetic bit swaps, pin escapes, underneath clearance reservations, missing pin stubs, placement/body constraints, all mutation families, checkpoint integrity, numeric worker IDs 0–15, integer wire nodes, negotiated repair budgeting, generic board reuse, SVG export, and dashboard rendering.

A late additional endpoint-crossing restriction failed the original-seed tests immediately before interruption. Final packaging removed only that unvalidated addition, restoring the previously tested crossing rules. Active two-cell pin escapes, body clearance, orthogonal crossing/overlap checks, and the validated 12-unresolved candidate were retained. Final packaging uses lightweight physical/integrity checks rather than repeating the exhaustive truth-table runs.

## Short performance samples already completed

| Workers | Scored candidates/sec | Reported worker RSS total, MiB |
|---:|---:|---:|
| 4 | 10.76 | 219.9 |
| 8 | 14.90 | 423.9 |
| 12 | 16.58 | 626.7 |
| 16 | 15.15 | 778.5 |

Each trial requested a three-second session, plus startup and safe shutdown. These are short development samples, not a steady-state hardware benchmark. Startup/export timing and fast rejected placements affect the numbers. The bundled automatic recommendation is 12, using the smallest count within 10% of the measured peak. The guide suggests explicitly starting with 8 while using the computer interactively. No benchmarks were repeated during final packaging.

An earlier profile identified A* Python dictionary traffic as a major cost. The existing implementation uses integer grid indices, compact search-state arrays, precomputed neighbors, and per-search foreign-net masks. Subsequent routing-budget and persistence fixes are covered by regression checks; these samples are guidance, not a promised production rate. No GPU work was undertaken.

## Repeating checks locally

```powershell
python -m unittest discover -s tests -v
python tests/integration_smoke.py
python tests/interrupt_smoke.py
python optimize_alu.py --validate
```

The last command returns **3** while this board remains incomplete. The tests use temporary directories; they do not replace the included checkpoint. Integration/interrupt tests perform only bounded short software smoke runs. The final ZIP also contains `MANIFEST.json`, with SHA-256 hashes for every other packaged file, for verifying extraction or transfer.

The saved SVG was rasterized and visually reviewed during delivery. It is an editable review artifact, not a claim that the incomplete board can yet be built as a fully connected ALU. Runtime requires only the dependencies in `requirements.txt`; the SVG rasterizer used for this review is not a runtime dependency.

## Final packaging checks

Eleven lightweight regression checks passed. New-run startup and resume were exercised with two workers and a zero-candidate quota. A real worker started paused, acknowledged save, and quit with zero evaluated candidates. Manual SVG and diagnostics exports passed. These lifecycle checks reused the previously confirmed functional results in the test harness, guarded by exact candidate hashes; production validation code was not bypassed or changed. No exhaustive ALU rerun, new benchmark, or placement/routing search occurred during final packaging.

The included checkpoint remained byte-for-byte unchanged, SHA-256:

```text
8161a99aaa28b35bc0f408c4aea78f65325399ad55fb4ded5f7ab5a499b6d691
```
