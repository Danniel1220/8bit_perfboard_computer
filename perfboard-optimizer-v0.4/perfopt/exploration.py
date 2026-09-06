"""Bounded, geometry-checked placement restarts for independent explorer workers."""
import copy
from .model import Geometry
from .router import Router


def explorer_worker(config, worker_id):
    every=config['search'].get('explorer_every',0)
    return bool(every and worker_id % every == every-1)


def diversify(config, current, rng, stop=None):
    if config.get('placement_groups'):
        return structured(config,current,rng,stop)
    movable=[s for s in config['components'] if not s.get('fixed') and s['function']!='connector']
    original=current['placements']
    budget=config['search'].get('placement_restart_attempts',32)
    for attempt in range(budget):
        if stop is not None and stop.is_set():break
        candidate={'placements':copy.deepcopy(current['placements']),
                   'pin_nets':copy.deepcopy(current['pin_nets']),'routes':[]}
        mode=rng.choice(('swap','relocate','group_relocate','shuffle'))
        if not movable:break
        chosen=rng.sample(movable,min(len(movable),2 if mode=='swap' else 4))
        if mode=='group_relocate':
            group=rng.choice(movable)['group']
            chosen=[s for s in movable if s['group']==group]
            dx=rng.randint(-config['board']['width']//2,config['board']['width']//2)
            dy=rng.randint(-config['board']['height']//2,config['board']['height']//2)
            for s in chosen:
                p=candidate['placements'][s['id']];p['x']+=dx;p['y']+=dy
        elif mode in ('swap','shuffle'):
            destinations=[original[s['id']] for s in chosen]
            destinations=destinations[1:]+destinations[:1]
            for s,destination in zip(chosen,destinations):
                p=candidate['placements'][s['id']]
                p['x'],p['y']=destination['x'],destination['y']
        else:
            chosen=chosen[:1]
            p=candidate['placements'][chosen[0]['id']]
            p.update(x=rng.randrange(config['board']['width']),y=rng.randrange(config['board']['height']),rotation=rng.choice(chosen[0]['rotations']))
        if candidate['placements']==original:continue
        candidate['routes']=[]
        g=Geometry(config,candidate)
        if g.errors:continue
        candidate['routes']=g.stubs
        router=Router(config,candidate,g)
        if router.physical_errors():continue
        if config['constraints'].get('physical_junctions'):candidate['junctions']=router.junctions()[0]
        return candidate,{'type':mode,'attempts':attempt+1,'components':[s['id'] for s in chosen]}
    return None,{'type':'placement_restart_failed','attempts':budget}


def structured(config,current,rng,stop=None):
    from .organization import centers,relationships,placement_terms
    groups=config['placement_groups'];specs={s['id']:s for s in config['components']}
    eligible={name:refs for name,refs in groups.items() if all(not specs[r].get('fixed') for r in refs)}
    if not eligible:return None,{'type':'no_movable_group'}
    cs=centers(config,current);links=relationships(config);options=[]
    for attempt in range(config['search'].get('placement_restart_attempts',32)):
        if stop is not None and stop.is_set():break
        candidate={'placements':copy.deepcopy(current['placements']),'pin_nets':copy.deepcopy(current['pin_nets']),'routes':[]}
        name=rng.choice(list(eligible));refs=eligible[name];mode=rng.choice(('exchange_groups','related_move','spread_group','tighten_group'))
        if mode=='exchange_groups' and len(eligible)>1:
            other=rng.choice([n for n in eligible if n!=name]);dx=round(cs[other][0]-cs[name][0]);dy=round(cs[other][1]-cs[name][1])
            for names,sign in ((refs,1),(eligible[other],-1)):
                for r in names:candidate['placements'][r]['x']+=sign*dx;candidate['placements'][r]['y']+=sign*dy
        elif mode=='tighten_group' and len(refs)>1:
            r=rng.choice(refs);p=candidate['placements'][r]
            # Pull one member toward its own submodule; never permute logic.
            axis=rng.choice(('x','y'));target=cs[name][axis=='y'];delta=round((target-p[axis])*rng.uniform(.25,.8))
            p[axis]+=delta
        else:
            related=[(b if a==name else a,v) for (a,b),v in links.items() if name in (a,b)]
            if mode=='related_move' and related:
                other=rng.choices([n for n,v in related],weights=[v for n,v in related])[0]
                tx,ty=cs[other];spacing=rng.randint(12,26)
                dx,dy=rng.choice(((spacing,0),(-spacing,0),(0,spacing),(0,-spacing)));tx+=dx;ty+=dy
            else:
                # Broad board zones, with a score favoring useful breathing room.
                tx=config['board']['width']*rng.choice((.2,.4,.6,.8));ty=config['board']['height']*rng.choice((.2,.4,.6,.8))
            dx,dy=round(tx-cs[name][0]),round(ty-cs[name][1])
            for r in refs:candidate['placements'][r]['x']+=dx;candidate['placements'][r]['y']+=dy
        if candidate['placements']==current['placements']:continue
        g=Geometry(config,candidate)
        if g.errors:continue
        candidate['routes']=g.stubs;router=Router(config,candidate,g)
        if router.physical_errors():continue
        candidate['junctions']=router.junctions()[0]
        terms=placement_terms(config,candidate)
        cost=terms['submodule_spread']+3*terms['related_group_distance']+2*terms['group_crowding']
        options.append((cost,candidate,{'type':mode,'group':name,'attempts':attempt+1}))
        if len(options)>=4:break
    if not options:return None,{'type':'placement_restart_failed'}
    options.sort(key=lambda item:item[0])
    # Retain breadth among sound proposals instead of always the same minimum.
    _,candidate,detail=rng.choice(options[:3])
    return candidate,detail
