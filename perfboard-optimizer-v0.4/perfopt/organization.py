"""Functional placement relationships and manual-finish-oriented scoring."""
from collections import defaultdict
import math


def centers(config,candidate):
    return {name:(sum(candidate['placements'][r]['x'] for r in refs)/len(refs),
                  sum(candidate['placements'][r]['y'] for r in refs)/len(refs))
            for name,refs in config.get('placement_groups',{}).items()}


def relationships(config):
    groups=config.get('placement_groups',{});owner={r:name for name,refs in groups.items() for r in refs}
    nets=defaultdict(set)
    for spec in config['components']:
        if spec['id'] not in owner:continue
        for net in spec['pin_nets'].values():
            if net is not None and net not in config['constants']:nets[net].add(spec['id'])
    links=defaultdict(float)
    for refs in nets.values():
        if len(refs)>4:continue  # shared controls do not pull the whole board together
        names=sorted({owner[r] for r in refs})
        for i,a in enumerate(names):
            for b in names[i+1:]:links[(a,b)]+=1
    return links


def placement_terms(config,candidate):
    cs=centers(config,candidate);cohesion=0
    for name,refs in config.get('placement_groups',{}).items():
        x,y=cs[name]
        cohesion+=sum(abs(candidate['placements'][r]['x']-x)+abs(candidate['placements'][r]['y']-y) for r in refs)
    links=relationships(config)
    related=sum(weight*(abs(cs[a][0]-cs[b][0])+abs(cs[a][1]-cs[b][1])) for (a,b),weight in links.items())/max(sum(links.values()),1)
    crowding=0;items=list(cs.values())
    target=math.sqrt(config['board']['width']*config['board']['height']/max(len(items),1))*.65
    for i,(x,y) in enumerate(items):
        for u,v in items[i+1:]:crowding+=max(0,target-abs(x-u)-abs(y-v))
    return {'submodule_spread':cohesion,'related_group_distance':related,'group_crowding':crowding}


def distance(config,a,b):
    ca,cb=centers(config,a),centers(config,b)
    external=sum(abs(ca[n][0]-cb[n][0])+abs(ca[n][1]-cb[n][1]) for n in ca)/max(len(ca),1)
    internal=0;count=0
    for name,refs in config.get('placement_groups',{}).items():
        for ref in refs:
            pa,pb=a['placements'][ref],b['placements'][ref];count+=1
            internal+=abs((pa['x']-ca[name][0])-(pb['x']-cb[name][0]))+abs((pa['y']-ca[name][1])-(pb['y']-cb[name][1]))
    return external+.5*internal/max(count,1)


def finish_score(config,metrics):
    weights=config.get('portfolio',{}).get('merit_weights',{})
    o=metrics['organization']
    coverage=max(0,min(1,1-metrics['disconnected']/max(metrics.get('reference_sections',1),1)))
    terms={'unresolved':metrics['disconnected'],'remaining_distance':metrics.get('remaining_distance',0),
           'bundle_exposure':coverage*o.get('bundle_separation',0)/max(metrics.get('top_wire_length',metrics['wire_length']),1),
           'submodule_spread':o.get('submodule_spread',0),'related_group_distance':o.get('related_group_distance',0),
           'group_crowding':o.get('group_crowding',0),'bends':metrics['bends'],'wire_length':metrics['wire_length']}
    return round(sum(weights.get(k,0)*v for k,v in terms.items()),6)
