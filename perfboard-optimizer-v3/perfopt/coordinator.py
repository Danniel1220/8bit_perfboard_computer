"""Single checkpoint authority and live telemetry coordinator."""
from __future__ import annotations
from collections import Counter,deque
import copy
import datetime as dt
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import signal
import time
import uuid
from .dashboard import Dashboard,read_key
from .export import export_best
from .snapshots import save_svg_snapshot
from .logic import validate_functional
from .model import load_seed
from .search import validate_candidate
from .storage import RunLock,JsonLog,atomic_json,write_checkpoint,read_checkpoint,recover_candidates,stamp
from .worker import run_worker


def find_best(config,run,blank=False):
    best=None;where=None;warnings=[];mismatches=0
    for path,payload,error in recover_candidates(run,config):
        if error:
            warnings.append(error);mismatches+=int('differs from config' in error);continue
        try:
            report=validate_candidate(config,payload['candidate'])
            if report['metrics']['hard_violations']:raise ValueError('Hard physical violations in checkpoint')
            payload['metrics']=report['metrics']
            if best is None or tuple(payload['metrics']['rank'])<tuple(best['metrics']['rank']):best=payload;where=str(path)
        except (ValueError,KeyError,TypeError) as e:warnings.append(f'{path}: {e}')
    if best is None:
        if mismatches:raise ValueError('Existing run uses a different board definition; choose a new --run directory')
        candidate=load_seed(config,blank)
        if blank:
            from .model import Geometry
            candidate['routes']=Geometry(config,candidate).stubs
            if config['constraints'].get('physical_junctions',False):
                from .router import Router
                candidate['junctions']=Router(config,candidate).junctions()[0]
        report=validate_candidate(config,candidate)
        if report['metrics']['hard_violations']:raise ValueError(f"Seed is physically invalid: {report['metrics']['errors'][:5]}")
        best={'schema_version':1,'structure_hash':config['_structure_hash'],'candidate':candidate,'metrics':report['metrics'],'search':{}}
        where='configuration placement with blank routing' if blank else str(Path(config['_root'])/config['seed'])
    return best,where,warnings


def optimize(config,args):
    run=Path(args.run).resolve()
    if args.fresh and run.exists() and any(run.iterdir()):raise ValueError('--fresh requires an empty/new --run directory; existing bests are never deleted')
    run.mkdir(parents=True,exist_ok=True)
    with RunLock(run/'optimizer.lock'):
        return _optimize(config,args,run)


