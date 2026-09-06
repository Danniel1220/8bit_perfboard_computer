"""Realize T/+ nodes as distinct wire-end holes and adjacent underside links.

Logical routes remain convenient search graphs. The deterministic realization
replaces non-owner arms by underneath edges, never by multiple wires in a hole.
"""
from collections import defaultdict,ChainMap


def edge(a,b):return min(a,b),max(a,b)


def options(router,net,center,graph=None):
    g=router.g;graph=router.graphs[net] if graph is None else graph;arms=sorted(graph[center])
    if len(arms) not in (3,4) or center in g.blocked|g.pins|g.no_turn:return []
    if any(n!=net for n in router.occ.get(center,{})):return []
    fixed=router.fixed_edges
    choices=[]
    for owner in arms:
        ends=[center];links=[];valid=True
        for landing in arms:
            if landing==owner:continue
            if (net,edge(center,landing)) in fixed or landing in g.blocked|g.pins|g.no_turn:
                valid=False;break
            if g.reserved.get(landing,net)!=net or any(n!=net for n in router.occ.get(landing,{})):
                valid=False;break
            neighbors=graph[landing]
            # Each non-owner arm must have a real, straight wire approaching its
            # landing hole, not a zero-length wire or another branch at that hole.
            if len(neighbors)!=2 or 2*landing-center not in neighbors:
                valid=False;break
            ends.append(landing);links.append([center,landing])
        if valid:choices.append({'net':net,'center':center,'owner':owner,'ends':sorted(ends),'underneath':links})
    return choices


def can_attach(router,net,center,neighbor):
    if not router.config['constraints'].get('physical_junctions',False):return True
    graph=router.graphs.get(net,{})
    adjacent=graph.get(center,set())
    if neighbor in adjacent or len(adjacent)<2:return True
    # A local optimistic preview. Full path geometry and all footprints are
    # still validated after routing; this cheaply rejects impossible bus taps.
    approaching=set(graph.get(neighbor,{2*neighbor-center}))|{center}
    preview=ChainMap({center:set(adjacent)|{neighbor},neighbor:approaching},graph)
    return bool(options(router,net,center,preview))


def realize(router):
    if not router.config['constraints'].get('physical_junctions',False):return [],[]
    variables={}
    for net,graph in sorted(router.graphs.items()):
        for center,neighbors in sorted(graph.items()):
            if len(neighbors)>=3:variables[(net,center)]=options(router,net,center)
    bad=[key for key,choices in variables.items() if not choices]
    if bad:return [],bad
    # Most junctions are independent. Solve only overlapping endpoint-footprint
    # components, so a choice at one branch cannot double-book another's hole.
    by_hole=defaultdict(set)
    for key,choices in variables.items():
        for choice in choices:
            for hole in choice['ends']:by_hole[hole].add(key)
    adjacency={key:set() for key in variables}
    for keys in by_hole.values():
        for key in keys:adjacency[key].update(keys-{key})
    remaining=set(variables);selected=[]
    while remaining:
        seed=min(remaining);cluster={seed};stack=[seed];remaining.remove(seed)
        while stack:
            for key in adjacency[stack.pop()]-cluster:
                cluster.add(key);remaining.discard(key);stack.append(key)
        budget=[4096]
        def solve(todo,used):
            budget[0]-=1
            if budget[0]<0:return None
            if not todo:return []
            possible={key:[x for x in variables[key] if not used.intersection(x['ends'])] for key in todo}
            key=min(todo,key=lambda k:(len(possible[k]),k))
            for choice in possible[key]:
                rest=solve(todo-{key},used|set(choice['ends']))
                if rest is not None:return [choice]+rest
            return None
        solution=solve(cluster,set())
        if solution is None:bad.extend(sorted(cluster))
        else:selected.extend(solution)
    return sorted(selected,key=lambda x:(x['net'],x['center'])),bad


def physical_wires(router,plan):
    """Maximal top-side wire chains after replacing the underneath links."""
    removed={(j['net'],edge(a,b)) for j in plan for a,b in j['underneath']}
    wires=[]
    for net,logical in sorted(router.graphs.items()):
        graph=defaultdict(set);unused=set()
        for a,neighbors in logical.items():
            for b in neighbors:
                e=edge(a,b)
                if (net,e) not in removed:
                    graph[a].add(b);unused.add(e)
        def walk(a,b):
            points=[a,b];unused.remove(edge(a,b))
            while len(graph[b])==2:
                nxt=next(n for n in graph[b] if n!=a)
                if edge(b,nxt) not in unused:break
                points.append(nxt);unused.remove(edge(b,nxt));a,b=b,nxt
            wires.append({'net':net,'points':points,'kind':'wire'})
        for a in sorted(graph):
            if len(graph[a])!=2:
                for b in sorted(graph[a]):
                    if edge(a,b) in unused:walk(a,b)
        while unused:walk(*min(unused))
    return wires
