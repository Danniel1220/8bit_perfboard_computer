# SVG history update

1. In the running optimizer, press **Q** and wait for **Search stopped safely**.
2. Extract `perfboard-svg-snapshot-update.zip` into your existing optimizer folder (the folder containing `optimize_alu.py`). Allow the included program/documentation files to be replaced.
3. Resume with your usual command, for example:

```powershell
.\.venv\Scripts\python.exe optimize_alu.py --resume --workers 12
```

If you use a custom `--run` directory, include that same directory when resuming.

The update ZIP contains no `runs/`, `config/`, or checkpoint files. Your current best, worker state, and settings are preserved.

SVG history is written to `runs/alu/exports/snapshots/` (or your custom run's `exports/snapshots/`):

- At startup/resume, to capture your current best.
- Every five new-best checkpoints.
- When you press **S** or use `--control save`.

The most recent 40 snapshots are retained. Filenames include UTC time, checkpoint number, and unresolved count. The current `exports/best.svg` continues to update for every improvement.

Optional: add `"svg_snapshot_every": 5` and `"svg_snapshot_retention": 40` to the `search` object in your existing config to change the defaults. Both values must be positive integers. No configuration edits are required to use this update.
