"""Parallel routing preference using explicitly named related signal families."""
from collections import defaultdict


def peers(config,net):
    return {n for bundle in config.get('signal_bundles',[]) if net in bundle['nets'] for n in bundle['nets'] if n!=net}


def lane_support(router,net):
    """Candidate grid edges parallel and adjacent to an existing peer edge."""
    w,h=router.g.w,router.g.h
    support=set()
    spacing=router.config['search'].get('bundle_spacing_cells',1)
    for peer in peers(router.config,net):
        for a,neighbors in router.graphs.get(peer,{}).items():
            for b in neighbors:
                if a>=b:continue
                horizontal=a//w==b//w
                for sign in (-1,1):
                    dx,dy=(0,sign*spacing) if horizontal else (sign*spacing,0)
                    x,y=a%w+dx,a//w+dy;xx,yy=b%w+dx,b//w+dy
                    if 0<=x<w and 0<=xx<w and 0<=y<h and 0<=yy<h:
                        support.add((y*w+x,yy*w+xx))
    return support


def bundle_cost(config,router):
    """Penalize exposed edges of each bundle; adjacent parallel lanes score better.

    Count unique physical top-wire edges, excluding reserved pin escapes and
    underside links. Missing routes cannot improve the primary connectivity rank.
    """
    if not config.get('signal_bundles'):return 0
    plan,_=router.junctions()
    under={(j['net'],min(a,b),max(a,b)) for j in plan for a,b in j['underneath']}
    w=router.g.w;distance=config['search'].get('bundle_spacing_cells',1)
    penalty=0
    for bundle in config['signal_bundles']:
        lanes=defaultdict(set);edges=[]
        for net in bundle['nets']:
            for a,neighbors in router.graphs.get(net,{}).items():
                for b in neighbors:
                    if a>=b or (net,a,b) in under or a in router.g.reserved or b in router.g.reserved:continue
                    horizontal=a//w==b//w
                    along,lane=(a%w,a//w) if horizontal else (a//w,a%w)
                    lanes[(horizontal,along,lane)].add(net)
                    edges.append((net,horizontal,along,lane))
        for net,axis,along,lane in edges:
            matched=sum(bool(lanes.get((axis,along,lane+offset),set())-{net}) for offset in (-distance,distance))
            penalty+=2-matched
    return penalty
