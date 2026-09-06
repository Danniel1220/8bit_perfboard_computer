"""Placement/channel mutations and configurable visual-organization scoring."""
from __future__ import annotations
import copy
import fnmatch
import math
import time
from collections import Counter
from .model import Geometry, roles
from .router import Router
from .logic import equivalence, validate_functional
from .bundles import bundle_cost
from .organization import placement_terms,finish_score
from .unfinished import guides


def score(config,candidate,router=None):
    router=router or Router(config,candidate);g=router.g
    errors=router.physical_errors();unresolved=router.unresolved()
    length=len({(r['net'],min(a,b),max(a,b)) for r in router.routes for a,b in zip(r['points'],r['points'][1:])})
    bends=sum(router.axis(a,p)!=router.axis(p,b) for r in router.routes for a,p,b in zip(r['points'],r['points'][1:],r['points'][2:]))
    if config['constraints'].get('physical_junctions',False):
        plan,_=router.junctions()
        removed={(j['net'],min(a,b),max(a,b)) for j in plan for a,b in j['underneath']}
        bends=0
        for net,graph in router.graphs.items():
            for p,neighbors in graph.items():
                top=[q for q in neighbors if (net,min(p,q),max(p,q)) not in removed]
                if len(top)==2 and router.axis(p,top[0])!=router.axis(p,top[1]):bends+=1
    crossings=sum(len(n)>1 for n in router.occ.values())
    metrics={'disconnected':sum(unresolved.values()),'hard_violations':len(errors),'escape_violations':sum('escape' in str(e).lower() or 'clearance' in str(e).lower() for e in errors),
             'wire_length':length,'bends':bends,'congestion':crossings,'unresolved_nets':unresolved,'errors':errors[:100]}
    specs={x['id']:x for x in config['components']}
    groups={};centers={};spread=0
    for name,group in config.get('groups',{}).items():
        cs=[g.centers[n] for n in group['members'] if n in g.centers]
        if not cs:continue
        cx=sum(p[0] for p in cs)/len(cs);cy=sum(p[1] for p in cs)/len(cs);centers[name]=(cx,cy)
        spread+=sum(abs(x-cx)+abs(y-cy) for x,y in cs)
        pad=group.get('padding',2)
        groups[name]=(min(x for x,y in cs)-pad,min(y for x,y in cs)-pad,max(x for x,y in cs)+pad,max(y for x,y in cs)+pad)
    netgroups={}
    for pin in g.pin_info:
        if pin['net'] is not None:netgroups.setdefault(pin['net'],set()).add(specs[pin['ref']]['group'])
    foreign=outside=0
    for net,graph in router.graphs.items():
        own=netgroups.get(net,set())
        for node in graph:
            x,y=g.xy(node)
            corridor_factor=min([1]+[corr.get('weight',0) for corr in config.get('corridors',[]) for a,b,w,h in [corr['rect']] if a<=x<a+w and b<=y<b+h and any(fnmatch.fnmatchcase(net,pat) for pat in corr['nets'])])
            foreign+=corridor_factor*sum(name not in own and x0<=x<=x1 and y0<=y<=y1 for name,(x0,y0,x1,y1) in groups.items())
            if len(own)==1:
                box=groups.get(next(iter(own)))
                if box and not(box[0]-3<=x<=box[2]+3 and box[1]-3<=y<=box[3]+3):outside+=corridor_factor
    symmetry=0
    for pair in config.get('symmetry_pairs',[]):
        a=candidate['placements'][pair['a']];b=candidate['placements'][pair['b']];dx,dy=pair['offset']
        symmetry+=abs(b['x']-a['x']-dx)+abs(b['y']-a['y']-dy)+(4 if a['rotation']!=b['rotation'] else 0)
    connector_distance=0
    for ref,spec in specs.items():
        if spec['function']!='connector':continue
        x,y=g.centers[ref]
        for net in candidate['pin_nets'][ref].values():
            others=[g.centers[p['ref']] for p in g.pin_info if p['net']==net and p['ref']!=ref and net not in config['constants']]
            if others:connector_distance+=min(abs(x-a)+abs(y-b) for a,b in others)
    flow=0
    for item in config.get('flow_edges',[]):
        if item['from'] not in centers or item['to'] not in centers:continue
        ax,ay=centers[item['from']];bx,by=centers[item['to']]
        dx,dy=bx-ax,by-ay
        flow+=max(0,{'right':-dx,'left':dx,'down':-dy,'up':dy}[item['direction']])+0.15*(abs(dx)+abs(dy))
    terms={'group_spread':spread,'foreign_group_wire':foreign,'internal_wire_escape':outside,'connector_distance':connector_distance,'flow':flow,'symmetry':symmetry,'wire_length':length,'bends':bends,'congestion':crossings}
    terms['bundle_separation']=bundle_cost(config,router)
    terms.update(placement_terms(config,candidate))
    quality=round(sum(config['weights'].get(k,0)*v for k,v in terms.items()),6)
    metrics.update(quality=quality,organization=terms,longest_route=max((len(r['points'])-1 for r in router.routes),default=0),crossings=crossings)
    metrics['rank']=[metrics['disconnected'],metrics['hard_violations'],metrics['escape_violations'],quality,length,bends]
    metrics['complete']=not errors and metrics['disconnected']==0
    if config['constraints'].get('physical_junctions',False):
        plan,bad=router.junctions();metrics['junctions']=len(plan);metrics['junction_violations']=len(bad)
        metrics['underneath_links']=sum(len(j['underneath']) for j in plan)
        metrics['top_wire_length']=length-metrics['underneath_links']
    if config.get('portfolio',{}).get('enabled'):
        metrics['remaining_distance']=sum(item['distance'] for item in guides(router))
        metrics['reference_sections']=sum(max(0,len(pins)-1) for pins in router.g.terminals.values())
        metrics['finish_score']=finish_score(config,metrics)
        metrics['rank']=[metrics['hard_violations'],metrics['finish_score'],metrics['disconnected'],quality,length,bends]
    return metrics


