"""Bounded 12-worker portfolio lifecycle, including partial scout-trial resume."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from perfopt.storage import read_checkpoint


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='portfolio-smoke-') as folder:
        cfg=json.loads((ROOT/'config/alu.json').read_text(encoding='utf-8'))
        cfg['portfolio'].update(trial_candidates=6,svg_seconds=1)
        cfg['search'].update(candidate_seconds=.025,max_astar_nodes=512,max_route_attempts=1)
        handle=tempfile.NamedTemporaryFile(mode='w',suffix='.json',dir=ROOT/'config',delete=False,encoding='utf-8')
        try:
            json.dump(cfg,handle);handle.close()
            run=Path(folder)/'run';base=[sys.executable,str(ROOT/'optimize_alu.py'),'--config',handle.name,'--run',str(run)]
            def invoke(*args):
                result=subprocess.run(base+list(args),capture_output=True,text=True,cwd=ROOT,timeout=35)
                assert result.returncode==0,(result.stdout,result.stderr)
            invoke('--fresh','--blank-routing','--workers','12','--max-candidates','24','--plain')
            first={i:read_checkpoint(run/f'workers/worker_{i}.state.json') for i in range(8,12)}
            assert all(s['trial_evaluations']==2 for s in first.values())
            invoke('--resume','--workers','12','--max-candidates','12','--plain')
            second={i:read_checkpoint(run/f'workers/worker_{i}.state.json') for i in range(8,12)}
            assert all(second[i]['trial_id']==first[i]['trial_id'] and second[i]['trial_evaluations']==3 for i in first)
            invoke('--resume','--workers','12','--max-candidates','48','--plain')
            assert len(list((run/'portfolio/evaluated').glob('*.json')))>=4
            state=read_checkpoint(run/'portfolio/state.json')
            assert len(state['slots'])==4
            for i in range(4):
                assert (run/f'layouts/layout-{i+1}/exports/best.svg').exists()
                assert list((run/f'layouts/layout-{i+1}/exports/snapshots').glob('*.svg'))
            assert (run/'portfolio/live.html').exists()
            assert not json.loads((run/'last-session.json').read_text())['errors']
            bundle=Path(folder)/'feedback.zip';invoke('--export-diagnostics','--output',str(bundle))
            with zipfile.ZipFile(bundle) as z:
                assert 'portfolio/state.json' in z.namelist()
                assert sum(n.endswith('/exports/unfinished-connections.json') for n in z.namelist())==4
            print('PASS: 12 workers, four layout exports/snapshots, scout-trial resume and completion, durable portfolio, diagnostics; 84 candidates total.')
        finally:
            handle.close();Path(handle.name).unlink(missing_ok=True)
