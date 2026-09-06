"""Bounded, geometry-checked placement restarts for independent explorer workers."""
import copy
from .model import Geometry
from .router import Router


def explorer_worker(config, worker_id):
    every=config['search'].get('explorer_every',0)
    return bool(every and worker_id % every == every-1)


def diversify(config, current, rng, stop=None):
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