def mutate(config,current,rng,level=0):
    cand=copy.deepcopy(current);weights=dict(config['search']['mutation_weights'])
    if level:
        for name,factor in (('move',1+level),('rotate',1+level/2),('route',0.7)):
            if name in weights:weights[name]*=factor
    names=list(weights);kind=rng.choices(names,weights=[weights[k] for k in names])[0]
    radius=[1,3,8,14][min(level,3)]
    specs=config['components'];changed=[];detail={'type':kind,'radius':radius};logical=False
    eligible=[s for s in specs if not s.get('fixed')]
    if kind in ('move','rotate'):
        options=[s for s in eligible if s['function']!='connector']
        if not options:return cand,{'type':'route','reason':'no movable IC'},False
        spec=rng.choice(options);p=cand['placements'][spec['id']];changed=[spec['id']]
        if kind=='move':
            dx,dy=rng.choice([(0,rng.choice((-1,1))*rng.randint(1,radius)),(rng.choice((-1,1))*rng.randint(1,radius),0)])
            p['x']+=dx;p['y']+=dy;detail['delta']=[dx,dy]
        else:
            rotations=[r for r in spec['rotations'] if r!=p['rotation']]
            if not rotations:return cand,{'type':'route','reason':'rotation fixed'},False
            detail['from']=p['rotation'];p['rotation']=rng.choice(rotations);detail['to']=p['rotation']
    elif kind=='group_move':
        group=rng.choice(list(config['groups']));members=set(config['groups'][group]['members'])
        dx,dy=rng.randint(-radius,radius),rng.randint(-radius,radius)
        for spec in eligible:
            if spec['id'] in members and spec['function']!='connector':
                p=cand['placements'][spec['id']];p['x']+=dx;p['y']+=dy;changed.append(spec['id'])
        detail.update(group=group,delta=[dx,dy])
    elif kind=='connector_move':
        options=[s for s in eligible if s['function']=='connector']
        if not options:return cand,{'type':'route'},False
        spec=rng.choice(options);changed=[spec['id']];p=cand['placements'][spec['id']]
        if level>=2 and len(spec['edges'])>1:p['edge']=rng.choice(spec['edges'])
        delta=rng.choice((-1,1))*rng.randint(1,radius*2);edge=p['edge'];inset=config['constraints']['connector_inset']
        if edge in ('left','right'):p['x']=inset if edge=='left' else config['board']['width']-1-inset;p['y']+=delta
        else:p['y']=inset if edge=='top' else config['board']['height']-1-inset;p['x']+=delta
        detail.update(delta=delta,edge=edge)
    elif kind=='connector_order':
        options=[s for s in specs if s['function']=='connector' and s.get('reorder_pins')]
        if not options:return cand,{'type':'route'},False
        spec=rng.choice(options);netmap=cand['pin_nets'][spec['id']];a,b=rng.sample(list(netmap),2)
        netmap[a],netmap[b]=netmap[b],netmap[a];changed=[spec['id']];logical=True;detail['pins']=[a,b]
    elif kind in ('gate_channels','mux_channels','input_swap'):
        options=[s for s in specs if s.get('commutative_pairs') if kind=='input_swap'] if kind=='input_swap' else [s for s in specs if s.get('equivalent_channels') and (s['function'] in ('AND','OR','XOR') if kind=='gate_channels' else s['function'] not in ('AND','OR','XOR'))]
        if not options:return cand,{'type':'route'},False
        spec=rng.choice(options);netmap=cand['pin_nets'][spec['id']]
        pins={p['role']:n for n,p in config['packages'][spec['package']]['pins'].items()}
        if kind=='input_swap':
            a,b=rng.choice(spec['commutative_pairs']);netmap[pins[a]],netmap[pins[b]]=netmap[pins[b]],netmap[pins[a]];detail['roles']=[a,b]
        else:
            channels=spec['equivalent_channels'];a,b=rng.sample(range(len(channels)),2)
            for ra,rb in zip(channels[a],channels[b]):netmap[pins[ra]],netmap[pins[rb]]=netmap[pins[rb]],netmap[pins[ra]]
            detail['channels']=[a,b]
        changed=[spec['id']];logical=True
    if kind=='route':
        wires=[r for r in cand['routes'] if r['kind']!='pin']
        if wires and rng.random()<0.55:
            selected=rng.choice(wires);detail['ripped_net']=selected['net'];detail['ripped_cells']=len(selected['points'])
            cand['routes'].remove(selected)
    detail['components']=changed
    return cand,detail,logical


