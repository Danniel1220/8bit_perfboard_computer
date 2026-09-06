"""One candidate with an intentionally undrained full IPC queue."""
from pathlib import Path
import multiprocessing as mp
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from perfopt.model import load_config,load_seed
from perfopt.search import score
from perfopt.worker import run_worker
from perfopt.storage import read_checkpoint
import json

if __name__=='__main__':
    c=load_config(ROOT/'config/alu.json');c['search'].update(candidate_seconds=.025,max_astar_nodes=512,max_route_attempts=1)
    candidate=load_seed(c);best={'candidate':candidate,'metrics':score(c,candidate)}
    with tempfile.TemporaryDirectory(prefix='perfopt-full-queue-') as folder:
        ctx=mp.get_context('spawn');outbox=ctx.Queue(maxsize=1);inbox=ctx.Queue();stop=ctx.Event();pause=ctx.Event()
        outbox.put({'occupied':True})
        p=ctx.Process(target=run_worker,args=(c,best,folder,0,173688151,outbox,inbox,stop,pause,{'quota':1,'verbosity':'normal','session_id':'queue-test'}))
        p.start();p.join(8)
        try:
            assert not p.is_alive(),'Worker hung on a full queue'
            assert p.exitcode==0,p.exitcode
            state=read_checkpoint(Path(folder)/'workers/worker_0.state.json',c)
            assert state['stats']['candidates']==1
            assert state['stats']['dropped_notifications']>0
            assert json.loads((Path(folder)/'workers/worker_0.status.json').read_text())['kind']=='done'
            print('PASS: worker scored one candidate and exited cleanly with a permanently full queue; durable state/status survived.')
        finally:
            if p.is_alive():stop.set();p.terminate();p.join(2)
            outbox.close();outbox.cancel_join_thread();inbox.close();inbox.cancel_join_thread()
