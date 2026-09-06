"""Exercise the actual SIGINT handler with a two-second bounded worker session."""
from pathlib import Path
import signal
import sys
import tempfile
import threading
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from optimize_alu import main
from perfopt.storage import read_checkpoint

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='perfopt-interrupt-') as temp:
        timer=threading.Timer(2,lambda:signal.raise_signal(signal.SIGINT))
        timer.start()
        try:
            code=main(['--fresh','--run',temp,'--workers','1','--seconds','5','--candidate-seconds','.08','--plain'])
            assert code==0
            assert read_checkpoint(Path(temp)/'checkpoints/best.json')['metrics']['hard_violations']==0
            assert (Path(temp)/'workers/worker_0.state.json').exists()
            assert main(['--resume','--run',temp,'--workers','1','--max-candidates','0','--plain'])==0
            print('PASS: SIGINT saves best and worker state; subsequent resume succeeds.')
        finally:timer.cancel();timer.join()
