"""Persistent scouts and slot-local routing; best proposals are always durable."""
import copy
from collections import Counter
import json
from pathlib import Path
import queue
import random
import signal
import time
import traceback
import uuid
from .worker import memory_bytes
from .model import Geometry
from .search import mutate,evaluate,score,validate_candidate
from .exploration import diversify
from .storage import JsonLog,read_checkpoint,write_checkpoint,tuples
from .messaging import Mailbox
from .organization import distance


def run_portfolio_worker(config,starting,run_dir,worker_id,seed,outbox,inbox,stop,pause,settings):
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    if hasattr(signal,'SIGBREAK'):signal.signal(signal.SIGBREAK,signal.SIG_IGN)
    run=Path(run_dir);state_path=run/f'workers/worker_{worker_id}.state.json'
    log=JsonLog(run/f'logs/worker_{worker_id}.jsonl');rng=random.Random(seed)
    profiler=None
    if settings.get('profile'):
        import cProfile
        profiler=cProfile.Profile();profiler.enable()
    role=settings['role'];slot=settings['slot'];epoch=settings['epoch'];cfg=config['portfolio']
    current=copy.deepcopy(starting['candidate']);metrics=score(config,current);best=copy.deepcopy(current);bm=metrics
    trial_id=uuid.uuid4().hex;trial_count=0;baseline=metrics['disconnected'];layout_count=0;lifetime=0;history={};needs_trial=role=='scout'
    try:
        saved=read_checkpoint(state_path,config)
        if saved.get('role')==role and (role=='scout' or saved.get('slot')==slot and saved.get('epoch')==epoch):
            report=validate_candidate(config,saved['candidate'])
            if not report['metrics']['hard_violations']:
                current=saved['candidate'];metrics=report['metrics'];best=saved.get('local_best',current)
                br=validate_candidate(config,best)
                if br['metrics']['hard_violations']:raise ValueError('Invalid local best')
                bm=br['metrics'];trial_count=saved.get('trial_evaluations',0);layout_count=saved.get('layout_evaluations',0)
                trial_id=saved.get('trial_id',trial_id);baseline=saved.get('baseline_unresolved',baseline);needs_trial=saved.get('needs_trial',needs_trial)
                lifetime=saved.get('lifetime_candidates',0);rng.setstate(tuples(saved['rng_state']))
                history={(n,p):v for n,p,v in saved.get('history',[])}
    except (OSError,ValueError,KeyError):pass
    stats={'worker':worker_id,'role':role,'slot':slot,'epoch':epoch,'candidates':0,'accepted':0,'rejected':0,'invalid':0,'route_attempts':0,'restarts':0,'expansions':0,
           'phase_seconds':Counter(),'mutation_counts':Counter(),'mutation_accepted':Counter(),'route_failures':Counter()}
    mailbox=Mailbox(outbox,run,worker_id,settings['session_id']);start=last_pulse=last_save=last_assignment=time.monotonic();paused=False;last_rank=None
    local_config=copy.deepcopy(config)
    local_config['search']['mutation_weights']={k:v for k,v in config['search']['mutation_weights'].items() if k in ('route','connector_order','gate_channels','mux_channels','input_swap')}
    def send(kind,**kw):
        if not mailbox.send(kind,**kw):stats['dropped_notifications']=stats.get('dropped_notifications',0)+1
    def pulse(activity='routing',force=False):
        nonlocal last_pulse
        now=time.monotonic()
        if force or now-last_pulse>.25:
            send('telemetry',stats={**stats,'activity':activity,'elapsed':now-start,'cpu_seconds':time.process_time(),'memory_bytes':memory_bytes(),
                 'layout_id':f'L{slot+1}.{epoch}' if role=='router' else f'trial-{trial_id[:6]}','trial_remaining':max(0,cfg['trial_candidates']-trial_count) if role=='scout' else 0,
                 'rank':metrics['rank'],'unresolved':metrics['disconnected'],'bundle':metrics['organization'].get('bundle_separation',0)})
            last_pulse=now
    def payload(candidate,m):
        return {'schema_version':1,'structure_hash':config['_structure_hash'],'session_id':settings['session_id'],'candidate':candidate,'metrics':m,
                'worker':worker_id,'role':role,'slot':slot,'epoch':epoch,'rng_state':rng.getstate(),'seed':seed,'history':[[n,p,v] for (n,p),v in list(history.items())[-4096:]],
                'trial_id':trial_id,'trial_evaluations':trial_count,'layout_evaluations':layout_count,'baseline_unresolved':baseline,'needs_trial':needs_trial,
                'lifetime_candidates':lifetime+stats['candidates'],'local_best':best,'stats':stats}
    def propose():
        nonlocal last_rank
        p=payload(best,bm)
        if role=='router':write_checkpoint(run/f'workers/worker_{worker_id}.layout.json',p)
        if last_rank is None or tuple(bm['rank'])<last_rank:
            path=run/f'workers/worker_{worker_id}.best.json';write_checkpoint(path,p);send('best',path=str(path),rank=bm['rank']);last_rank=tuple(bm['rank'])
    def save(reason):
        propose();write_checkpoint(state_path,payload(current,metrics));log.write('worker_checkpoint',reason=reason,candidates=stats['candidates'])
    try:
        log.write('worker_started',role=role,slot=slot,epoch=epoch)
        while not stop.is_set() and (settings.get('quota') is None or stats['candidates']<settings['quota']):
            while True:
                try:message=inbox.get_nowait()
                except queue.Empty:break
                if message['kind']=='save':save('requested');send('saved')
                # Global-best broadcasts intentionally never collapse this portfolio.
            if pause.is_set():
                if not paused:save('pause');send('paused');paused=True
                pulse('paused');time.sleep(.05);continue
            if paused:send('resumed');paused=False
            now=time.monotonic()
            if role=='router' and now-last_assignment>=1:
                last_assignment=now
                try:
                    assignment=read_checkpoint(run/f'portfolio/assignments/worker_{worker_id}.json',config)
                    changed=assignment['epoch']!=epoch or assignment['slot']!=slot
                    if changed or tuple(assignment['best']['metrics']['rank'])<tuple(bm['rank']):
                        adopted=assignment['best'];report=validate_candidate(config,adopted['candidate'])
                        if report['metrics']['hard_violations']:raise ValueError('Invalid assignment')
                        current=copy.deepcopy(adopted['candidate']);metrics=report['metrics'];best=copy.deepcopy(current);bm=metrics;history={}
                        if changed:layout_count=0
                        epoch=assignment['epoch'];slot=assignment['slot'];stats.update(slot=slot,epoch=epoch)
                        log.write('layout_assigned',slot=slot,epoch=epoch)
                except (OSError,ValueError,KeyError):pass
            if role=='scout' and needs_trial:
                pulse('placing submodules',True);before=time.perf_counter()
                try:
                    slots=read_checkpoint(run/'portfolio/state.json',config)['slots'];base=rng.choice(slots)['best']['candidate']
                except (OSError,ValueError,KeyError):base=best;slots=[]
                alternative=None;detail={}
                for _ in range(3):
                    alternative,detail=diversify(config,base,rng,stop)
                    if alternative is not None and all(distance(config,alternative,s['best']['candidate'])>=cfg['diversity_cells'] for s in slots):break
                    if alternative is not None:base=alternative
                    alternative=None
                    if stop.is_set():break
                stats['phase_seconds']['placement_exploration']+=time.perf_counter()-before
                if alternative is not None:
                    current=alternative;metrics=score(config,current);best=copy.deepcopy(current);bm=metrics;history={}
                    trial_id=uuid.uuid4().hex;trial_count=0;baseline=metrics['disconnected'];needs_trial=False;stats['restarts']+=1
                    log.write('placement_exploration',trial_id=trial_id,mutation=detail)
                # Failed placement gets one bounded routing attempt before retrying.
            before=time.perf_counter()
            if rng.random()<.7:candidate=copy.deepcopy(current);mutation={'type':'route','components':[]};logical=False
            else:candidate,mutation,logical=mutate(local_config,current,rng,0)
            candidate,result,router,times=evaluate(config,candidate,rng,history,stop,pulse,logical)
            stats['candidates']+=1;layout_count+=1
            if role=='scout' and not needs_trial:trial_count+=1
            stats['phase_seconds'].update(times);stats['route_attempts']+=router.attempts;stats['expansions']+=router.expansions
            stats['route_failures'].update(router.failures);stats['mutation_counts'][mutation['type']]+=1;history=router.history
            if len(history)>8192:history=dict(list(history.items())[-4096:])
            valid=result['hard_violations']==0
            accept=valid and (tuple(result['rank'])<tuple(metrics['rank']) or rng.random()<.025)
            if accept:current=candidate;metrics=result;stats['accepted']+=1;stats['mutation_accepted'][mutation['type']]+=1
            else:stats['rejected']+=1
            if not valid:stats['invalid']+=1
            if valid and tuple(result['rank'])<tuple(bm['rank']):best=copy.deepcopy(candidate);bm=result;propose()
            if role=='scout' and not needs_trial and trial_count>=cfg['trial_candidates']:
                write_checkpoint(run/f'portfolio/proposals/{worker_id}-{trial_id}.json',payload(best,bm))
                log.write('trial_ready',trial_id=trial_id,evaluations=trial_count,unresolved=bm['disconnected'],finish_score=bm['finish_score'])
                needs_trial=True
            log.write('candidate',candidate=stats['candidates'],role=role,slot=slot,epoch=epoch,trial_id=trial_id,trial_evaluations=trial_count,
                      accepted=accept,score=result['rank'],unresolved=result['disconnected'],phase_seconds=times,elapsed_seconds=time.perf_counter()-before)
            if time.monotonic()-last_save>=config['search']['worker_state_seconds']:save('periodic');last_save=time.monotonic()
            pulse('scout: developing layout' if role=='scout' else 'routing assigned layout')
        save('stop');pulse('stopped',True);send('done')
    except BaseException:
        error=traceback.format_exc();log.write('fatal',error=error)
        try:save('error')
        except Exception:pass
        send('error',error=error)
    finally:
        if profiler:
            profiler.disable();(run/'profiles').mkdir(exist_ok=True);profiler.dump_stats(str(run/f'profiles/worker_{worker_id}.pstats'))
        log.close();outbox.cancel_join_thread()
