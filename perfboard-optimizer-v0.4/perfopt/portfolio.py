"""Coordinator-owned, durable portfolio of independent placement families."""
import copy
from pathlib import Path
import random
import time
from .storage import write_checkpoint,read_checkpoint,atomic_json
from .search import validate_candidate,score
from .exploration import diversify
from .organization import distance
from .export import export_best
from .snapshots import save_svg_snapshot


class Portfolio:
    def __init__(self,config,run,seed,workers,random_seed):
        self.config=config;self.run=Path(run);self.workers=workers;self.seen={};self.slots=[];self.dirty=set();self.last_export=0
        self.path=self.run/'portfolio/state.json';self.backup=self.run/'portfolio/state-backup.json'
        cfg=config['portfolio'];self.count=cfg['slots'];self.scouts=min(cfg['scouts'],max(0,workers-self.count))
        for path in (self.path,self.backup):
            try:
                saved=read_checkpoint(path,config)
                for slot in saved['slots']:
                    report=validate_candidate(config,slot['best']['candidate'])
                    if report['metrics']['hard_violations']:raise ValueError('Invalid portfolio layout')
                    slot['best']['metrics']=report['metrics']
                self.slots=saved['slots'];self.seen=saved.get('seen',{});break
            except (OSError,ValueError,KeyError):pass
        if not self.slots and (self.path.exists() or self.backup.exists()):raise ValueError('Both portfolio state copies are invalid; preserve the run and recover its layout checkpoints before resuming')
        if self.slots and len(self.slots)!=self.count:raise ValueError('Changing portfolio slots requires a new run')
        rng=random.Random(random_seed)
        while len(self.slots)<self.count:
            candidate=copy.deepcopy(seed['candidate'])
            if self.slots:
                found=False
                for _ in range(12):
                    alternative,_=diversify(config,candidate,rng)
                    if alternative is None:continue
                    candidate=alternative
                    if all(distance(config,candidate,s['best']['candidate'])>=cfg['diversity_cells'] for s in self.slots):found=True;break
                if not found:raise ValueError('Could not initialize distinct valid portfolio layouts; lower diversity_cells or revise starting placement')
            report=validate_candidate(config,candidate)
            self.slots.append({'slot':len(self.slots),'epoch':0,'best':{'structure_hash':config['_structure_hash'],'candidate':candidate,'metrics':report['metrics']},
                               'evaluations':0,'worker_counts':{},'baseline':report['metrics']['disconnected'],'updates':0,'last_progress':time.time()})
        self.dirty.update(range(self.count));self.persist();self.assignments()

    def role(self,wid):
        routing=self.workers-self.scouts
        if wid>=routing:return 'scout',wid%self.count
        return 'router',min(self.count-1,wid*self.count//max(routing,1))

    def settings(self,wid):
        role,slot=self.role(wid)
        return {'role':role,'slot':slot,'epoch':self.slots[slot]['epoch']}

    def starting(self,wid):return self.slots[self.role(wid)[1]]['best']

    def assignments(self):
        for wid in range(self.workers):
            role,index=self.role(wid);slot=self.slots[index]
            write_checkpoint(self.run/f'portfolio/assignments/worker_{wid}.json',{'structure_hash':self.config['_structure_hash'],
                'role':role,'slot':index,'epoch':slot['epoch'],'best':slot['best']})

    def persist(self):
        payload={'structure_hash':self.config['_structure_hash'],'slots':self.slots,'seen':self.seen}
        # Two independently checksummed copies; either can recover a torn write.
        write_checkpoint(self.backup,payload);write_checkpoint(self.path,payload)
        for slot in self.slots:
            write_checkpoint(self.run/f"layouts/layout-{slot['slot']+1}/checkpoints/best.json",slot['best'])

    def consider(self,payload):
        c=self.config;cfg=c['portfolio'];role=payload['role'];index=payload['slot']
        if role=='scout' and payload.get('trial_evaluations',0)<cfg['trial_candidates']:return False
        report=validate_candidate(c,payload['candidate'])
        if report['metrics']['hard_violations']:return False
        payload['metrics']=report['metrics']
        if role=='router':
            slot=self.slots[index]
            if payload['epoch']!=slot['epoch']:return False
            key=str(payload['worker']);slot['worker_counts'][key]=max(slot['worker_counts'].get(key,0),payload.get('layout_evaluations',0))
            slot['evaluations']=sum(slot['worker_counts'].values())
            if tuple(payload['metrics']['rank'])>=tuple(slot['best']['metrics']['rank']):return False
        else:
            if any(distance(c,payload['candidate'],s['best']['candidate'])<cfg['diversity_cells'] for s in self.slots):return False
            # Young active layouts also receive their own fair routing budget.
            eligible=[s for s in self.slots if s['evaluations']>=cfg['trial_candidates']]
            if not eligible:return False
            slot=max(eligible,key=lambda s:self.admission_score(s['best']['metrics'],s['baseline'],s['evaluations']))
            new_score=self.admission_score(payload['metrics'],payload.get('baseline_unresolved',170),payload['trial_evaluations'])
            if new_score>=self.admission_score(slot['best']['metrics'],slot['baseline'],slot['evaluations']):return False
            index=slot['slot'];self.archive(slot,'replaced')
            slot.update(epoch=slot['epoch']+1,evaluations=0,worker_counts={},baseline=payload['metrics']['disconnected'])
        slot['best']=copy.deepcopy(payload);slot['updates']+=1;slot['last_progress']=time.time();self.dirty.add(index)
        return True

    def admission_score(self,metrics,baseline,evaluations):
        # Bounded progress bonus allocates opportunity, never rewrites board merit.
        progress=max(0,baseline-metrics['disconnected'])/max(evaluations,1)*100
        return metrics['finish_score']-min(self.config['portfolio']['progress_bonus_cap'],progress*self.config['portfolio']['progress_weight'])

    def archive(self,slot,reason):
        folder=self.run/f"portfolio/archive/layout-{slot['slot']+1}-generation-{slot['epoch']}-{time.time_ns()}"
        write_checkpoint(folder/'checkpoint.json',slot['best'])
        export_best(self.config,slot['best']['candidate'],validate_candidate(self.config,slot['best']['candidate']),folder)
        atomic_json(folder/'reason.json',{'reason':reason,'evaluations':slot['evaluations']})

    def poll(self):
        changed=False;observed=False
        paths=list((self.run/'workers').glob('*.layout.json'))+sorted((self.run/'portfolio/proposals').glob('*.json'))[:32]
        for path in paths:
            try:
                stamp=str(path.stat().st_mtime_ns);key=str(path.relative_to(self.run))
                if self.seen.get(key)==stamp:continue
                payload=read_checkpoint(path,self.config)
                changed=self.consider(payload) or changed;observed=True;self.seen[key]=stamp
                if path.parent.name=='proposals':
                    # Preserve the tested alternative, including those not admitted.
                    folder=self.run/'portfolio/evaluated';folder.mkdir(parents=True,exist_ok=True)
                    path.replace(folder/path.name)
            except (OSError,ValueError,KeyError,IndexError):continue
        if observed:self.persist()
        if changed:self.assignments()
        return changed

    def rows(self):
        result=[]
        for s in self.slots:
            m=s['best']['metrics'];workers=[wid for wid in range(self.workers) if self.role(wid)==('router',s['slot'])]
            result.append({'id':f"L{s['slot']+1}.{s['epoch']}",'unresolved':m['disconnected'],'finish_score':m['finish_score'],
                'bundle':m['organization'].get('bundle_separation',0)/max(m.get('top_wire_length',1),1),
                'organization':m['organization'].get('submodule_spread',0),'evaluations':s['evaluations'],
                'progress':s['baseline']-m['disconnected'],'remaining':max(0,self.config['portfolio']['trial_candidates']-s['evaluations']),
                'workers':','.join(map(str,workers)) or 'waiting','since_progress':time.time()-s['last_progress']})
        return result

    def export(self,force=False):
        if not force and time.monotonic()-self.last_export<self.config['portfolio']['svg_seconds']:return
        for index in sorted(self.dirty if not force else range(self.count)):
            slot=self.slots[index];folder=self.run/f'layouts/layout-{index+1}'
            export_best(self.config,slot['best']['candidate'],validate_candidate(self.config,slot['best']['candidate']),folder/'exports')
            save_svg_snapshot(folder,slot['updates'],slot['best']['metrics']['disconnected'],force=True,retention=self.config['search'].get('svg_snapshot_retention',10000))
        self.dirty.clear();self.last_export=time.monotonic()
        atomic_json(self.run/'portfolio/status.json',{'layouts':self.rows(),'updated':time.time()})
        # Local HTML uses refresh, so opening it shows all live SVGs without a server.
        cards=''.join(f'<section><h2>{r["id"]}: {r["unresolved"]} unresolved; merit {r["finish_score"]:.1f}</h2><object data="../layouts/layout-{i+1}/exports/best.svg?t={time.time_ns()}" type="image/svg+xml"></object></section>' for i,r in enumerate(self.rows()))
        html=f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="{self.config["portfolio"]["svg_seconds"]}"><title>Live ALU layouts</title><style>body{{background:#eee;font:14px Arial}}main{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}object{{width:100%;height:70vh}}h2{{font-size:16px}}</style><h1>Active layouts — auto-refreshing</h1><main>{cards}</main>'
        path=self.run/'portfolio/live.html';tmp=path.with_suffix('.tmp');tmp.write_text(html,encoding='utf-8');tmp.replace(path)