def evaluate(config,candidate,rng,history=None,stop=None,pulse=None,logical=False,previous_geometry=None):
    times={};start=time.perf_counter();g=previous_geometry or Geometry(config,candidate);times['placement']=time.perf_counter()-start
    start=time.perf_counter();equivalence(config,candidate)
    if logical:validate_functional(config,candidate)
    times['logic']=time.perf_counter()-start
    router=Router(config,candidate,g);router.history=dict(history or {});router.stop=stop;router.pulse=pulse
    router.deadline=time.perf_counter()+config['search']['candidate_seconds']
    start=time.perf_counter()
    if not g.errors:
        router.sanitize();router.repair(rng)
        if config['constraints'].get('physical_junctions',False):router.repair_junctions()
    times['routing']=time.perf_counter()-start
    candidate['routes']=router.routes
    start=time.perf_counter();metrics=score(config,candidate,router);times['scoring_validation']=time.perf_counter()-start
    if config['constraints'].get('physical_junctions',False):candidate['junctions']=router.junctions()[0]
    return candidate,metrics,router,times


def validate_candidate(config,candidate,exhaustive=False):
    equivalence(config,candidate)
    g=Geometry(config,candidate)
    expected=Counter((r['net'],tuple(r['points'])) for r in g.stubs)
    actual=Counter((r['net'],tuple(r['points'])) for r in candidate['routes'] if r['kind']=='pin')
    if expected!=actual:raise ValueError('Stored pin stubs differ from physical pin geometry')
    router=Router(config,candidate,g);metrics=score(config,candidate,router)
    if config['constraints'].get('physical_junctions',False) and candidate.get('junctions')!=router.junctions()[0]:
        raise ValueError('Stored physical junction plan differs from validated geometry')
    functional=validate_functional(config,candidate) if exhaustive else {'passed':True,'method':'canonical equivalence'}
    return {'schema_version':1,'complete':metrics['complete'],'status':'COMPLETE' if metrics['complete'] else 'INVALID' if metrics['hard_violations'] else 'INCOMPLETE','metrics':metrics,'functional':functional}
