"""Bounded process/control/recovery smoke test; no long optimization search.

Run from the package directory: python tests/integration_smoke.py
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from perfopt.storage import read_checkpoint


def main():
    with tempfile.TemporaryDirectory(prefix='perfopt-integration-') as temp:
        run=Path(temp)/'run'
        base=[sys.executable,str(ROOT/'optimize_alu.py'),'--run',str(run)]
        def command(*args,expected=0):
            result=subprocess.run(base+list(args),cwd=ROOT,capture_output=True,text=True,timeout=15)
            assert result.returncode==expected,(args,result.returncode,result.stdout,result.stderr)
            return result
        def wait_for(predicate,seconds=6):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                if predicate():return
                time.sleep(.05)
            raise AssertionError('Timed out waiting for control acknowledgement')
        def events(path):
            try:return [json.loads(line) for line in path.read_text().splitlines() if line]
            except (OSError,ValueError):return []
        log=Path(temp)/'stdout.txt'
        with log.open('w') as stream:
            p=subprocess.Popen(base+['--fresh','--workers','2','--seconds','9','--candidate-seconds','.12','--refresh-rate','10','--verbosity','trace','--plain'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            try:
                wait_for(lambda:any(e['event']=='workers_started' for e in events(run/'logs/events.jsonl')))
                command('--control','pause')
                wait_for(lambda:all(any(e['event']=='worker_checkpoint' and e.get('reason')=='pause' for e in events(run/f'logs/worker_{i}.jsonl')) for i in range(2)))
                counts=[sum(e['event']=='candidate' for e in events(run/f'logs/worker_{i}.jsonl')) for i in range(2)]
                time.sleep(.25)
                assert counts==[sum(e['event']=='candidate' for e in events(run/f'logs/worker_{i}.jsonl')) for i in range(2)]
                command('--control','save')
                wait_for(lambda:any(e['event']=='checkpoint' and e.get('reason')=='requested' for e in events(run/'logs/events.jsonl')))
                locked=command('--workers','1','--max-candidates','0',expected=2)
                assert 'already being optimized' in locked.stderr
                command('--control','resume')
                wait_for(lambda:any(e['event']=='resumed' for e in events(run/'logs/events.jsonl')))
                command('--control','quit')
                assert p.wait(timeout=10)==0,log.read_text()
            finally:
                if p.poll() is None:p.terminate();p.wait(timeout=5)
        before=read_checkpoint(run/'runtime.json')['total_candidates']
        assert len(list((run/'workers').glob('*.state.json')))==2
        # Simulate an interrupted/corrupt current-best write; recover an archive.
        (run/'checkpoints/best.json').write_text('{truncated')
        recovered=command('--resume','--workers','1','--max-candidates','1','--candidate-seconds','.05','--plain')
        assert 'Recovery warning:' in recovered.stdout
        assert read_checkpoint(run/'runtime.json')['total_candidates']==before+1
        command('--validate',expected=3)
        command('--export-svg','--output',str(Path(temp)/'manual'))
        bundle=Path(temp)/'diagnostics.zip'
        command('--export-diagnostics','--output',str(bundle))
        with zipfile.ZipFile(bundle) as z:
            assert 'manifest.json' in z.namelist() and 'checkpoints/best.json' in z.namelist()
        command('--help')
        assert (Path(temp)/'manual/best.svg').exists()
        print('PASS: two workers, true pause, save, run lock, resume, quit, corrupt-best recovery, counters, validation, SVG, diagnostics, help.')


if __name__=='__main__':main()
