"""Incremental negotiated router. Compact integer grid nodes; independent worker state."""
from __future__ import annotations
from collections import defaultdict
import heapq
import itertools
import time
from .model import Geometry


def edge(a,b):return (a,b) if a<b else (b,a)


class Router:
    def __init__(self,config,candidate,geometry=None):
        self.config=config;self.g=geometry or Geometry(config,candidate)
        self.history={};self.attempts=0;self.expansions=0;self.failures=defaultdict(int)
        self.deadline=float('inf');self.stop=None;self.pulse=None
        self.fixed_occ=self.occupancy(self.g.stubs)
        self.rebuild(self.g.stubs+[r for r in candidate['routes'] if r['kind']!='pin'])

    def axis(self,a,b):return 1 if a//self.g.w==b//self.g.w else 2

    def occupancy(self,routes):
        occ={}
        for r in routes:
            for a,b in zip(r['points'],r['points'][1:]):
                ax=self.axis(a,b)
                for p in (a,b):occ.setdefault(p,{})[r['net']]=occ.get(p,{}).get(r['net'],0)|ax
        return occ

    def rebuild(self,routes):
        self.routes=[];self.occ={};self.edges={};self.graphs={};self.build_errors=[]
        for r in routes:self.add(r)

    def add(self,r):
        if len(r['points'])<2:return
        self.routes.append(r);net=r['net'];graph=self.graphs.setdefault(net,defaultdict(set))
        for a,b in zip(r['points'],r['points'][1:]):
            ax=self.axis(a,b);e=edge(a,b)
            if e in self.edges and self.edges[e]!=net:self.build_errors.append(('overlap',e))
            self.edges[e]=net;graph[a].add(b);graph[b].add(a)
            for p in (a,b):self.occ.setdefault(p,{})[net]=self.occ.get(p,{}).get(net,0)|ax

    def components(self,net):
        graph=self.graphs.get(net,{})
        remaining=set(graph)|set(self.g.terminals.get(net,[]));out=[]
        while remaining:
            stack=[remaining.pop()];seen=set(stack)
            while stack:
                for p in graph.get(stack.pop(),()):
                    if p not in seen:seen.add(p);remaining.discard(p);stack.append(p)
            out.append(seen)
        return sorted(out,key=lambda x:(-len(x),min(x)))

    def unresolved(self):
        return {n:len(cs)-1 for n in self.g.terminals if len(cs:=self.components(n))>1}

    def bad_geometry(self,r):
        if r['kind']=='pin':return False
        net=r['net'];ps=r['points']
        if net not in self.g.terminals:return True
        for p in ps:
            if not self.g.available(p,net):return True
        for a,p,b in zip(ps,ps[1:],ps[2:]):
            if p in self.g.no_turn and self.axis(a,p)!=self.axis(p,b):return True
        for a,b in zip(ps,ps[1:]):
            ax=self.axis(a,b)
            if any(mask&ax for p in (a,b) for n,mask in self.fixed_occ.get(p,{}).items() if n!=net):return True
        return False

    def sanitize(self):
        self.rebuild(self.g.stubs+[r for r in self.routes if r['kind']!='pin' and not self.bad_geometry(r)])
        # Geometry moves can introduce a branch/crossing conflict with new pin stubs.
        bad=set()
        for p,nets in self.occ.items():
            masks=list(nets.values())
            if len(nets)>1 and (len(nets)>2 or 3 in masks or len(set(masks))<2):bad.add(p)
            if p in self.g.no_turn and 3 in masks:bad.add(p)
        if bad:self.rebuild([r for r in self.routes if r['kind']=='pin' or not bad.intersection(r['points'])])
        self.prune()

    def prune(self):
        # Remove obsolete dangling wire tails after a moved terminal or ripped route.
        keep_edges=set()
        for net,original in self.graphs.items():
            g={p:set(v) for p,v in original.items()};protected=set(self.g.terminals.get(net,[]))
            stack=[p for p in g if len(g[p])<=1 and p not in protected]
            while stack:
                p=stack.pop()
                for q in list(g[p]):
                    g[p].discard(q);g[q].discard(p)
                    if len(g[q])<=1 and q not in protected:stack.append(q)
            # Orphan cycles have no electrical purpose either.
            reachable=set(protected);queue=list(protected)
            while queue:
                for q in g.get(queue.pop(),()):
                    if q not in reachable:reachable.add(q);queue.append(q)
            keep_edges.update((net,edge(p,q)) for p in reachable for q in g.get(p,()))
        routes=[]
        for r in self.routes:
            if r['kind']=='pin':routes.append(r);continue
            ps=r['points'];segment=[ps[0]]
            for a,b in zip(ps,ps[1:]):
                if (r['net'],edge(a,b)) in keep_edges:segment.append(b)
                else:
                    if len(segment)>1:routes.append({**r,'points':segment})
                    segment=[b]
            if len(segment)>1:routes.append({**r,'points':segment})
        self.rebuild(routes)

    def expired(self):
        return time.perf_counter()>self.deadline or self.stop is not None and self.stop.is_set()

    def search(self,net,starts,goals,relax=False):
        self.attempts+=1
        if self.expired():self.failures['budget_or_stop']+=1;return None
        unavailable=self.g.blocked|self.g.pins|{p for p,n in self.g.reserved.items() if n!=net}
        starts=set(starts)-unavailable;goals=set(goals)-unavailable
        if not starts or not goals:self.failures['no_legal_escape']+=1;return None
        xs=[p%self.g.w for p in goals];ys=[p//self.g.w for p in goals]
        xmin,xmax,ymin,ymax=min(xs),max(xs),min(ys),max(ys);w=self.g.w
        def h(p):return max(xmin-p%w,0,p%w-xmax)+max(ymin-p//w,0,p//w-ymax)
        # Profiled hot loop: precompute foreign occupancy masks once per net search.
        def foreign(occ):
            result={}
            for p,nets in occ.items():
                mask=0
                for n,v in nets.items():
                    if n!=net:mask|=v
                if mask:result[p]=mask
            return result
        other=foreign(self.occ);fixed=foreign(self.fixed_occ) if relax else {}
        own={p:nets.get(net,0) for p,nets in self.occ.items() if net in nets}
        size=self.g.w*self.g.h*2;dist=[float('inf')]*size;previous=[-1]*size
        heap=[];serial=itertools.count()
        for p in sorted(starts):
            for offset in (0,1):
                state=p*2+offset;dist[state]=0;heapq.heappush(heap,(h(p),next(serial),state))
        expanded=0;limit=self.config['search']['max_astar_nodes'];no_turn=self.g.no_turn
        while heap:
            cost,_,state=heapq.heappop(heap);p=state//2;last=1 if state%2==0 else 2;base=dist[state]
            if cost>base+h(p)+1e-8:continue
            expanded+=1
            if expanded%512==0:
                if self.pulse:self.pulse('routing')
                if self.expired() or expanded>=limit:
                    self.expansions+=expanded;self.failures['search_budget']+=1;return None
            if p in goals:
                path=[]
                while state!=-1:path.append(state//2);state=previous[state]
                self.expansions+=expanded;return path[::-1]
            for q,ax in self.g.neighbors[p]:
                if q in unavailable:continue
                if p in no_turn and (ax!=last or own.get(p,0)&(3^ax)):continue
                if q in no_turn and own.get(q,0)&(3^ax):continue
                oq=other.get(q,0);op=other.get(p,0)
                badq=oq&ax;badp=op and (ax!=last or op&ax)
                if badq or badp:
                    if not relax:continue
                    fp=fixed.get(p,0)
                    if fixed.get(q,0)&ax or fp and (ax!=last or fp&ax):continue
                ng=base+1+(3.5 if ax!=last else 0)+(1.2 if oq else 0)+(40 if badq else 0)+(40 if badp else 0)+self.history.get((net,q),0)
                ns=q*2+int(ax==2)
                if ng<dist[ns]:
                    dist[ns]=ng;previous[ns]=state;heapq.heappush(heap,(ng+h(q),next(serial),ns))
        self.expansions+=expanded;self.failures['blocked']+=1;return None

    def connect(self,net,attempt_limit=None):
        attempt_limit=attempt_limit or self.config['search']['max_route_attempts']
        while not self.expired():
            cs=self.components(net)
            if len(cs)<2:return True
            success=False
            for other in cs[1:]:
                if self.attempts>=attempt_limit:return False
                path=self.search(net,other,cs[0])
                if path:
                    self.add({'net':net,'points':path,'kind':'wire'});success=True;break
                if self.attempts>=attempt_limit or self.expired():return False
            if not success:return False
        return False

    def repair(self,rng,focus=None):
        affected=set();unresolved=self.unresolved()
        todo=list(unresolved);rng.shuffle(todo)
        if focus:todo=sorted(todo,key=lambda n:n not in focus)
        strict_limit=max(1,self.config['search']['max_route_attempts']//2)
        for net in todo:
            self.connect(net,strict_limit)
            if self.expired():return
            if self.attempts>=strict_limit:break
        if self.attempts>=self.config['search']['max_route_attempts']:return
        unresolved=self.unresolved()
        if not unresolved:return
        net=rng.choice(list(unresolved));cs=self.components(net)
        path=self.search(net,rng.choice(cs[1:]),cs[0],relax=True)
        if not path:return
        bad={}
        for i,p in enumerate(path):
            mask=0
            if i:mask|=self.axis(path[i-1],p)
            if i+1<len(path):mask|=self.axis(p,path[i+1])
            for n,v in self.occ.get(p,{}).items():
                if n!=net and (mask==3 or mask&v):bad.setdefault(n,set()).add(p)
        remove=[r for r in self.routes if r['kind']!='pin' and r['net'] in bad and bad[r['net']].intersection(r['points'])]
        for n,points in bad.items():
            for p in points:self.history[(n,p)]=min(30,self.history.get((n,p),0)+2)
        ids={id(r) for r in remove};self.rebuild([r for r in self.routes if id(r) not in ids])
        self.add({'net':net,'points':path,'kind':'wire'})
        affected.update(r['net'] for r in remove)
        todo=list(affected);rng.shuffle(todo)
        for n in todo:
            if self.expired() or self.attempts>=self.config['search']['max_route_attempts']:break
            self.connect(n)
        self.prune()

    def physical_errors(self):
        errors=list(self.g.errors)+[str(e) for e in self.build_errors]
        for r in self.routes:
            if any(type(p) is not int for p in r['points']):
                errors.append('Wire node is not an integer grid cell');continue
            if self.bad_geometry(r):errors.append(f"Illegal route body/escape/fixed-pin conflict: {r['net']}")
            for a,b in zip(r['points'],r['points'][1:]):
                ax,ay=self.g.xy(a);bx,by=self.g.xy(b)
                if not(0<=a<self.g.w*self.g.h and 0<=b<self.g.w*self.g.h) or abs(ax-bx)+abs(ay-by)!=1:errors.append('Wire off grid or outside board')
        for p,nets in self.occ.items():
            masks=list(nets.values())
            if len(nets)>1 and (len(nets)>2 or 3 in masks or len(set(masks))<2):errors.append(f'Illegal crossing at {self.g.xy(p)}')
            if p in self.g.no_turn and 3 in masks:errors.append(f'Turn in fixed-tie clearance at {self.g.xy(p)}')
        return errors
