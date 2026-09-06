"""Occasional immutable copies of the exported best SVG; no routing work."""
from pathlib import Path
import datetime as dt
import os
import uuid


def save_svg_snapshot(run,checkpoint_count,unresolved,*,new_best=False,force=False,every=5,retention=40):
    if type(every) is not int or every<1 or type(retention) is not int or retention<1:
        raise ValueError('svg_snapshot_every and svg_snapshot_retention must be positive integers')
    if not force and not(new_best and checkpoint_count%every==0):return None
    run=Path(run);folder=run/'exports/snapshots';folder.mkdir(parents=True,exist_ok=True)
    timestamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=folder/f'{timestamp}_best-{checkpoint_count:08d}_{unresolved}-unresolved.svg'
    temporary=folder/(target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('wb') as f:
            f.write((run/'exports/best.svg').read_bytes());f.flush();os.fsync(f.fileno())
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    for old in sorted(folder.glob('*_best-*_*-unresolved.svg'))[:-retention]:old.unlink()
    return target
