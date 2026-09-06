"""Bounded explorer worker save/resume test; no long search."""
from pathlib import Path
import multiprocessing as mp
import json
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from perfopt.model import load_config,load_seed
from perfopt.search import score,validate_candidate
from perfopt.worker import run_worker
from perfopt.storage import read_checkpoint


if __name__=='__main__':
    c=load_config(ROOT/'config/alu.json')
    c['search'].update(candidate_seconds=.025,max_astar_nodes=512,max_route_attempts=1,
        exploration_interval_candidates=1,exploration_initial_candidates=1,exploration_grace_candidates=20,placement_restart_attempts=100)
    candidate=load_seed(c);best={'candidate':candidate,'metrics':score(c,candidate)}
    with tempfile.TemporaryDirectory(prefix='perfopt-v3-explorer-') as folder:
        ctx=mp.get_context('spawn')
        def session(quota):
            outbox=ctx.Queue();inbox=ctx.Queue();stop=ctx.Event();pause=ctx.Event()
            p=ctx.Process(target=run_worker,args=(c,best,folder,2,1,outbox,inbox,stop,pause,{'quota':quota,'verbosity':'normal','session_id':'explorer-test'}))
            p.start();p.join(12)
            try:
                assert not p.is_alive() and p.exitcode==0
                status=json.loads((Path(folder)/'workers/worker_2.status.json').read_text())
                assert status['kind']=='done',status
                return read_checkpoint(Path(folder)/'workers/worker_2.state.json',c)
            finally:
                if p.is_alive():p.terminate();p.join(2)
                outbox.close();outbox.cancel_join_thread();inbox.close();inbox.cancel_join_thread()
        state=session(3)
        assert state['exploration_remaining']==18,state['exploration_remaining']
        assert state['candidate']['placements']!=candidate['placements']
        assert validate_candidate(c,state['candidate'])['metrics']['hard_violations']==0
        resumed=session(1)
        assert resumed['exploration_remaining']==17
        assert resumed['next_exploration']==state['next_exploration']
        print('PASS: explorer changes placement, retains protected routing budget, saves and resumes it; four candidates total.')
