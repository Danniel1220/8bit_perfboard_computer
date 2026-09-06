"""Coarse-grained multiprocessing worker: no shared A* or grid state."""
from __future__ import annotations
from collections import Counter
import copy
import json
import math
import os
from pathlib import Path
import queue
import random
import signal
import time
import traceback
from .model import Geometry
from .search import mutate,evaluate,score,validate_candidate
from .storage import JsonLog,write_checkpoint,read_checkpoint,tuples


def memory_bytes():
    try:
        import psutil
        return psutil.Process().memory_info().rss
    except ImportError:
        if os.name=='nt':
            try:
                import ctypes
                from ctypes import wintypes
                class Counters(ctypes.Structure):
                    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
                c=Counters();c.cb=ctypes.sizeof(c)
                handle=ctypes.c_void_p(-1)
                if ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(c),c.cb):return c.WorkingSetSize
            except Exception:pass
        else:
            try:
                import resource
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if os.uname().sysname=='Darwin' else 1024)
            except Exception:pass
    return None


def run_worker(config,starting,run_dir,worker_id,seed,outbox,inbox,stop,pause,settings):
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    if hasattr(signal,'SIGBREAK'):signal.signal(signal.SIGBREAK,signal.SIG_IGN)
    run=Path(run_dir);log=JsonLog(run/'logs'/f'worker_{worker_id}.jsonl')
    profiler=None
    if settings.get('profile'):
        import cProfile
        profiler=cProfile.Profile();profiler.enable()
    rng=random.Random(seed);current=copy.deepcopy(starting['candidate']);best=copy.deepcopy(current)
    metrics=score(config,current);best_rank=tuple(metrics['rank']);global_rank=tuple(starting['metrics']['rank'])
    history={};lifetime=0
    state_path=run/'workers'/f'worker_{worker_id}.state.json'
    try:
        saved=read_checkpoint(state_path,config)
        report=validate_candidate(config,saved['candidate'])
        if not report['metrics']['hard_violations']:
            current=saved['candidate'];metrics=report['metrics'];best=copy.deepcopy(current);best_rank=tuple(metrics['rank'])
            rng.setstate(tuples(saved['rng_state']));history={(n,p):v for n,p,v in saved.get('history',[])};lifetime=saved.get('lifetime_candidates',0)
    except (OSError,ValueError,KeyError):pass
    stats={'worker':worker_id,'pid':os.getpid(),'seed':seed,'candidates':0,'accepted':0,'rejected':0,'route_attempts':0,'expansions':0,'invalid':0,'restarts':0,'phase_seconds':Counter(),'mutation_counts':Counter(),'mutation_accepted':Counter(),'route_failures':Counter()}
    start=time.perf_counter();last_pulse=last_save=last_improvement=last_adopt=start;last_improvement_count=0;activity='starting';old_level=-1;paused=False;pending=None;last_proposal=None
    quota=settings.get('quota');geometry=Geometry(config,current)
    def send(kind,**payload):
        try:outbox.put_nowait({'kind':kind,'worker':worker_id,**payload})
        except queue.Full:
            if kind not in ('telemetry',):outbox.put({'kind':kind,'worker':worker_id,**payload},timeout=5)
    def pulse(what=None,force=False):
        nonlocal last_pulse,activity
        if what:activity=what
        now=time.perf_counter()
        if force or now-last_pulse>=0.25:
            send('telemetry',stats={**stats,'phase_seconds':dict(stats['phase_seconds']),'mutation_counts':dict(stats['mutation_counts']),'mutation_accepted':dict(stats['mutation_accepted']),'route_failures':dict(stats['route_failures']),'activity':activity,'elapsed':now-start,'cpu_seconds':time.process_time(),'memory_bytes':memory_bytes(),'rank':metrics['rank'],'plateau':max(old_level,0),'history_cells':len(history)})
            last_pulse=now
    def payload(candidate,rank_metrics):
        return {'schema_version':1,'structure_hash':config['_structure_hash'],'candidate':candidate,'metrics':rank_metrics,'rng_state':rng.getstate(),'history':[[n,p,v] for (n,p),v in list(history.items())[-4096:]],'worker':worker_id,'seed':seed,'lifetime_candidates':lifetime+stats['candidates'],'stats':{**stats,'phase_seconds':dict(stats['phase_seconds'])}}
    def save_state(reason):
        write_checkpoint(state_path,payload(current,metrics));log.write('worker_checkpoint',worker=worker_id,reason=reason,candidates=stats['candidates'])
    try:
        log.write('worker_started',worker=worker_id,seed=seed,pid=os.getpid(),quota=quota)
        while not stop.is_set() and (quota is None or stats['candidates']<quota):
            while True:
                try:message=inbox.get_nowait()
                except queue.Empty:break
                if message['kind']=='best':global_rank=tuple(message['rank']);pending=message['path']
                elif message['kind']=='save':save_state('requested');send('saved')
            if pause.is_set():
                if not paused:save_state('pause');paused=True;send('paused')
                pulse('paused');time.sleep(.05);continue
            if paused:paused=False;send('resumed')
            now=time.perf_counter()
            level=min(3,max(int((now-last_improvement)/config['search']['plateau_seconds']),int((stats['candidates']-last_improvement_count)/config['search']['plateau_candidates'])))
            if level!=old_level:
                old_level=level;log.write('strategy',worker=worker_id,plateau=level,strategy='local placement + rip-up' if not level else 'wider placement + channel diversification',candidates=stats['candidates']);send('strategy',level=level)
            if pending and now-last_adopt>=config['search']['adopt_seconds']:
                try:
                    adopted=read_checkpoint(pending,config)
                    if tuple(adopted['metrics']['rank'])<tuple(metrics['rank']):
                        current=copy.deepcopy(adopted['candidate']);metrics=score(config,current);geometry=Geometry(config,current);stats['restarts']+=1
                        log.write('adopt_global',worker=worker_id,rank=metrics['rank'])
                except (OSError,ValueError,KeyError):pass
                pending=None;last_adopt=now
            if level>=2 and rng.random()<0.025:
                # Elite restart, never a compulsory blank-board restart.
                elites=sorted((run/'checkpoints').glob('best_*.json'))[-10:]
                source=rng.choice(elites) if elites and rng.random()<.5 else None
                try:restart=read_checkpoint(source,config)['candidate'] if source else best
                except (OSError,ValueError,KeyError):restart=best
                current=copy.deepcopy(restart);metrics=score(config,current);geometry=Geometry(config,current)
                history={k:v*.5 for k,v in history.items()};stats['restarts']+=1;log.write('elite_restart',worker=worker_id,source=str(source or 'local-best'),radius=level)
            pulse('mutating')
            candidate,mutation,logical=mutate(config,current,rng,level)
            before=time.perf_counter()
            reuse=geometry if not mutation.get('components') else None
            candidate,result,router,times=evaluate(config,candidate,rng,history,stop,pulse,logical,reuse)
            # A candidate is counted only here: complete mutation + bounded repair + full score.
            stats['candidates']+=1;stats['route_attempts']+=router.attempts;stats['expansions']+=router.expansions
            stats['phase_seconds'].update(times);stats['route_failures'].update(router.failures);stats['mutation_counts'][mutation['type']]+=1
            history=router.history
            if len(history)>8192:history=dict(list(history.items())[-4096:])
            rank=tuple(result['rank']);valid=result['hard_violations']==0
            # Hard-invalid states are diagnosed but never accepted or published.
            improvement=valid and rank<tuple(metrics['rank'])
            temperature=1+level
            accept=valid and (improvement or result['disconnected']<=metrics['disconnected']+2+level and rng.random()<0.025*temperature)
            if accept:
                current=candidate;metrics=result;geometry=router.g;stats['accepted']+=1;stats['mutation_accepted'][mutation['type']]+=1
            else:stats['rejected']+=1
            if not valid:stats['invalid']+=1
            reason='hard_constraint' if not valid else 'improved_local' if improvement else 'exploration' if accept else 'score_rejected'
            if valid and rank<best_rank:
                best=copy.deepcopy(candidate);best_rank=rank;last_improvement=time.perf_counter();last_improvement_count=stats['candidates']
            if valid and rank<global_rank and (last_proposal is None or rank<last_proposal):
                proposal=run/'workers'/f'worker_{worker_id}.best.json'
                write_checkpoint(proposal,payload(candidate,result));send('best',path=str(proposal),rank=result['rank']);last_proposal=rank
            log.write('candidate',worker=worker_id,seed=seed,candidate=stats['candidates'],mutation=mutation,accepted=accept,reason=reason,score=result['rank'],disconnected=result['disconnected'],hard_violations=result['hard_violations'],wire_length=result['wire_length'],bends=result['bends'],congestion=result['congestion'],route_attempts=router.attempts,route_failures=dict(router.failures),phase_seconds=times,elapsed_seconds=time.perf_counter()-before,seconds_since_improvement=time.perf_counter()-last_improvement,plateau=level,**({'errors':result['errors'],'unresolved_nets':result['unresolved_nets'],'hotspots':[[n,p,v] for (n,p),v in sorted(history.items(),key=lambda x:-x[1])[:12]]} if settings['verbosity']=='trace' else {}))
            if time.perf_counter()-last_save>=config['search']['worker_state_seconds']:
                save_state('periodic');last_save=time.perf_counter()
            pulse('searching')
        save_state('stop');pulse('stopped',True);send('done')
    except BaseException:
        error=traceback.format_exc();log.write('fatal',worker=worker_id,error=error)
        try:save_state('error')
        except Exception:pass
        send('error',error=error)
    finally:
        if profiler:
            profiler.disable();(run/'profiles').mkdir(exist_ok=True)
            profiler.dump_stats(str(run/'profiles'/f'worker_{worker_id}.pstats'))
        log.close()
