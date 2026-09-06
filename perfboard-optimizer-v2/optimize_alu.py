#!/usr/bin/env python3
"""Standalone CPU perfboard optimizer. See README.md for normal operation."""
from __future__ import annotations
import argparse
import copy
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
from perfopt.model import load_config
from perfopt.storage import atomic_json

ROOT=Path(__file__).resolve().parent


def parser():
    p=argparse.ArgumentParser(description='Local multiprocessing perfboard placement/routing optimizer')
    p.add_argument('--config',default=str(ROOT/'config/alu.json'))
    p.add_argument('--run',default=str(ROOT/'runs/alu'),help='Persistent run directory')
    p.add_argument('--resume',action='store_true',help='Resume automatically (also the default)')
    p.add_argument('--fresh',action='store_true',help='New search history; requires an empty/new run directory')
    p.add_argument('--blank-routing',action='store_true',help='With --fresh, start from configured components without seed wires')
    p.add_argument('--workers',type=int,default=None,help='Independent CPU processes; benchmark recommendation or 4')
    p.add_argument('--seed',type=int,default=173688151)
    p.add_argument('--seconds',type=float,help='Optional session wall-time limit; otherwise run indefinitely')
    p.add_argument('--max-candidates',type=int,help='Optional total scored-candidate limit, divided across workers')
    p.add_argument('--refresh-rate',type=float,default=5,help='Live dashboard updates per second')
    p.add_argument('--verbosity',choices=['normal','verbose','trace'],default='normal')
    p.add_argument('--plain',action='store_true',help='Disable live screen; suitable for redirected logs')
    p.add_argument('--candidate-seconds',type=float,help='Routing time budget per candidate')
    p.add_argument('--plateau-seconds',type=float,help='Seconds without local improvement before diversification')
    p.add_argument('--plateau-candidates',type=int,help='Scored candidates without local improvement before diversification')
    p.add_argument('--summary-seconds',type=float,help='Diagnostic summary interval (default config: 600)')
    p.add_argument('--profile',action='store_true',help='Write per-worker cProfile .pstats files')
    actions=p.add_mutually_exclusive_group()
    actions.add_argument('--validate',action='store_true',help='Exhaustive functional + physical validation, no search')
    actions.add_argument('--export-svg',action='store_true',help='Manually export current best, no search')
    actions.add_argument('--export-diagnostics',action='store_true',help='Create compact diagnostic ZIP, no search')
    actions.add_argument('--control',choices=['pause','resume','save','quit'],help='Send command to running coordinator')
    actions.add_argument('--benchmark',action='store_true',help='Short 4/8/12/16-worker benchmark, never an overnight search')
    p.add_argument('--benchmark-seconds',type=float,default=3,help='Short search duration per worker-count benchmark')
    p.add_argument('--output',help='Output folder for --export-svg or ZIP path for --export-diagnostics')
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if args.workers is None:
        try:args.workers=int(json.loads((ROOT/'benchmarks/recommendation.json').read_text())['workers'])
        except (OSError,ValueError,KeyError):args.workers=min(4,os.cpu_count() or 1)
    if args.workers<1 or args.workers>128:raise ValueError('--workers must be between 1 and 128')
    if not .2<=args.refresh_rate<=30:raise ValueError('--refresh-rate must be between 0.2 and 30 Hz')
    if args.seconds is not None and args.seconds<=0:raise ValueError('--seconds must be positive')
    if args.max_candidates is not None and args.max_candidates<0:raise ValueError('--max-candidates must be nonnegative')
    if args.resume and args.fresh:raise ValueError('Choose --resume or --fresh')
    if args.blank_routing and not args.fresh:raise ValueError('--blank-routing requires --fresh and a new --run directory')
    if args.control:
        import uuid
        atomic_json(Path(args.run)/'control.json',{'id':uuid.uuid4().hex,'command':args.control,'timestamp':time.time()})
        print('Control request written:',args.control,'(check the running dashboard for acknowledgement)');return 0
    if args.export_diagnostics:
        from perfopt.diagnostics import bundle
        print(bundle(args.run,args.output));return 0
    config=load_config(args.config)
    for arg,key in [('candidate_seconds','candidate_seconds'),('plateau_seconds','plateau_seconds'),('plateau_candidates','plateau_candidates'),('summary_seconds','summary_seconds')]:
        value=getattr(args,arg)
        if value is not None:
            if value<=0:raise ValueError(f'--{arg.replace("_","-")} must be positive')
            config['search'][key]=value
    from perfopt.coordinator import find_best,optimize
    if args.validate or args.export_svg:
        from perfopt.search import validate_candidate
        best,loaded,warnings=find_best(config,args.run)
        report=validate_candidate(config,best['candidate'],exhaustive=args.validate)
        report['loaded_from']=loaded;report['recovery_warnings']=warnings
        if args.export_svg:
            from perfopt.export import export_best
            output=Path(args.output) if args.output else Path(args.run)/'manual-export'
            export_best(config,best['candidate'],report,output);print('SVG exported:',output/'best.svg');return 0
        output=Path(args.output) if args.output else Path(args.run)/'reports'/f'validation-{time.time_ns()}.json'
        atomic_json(output,report)
        print(json.dumps({'status':report['status'],'disconnected':report['metrics']['disconnected'],'hard_violations':report['metrics']['hard_violations'],'functional':report['functional'],'report':str(output)},indent=2))
        return 0 if report['complete'] else 2 if report['metrics']['hard_violations'] else 3
    if args.benchmark:
        if not 0<args.benchmark_seconds<=30:raise ValueError('Benchmark duration must be 0–30 seconds per count')
        results=[];folder=ROOT/'benchmarks'/str(time.time_ns());folder.mkdir(parents=True)
        for count in (4,8,12,16):
            trial=copy.copy(args);trial.workers=count;trial.run=str(folder/f'workers-{count}');trial.fresh=True;trial.resume=False;trial.seconds=args.benchmark_seconds;trial.max_candidates=None;trial.plain=True
            code=optimize(config,trial)
            result=json.loads((Path(trial.run)/'last-session.json').read_text());result['exit_code']=code;results.append(result)
        valid=[r for r in results if not r['errors']]
        if not valid:raise ValueError('All benchmark trials failed; inspect logs')
        peak=max(r['candidates_per_second'] for r in valid)
        eligible=[r for r in valid if r['candidates_per_second']>=peak*.9]
        chosen=min(eligible,key=lambda r:r['workers'])
        report={'schema_version':1,'workers':chosen['workers'],'results':results,'note':'Short startup-inclusive samples, not a steady-state or hardware-cache benchmark. Smallest worker count within 10% of measured peak throughput. Re-benchmark locally with --benchmark-seconds 15 for a more stable recommendation.'}
        atomic_json(ROOT/'benchmarks/recommendation.json',report);atomic_json(folder/'results.json',report)
        print('\nWorkers | candidates/s | reported worker RSS MiB')
        for r in results:print(f"{r['workers']:7} | {r['candidates_per_second']:12.2f} | {r['peak_reported_worker_rss_bytes']/1048576:23.1f}")
        print('Conservative measured default:',chosen['workers']);return 0
    return optimize(config,args)


if __name__=='__main__':
    multiprocessing.freeze_support()
    try:sys.exit(main())
    except (ValueError,RuntimeError,OSError,KeyError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(2)