def _optimize(config,args,run):
    best,loaded,warnings=find_best(config,run,args.blank_routing)
    functional=validate_functional(config,best['candidate'])
    runtime=best.get('search',{})
    try:
        saved=read_checkpoint(run/'runtime.json',config)
        if saved.get('total_candidates',0)>=runtime.get('total_candidates',0):runtime=saved
    except (OSError,ValueError,KeyError):pass
    base_candidates=runtime.get('total_candidates',0);base_seconds=runtime.get('total_search_seconds',0)
    checkpoint_count=runtime.get('checkpoints',0);session_id=uuid.uuid4().hex[:12]
    log=JsonLog(run/'logs/events.jsonl');history=JsonLog(run/'logs/best-history.jsonl',max_bytes=500*1024*1024,backups=1)
    atomic_json(run/'config-used.json',{k:v for k,v in config.items() if not k.startswith('_')})
    settings={k:v for k,v in vars(args).items() if isinstance(v,(str,int,float,bool,type(None)))}
    atomic_json(run/'settings.json',{'schema_version':1,'session_id':session_id,'started':stamp(),**settings})
    print(f"Loaded: {loaded}\nPrevious best: {best['metrics']['disconnected']} unresolved, {best['metrics']['wire_length']} wire cells, {best['metrics']['bends']} bends\nPrevious search time: {base_seconds:.1f}s; candidates evaluated: {base_candidates:,}\nWorkers: {args.workers}; strategy: placement portfolio + negotiated rip-up; seed: {args.seed}",flush=True)
    for warning in warnings:print('Recovery warning:',warning,flush=True)
    log.write('startup',session=session_id,loaded=loaded,workers=args.workers,seed=args.seed,previous_candidates=base_candidates,previous_seconds=base_seconds)
    ctx=mp.get_context('spawn');outbox=ctx.Queue(maxsize=max(128,args.workers*16));stop=ctx.Event();pause=ctx.Event()
    inboxes={};processes={};stats={};done=set();paused=set();errors=[];events=deque(maxlen=6)
    started=last_loop=last_runtime=last_summary=time.monotonic();active_seconds=0.0;last_improvement=started;last_print=started
    last_improvement-=runtime.get('seconds_since_improvement',0)
    improvement_monotonic=0;status='starting';saved_at='—';control_id=None;rate_samples=deque();last_export=0.0
    dashboard=Dashboard(not args.plain,args.refresh_rate)
    def totals():
        result={k:sum(s.get(k,0) for s in stats.values()) for k in ('candidates','accepted','rejected','invalid','route_attempts','restarts')}
        phases=Counter()
        for s in stats.values():phases.update(s.get('phase_seconds',{}))
        result['phase_seconds']=dict(phases);return result
    def search_state():
        t=totals();return {'structure_hash':config['_structure_hash'],'total_candidates':base_candidates+t['candidates'],'total_search_seconds':base_seconds+active_seconds,'checkpoints':checkpoint_count,'last_session':session_id,'worker_stats':stats,'seconds_since_improvement':time.monotonic()-last_improvement}
    def event(name,text,color='dim',**fields):
        line=f"[{dt.datetime.now().strftime('%H:%M:%S')}] {text}";events.append(f'[{color}]{line}[/{color}]')
        log.write(name,session=session_id,elapsed=active_seconds,**fields)
        if args.plain or not dashboard.enabled:
            if name!='strategy' or args.verbosity!='normal':print(line,flush=True)
    def publish(reason,new_best=False,worker=None):
        nonlocal checkpoint_count,saved_at,last_export
        best['search']=search_state();best['functional_validation']=functional
        if new_best:
            checkpoint_count+=1;best['search']['checkpoints']=checkpoint_count
            version=run/'checkpoints'/f'best_{checkpoint_count:08d}_{time.time_ns()}.json'
            write_checkpoint(version,best)
        write_checkpoint(run/'checkpoints/best.json',best)
        atomic_payload=search_state();write_checkpoint(run/'runtime.json',atomic_payload)
        saved_at=dt.datetime.now().strftime('%H:%M:%S')
        if new_best or reason in ('requested','startup/import') or not (run/'exports/best.svg').exists():
            before=time.perf_counter();report=validate_candidate(config,best['candidate']);report['functional']=functional
            export_best(config,best['candidate'],report,run/'exports');last_export=time.perf_counter()-before
            if new_best:history.write('global_best',session=session_id,worker=worker,candidates=base_candidates+totals()['candidates'],search_seconds=base_seconds+active_seconds,score=best['metrics']['rank'],unresolved=best['metrics']['unresolved_nets'],checkpoint=str(version.name),export_seconds=last_export)
        snapshot=save_svg_snapshot(run,checkpoint_count,best['metrics']['disconnected'],new_best=new_best,
            force=reason in ('requested','startup/import'),every=config['search'].get('svg_snapshot_every',5),
            retention=config['search'].get('svg_snapshot_retention',40))
        if snapshot:event('svg_snapshot',f'SVG snapshot saved: {snapshot.name}','cyan',path=str(snapshot))
        if new_best:
            versions=sorted((run/'checkpoints').glob('best_*.json'))
            for old in versions[:-config['search']['checkpoint_retention']]:old.unlink()
        event('checkpoint',f'Checkpoint saved ({reason}): {best["metrics"]["disconnected"]} unresolved','cyan',reason=reason,rank=best['metrics']['rank'])
    def summary():
        for old in sorted((run/'summaries').glob('*.json'))[:-143]:old.unlink()
        t=totals();hotspots=[];mutations=Counter();accepted_mutations=Counter();failures=Counter()
        for wid,s in stats.items():
            mutations.update(s.get('mutation_counts',{}));accepted_mutations.update(s.get('mutation_accepted',{}));failures.update(s.get('route_failures',{}))
            try:
                state=read_checkpoint(run/'workers'/f'worker_{wid}.state.json',config)
                hotspots.extend(state.get('history',[])[:100])
            except (OSError,ValueError,KeyError):pass
        atomic_json(run/'summaries'/f'{time.time_ns()}.json',{'schema_version':1,'timestamp':stamp(),'session_id':session_id,'total_search_seconds':base_seconds+active_seconds,'best':best['metrics'],'candidates':base_candidates+t['candidates'],'session_candidate_rate':t['candidates']/max(active_seconds,.001),'route_attempt_rate':t['route_attempts']/max(active_seconds,.001),'acceptance_rate':t['accepted']/max(t['candidates'],1),'mutation_counts':dict(mutations),'mutation_accepted':dict(accepted_mutations),'route_failures':dict(failures),'hotspots':hotspots[:500],'worker_stats':stats,'seconds_since_improvement':time.monotonic()-last_improvement})
    def command(cmd):
        nonlocal status
        if cmd in ('p','pause'):
            pause.set();status='pausing (finishing current candidates)';event('pause_requested','Pause requested','yellow')
        elif cmd in ('r','resume'):
            pause.clear();paused.clear();status='searching';event('resumed','Search resumed','cyan')
        elif cmd in ('s','save'):
            for q in inboxes.values():q.put({'kind':'save'})
            publish('requested')
        elif cmd in ('q','quit','stop'):
            stop.set();status='stopping safely';event('stop_requested','Finishing candidates and saving worker states','cyan')
    interrupts=[0]
    def interrupt(signum,frame):
        interrupts[0]+=1
        if interrupts[0]>1:raise KeyboardInterrupt
        command('quit')
    old_signal=signal.signal(signal.SIGINT,interrupt)
    old_break=None
    if hasattr(signal,'SIGBREAK'):old_break=signal.signal(signal.SIGBREAK,interrupt)
    try:
        publish('startup/import',new_best=not (run/'checkpoints/best.json').exists())
        # Discard stale control requests from an earlier process session.
        try:control_id=json.loads((run/'control.json').read_text())['id']
        except (OSError,ValueError,KeyError):pass
        for wid in range(args.workers):
            inbox=ctx.Queue(maxsize=16);inboxes[wid]=inbox
            quota=None if args.max_candidates is None else args.max_candidates//args.workers+int(wid<args.max_candidates%args.workers)
            p=ctx.Process(target=run_worker,args=(config,best,str(run),wid,args.seed+wid*1000003,outbox,inbox,stop,pause,{'quota':quota,'verbosity':args.verbosity,'profile':args.profile,'session_id':session_id}),name=f'perfboard-{wid}')
            p.start();processes[wid]=p
        status='searching';event('workers_started',f'{args.workers} independent workers started','cyan')
        dead_since={};file_seen={};last_poll=0.0
        while len(done)<len(processes):
            now=time.monotonic();delta=now-last_loop;last_loop=now
            if not pause.is_set() or len(paused|done)<len(processes):active_seconds+=delta
            if args.seconds is not None and now-started>=args.seconds and not stop.is_set():command('quit')
            key=read_key()
            if key:command(key)
            try:
                control=json.loads((run/'control.json').read_text())
                if control['id']!=control_id:control_id=control['id'];command(control['command'])
            except (OSError,ValueError,KeyError):pass
            messages=[];best_message=None
            # Queue congestion may drop notifications, never durable bests or
            # lifecycle acknowledgements. Poll changed files at coarse intervals.
            if now-last_poll>=2:
                last_poll=now
                for wid in processes:
                    for suffix in ('status','best'):
                        path=run/'workers'/f'worker_{wid}.{suffix}.json'
                        try:
                            modified=path.stat().st_mtime_ns
                            if file_seen.get(path)==modified:continue
                            if suffix=='status':
                                status_record=json.loads(path.read_text())
                                if status_record.get('session_id')!=session_id:continue
                                if status_record.get('paused'):paused.add(wid)
                                else:paused.discard(wid)
                                if status_record['kind'] in ('done','error') and wid not in done:messages.append(status_record)
                            else:
                                proposal=read_checkpoint(path,config)
                                if tuple(proposal['metrics']['rank'])<tuple(best['metrics']['rank']):
                                    item={'kind':'best','worker':wid,'path':str(path),'rank':proposal['metrics']['rank']}
                                    if best_message is None or tuple(item['rank'])<tuple(best_message['rank']):best_message=item
                            file_seen[path]=modified
                        except (OSError,ValueError,KeyError):pass
            for _ in range(1000):
                try:message=outbox.get_nowait()
                except queue.Empty:break
                if message['kind']=='best':
                    if best_message is None or tuple(message['rank'])<tuple(best_message['rank']):best_message=message
                else:messages.append(message)
            if best_message:messages.append(best_message)
            for message in messages:
                if args.seconds is not None and time.monotonic()-started>=args.seconds and not stop.is_set():command('quit')
                wid=message['worker'];kind=message['kind']
                if kind=='telemetry':stats[wid]=message['stats']
                elif kind=='best':
                    try:
                        proposal=read_checkpoint(message['path'],config);report=validate_candidate(config,proposal['candidate'])
                        if report['metrics']['hard_violations']:raise ValueError('Worker proposed a hard-invalid candidate')
                        if tuple(report['metrics']['rank'])<tuple(best['metrics']['rank']):
                            previous=best['metrics']['disconnected'];best=proposal;best['metrics']=report['metrics']
                            # Structural transforms were exhaustively tested in the worker;
                            # coordinator independently checks every published global best.
                            functional=validate_functional(config,best['candidate'])
                            last_improvement=improvement_monotonic=time.monotonic()
                            event('new_best',f'NEW BEST: {previous} -> {best["metrics"]["disconnected"]} unresolved','green',worker=wid,score=best['metrics']['rank'])
                            publish('new global best',True,wid)
                            for q in inboxes.values():
                                try:q.put_nowait({'kind':'best','rank':best['metrics']['rank'],'path':str(run/'checkpoints/best.json')})
                                except queue.Full:pass
                    except (OSError,ValueError,KeyError) as e:
                        event('proposal_rejected',str(e),'red',worker=wid)
                elif kind=='paused':paused.add(wid)
                elif kind=='resumed':paused.discard(wid)
                elif kind=='done':done.add(wid)
                elif kind=='strategy':event('strategy',f'Worker {wid}: plateau level {message["level"]}','yellow',worker=wid,level=message['level'])
                elif kind=='error' and wid not in done:errors.append(message['error']);event('worker_error',f'Worker {wid} failed; saving the best before stopping','red',worker=wid,error=message['error']);stop.set();done.add(wid)
            for wid,p in processes.items():
                if p.exitcode is not None and wid not in done:
                    try:
                        acknowledgement=json.loads((run/'workers'/f'worker_{wid}.status.json').read_text())
                        if acknowledgement.get('session_id')==session_id and acknowledgement['kind']=='done' and p.exitcode==0:
                            done.add(wid);continue
                    except (OSError,ValueError,KeyError):pass
                    # One grace interval lets the Queue feeder deliver the final message.
                    if p.exitcode!=0:errors.append(f'Worker {wid} exited with code {p.exitcode}');stop.set();done.add(wid)
                    elif wid in stats and stats[wid].get('activity')=='stopped':done.add(wid)
                    elif now-dead_since.setdefault(wid,now)>1:
                        errors.append(f'Worker {wid} exited without its final acknowledgement');stop.set();done.add(wid)
            if pause.is_set() and len(paused|done)==len(processes):status='paused (all workers checkpointed)'
            t=totals();rate_samples.append((now,t['candidates'],t['route_attempts']))
            while len(rate_samples)>1 and rate_samples[0][0]<now-5:rate_samples.popleft()
            first=rate_samples[0];span=max(now-first[0],.001)
            dashboard.update({'name':config['name'],'session_seconds':active_seconds,'total_seconds':base_seconds+active_seconds,'candidates':base_candidates+t['candidates'],'workers':args.workers,'best':best['metrics'],'candidate_rate':(t['candidates']-first[1])/span,'route_rate':(t['route_attempts']-first[2])/span,'accepted':t['accepted'],'rejected':t['rejected'],'invalid':t['invalid'],'since_improvement':now-last_improvement,'checkpoints':checkpoint_count,'saved_at':saved_at,'status':status,'worker_stats':stats,'phase_seconds':t['phase_seconds'],'events':list(events),'improvement_monotonic':improvement_monotonic})
            if now-last_runtime>=10:
                write_checkpoint(run/'runtime.json',search_state());last_runtime=now
            if now-last_summary>=config['search']['summary_seconds']:summary();last_summary=now
            if not dashboard.enabled and now-last_print>=10:
                print(f"{t['candidates']:,} session candidates; {t['candidates']/max(active_seconds,.001):.2f}/s; {best['metrics']['disconnected']} unresolved; {status}",flush=True);last_print=now
            time.sleep(1/args.refresh_rate)
    except KeyboardInterrupt:
        stop.set();event('force_stop','Second interrupt: stopping workers; durable global best remains saved','yellow')
    finally:
        stop.set();pause.clear()
        for p in processes.values():p.join(timeout=max(3,config['search']['candidate_seconds']+2))
        for p in processes.values():
            if p.is_alive():p.terminate();p.join();errors.append('Worker required forced termination; last durable worker state retained')
        # Collect final cumulative counters before persisting session totals.
        while True:
            try:message=outbox.get_nowait()
            except queue.Empty:break
            if message['kind']=='telemetry':stats[message['worker']]=message['stats']
        for wid in processes:
            try:
                saved=read_checkpoint(run/'workers'/f'worker_{wid}.state.json',config)
                if saved.get('session_id')==session_id:
                    stats[wid]={**stats.get(wid,{}),**saved['stats'],'activity':'stopped'}
            except (OSError,ValueError,KeyError):pass
        # A final worker proposal can arrive alongside its stop acknowledgement.
        for path,payload,error in recover_candidates(run,config):
            if payload is None:continue
            try:
                report=validate_candidate(config,payload['candidate'])
                if not report['metrics']['hard_violations'] and tuple(report['metrics']['rank'])<tuple(best['metrics']['rank']):
                    best=payload;best['metrics']=report['metrics'];functional=validate_functional(config,best['candidate']);publish('final worker result',True)
            except (ValueError,KeyError):pass
        publish('clean shutdown');summary();dashboard.close()
        t=totals();atomic_json(run/'last-session.json',{'schema_version':1,'session_id':session_id,'seconds':active_seconds,'candidates':t['candidates'],'candidates_per_second':t['candidates']/max(active_seconds,.001),'route_attempts':t['route_attempts'],'workers':args.workers,'peak_reported_worker_rss_bytes':sum(s.get('memory_bytes') or 0 for s in stats.values()),'phase_seconds':t['phase_seconds'],'errors':errors})
        signal.signal(signal.SIGINT,old_signal)
        if old_break is not None:signal.signal(signal.SIGBREAK,old_break)
        log.write('shutdown',session=session_id,search=search_state(),errors=errors);log.close();history.close()
        for q in [outbox,*inboxes.values()]:q.close();q.cancel_join_thread()
    print(f"\nSearch stopped {'with errors; checkpoint preserved' if errors else 'safely'}.\nBest checkpoint saved: {run/'checkpoints/best.json'}\nBest score: {best['metrics']['disconnected']} unresolved, {best['metrics']['wire_length']} wire cells, {best['metrics']['bends']} bends\nStatus: {'COMPLETE' if best['metrics']['complete'] else 'INCOMPLETE'}\nResume with:\npython optimize_alu.py --resume --workers {args.workers} --run \"{run}\"",flush=True)
    if errors:
        for error in errors:print(error,flush=True)
    return 1 if errors else 0
