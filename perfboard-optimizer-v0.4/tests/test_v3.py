import copy
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from perfopt.model import load_config,load_seed,Geometry
from perfopt.exploration import diversify,explorer_worker
from perfopt.bundles import bundle_cost,lane_support
from perfopt.search import validate_candidate
from perfopt.router import Router

ROOT=Path(__file__).resolve().parents[1]


def lanes(rows):
    graphs={}
    for i,row in enumerate(rows):
        graph={}
        for x in range(3,12):
            a=row*30+x;b=a+1
            graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
        graphs['N'+str(i)]=graph
    c={'signal_bundles':[{'nets':list(graphs)}],'search':{'bundle_spacing_cells':1}}
    return SimpleNamespace(config=c,g=SimpleNamespace(w=30,h=30,reserved={}),graphs=graphs,junctions=lambda:([],[]))


class V3Tests(unittest.TestCase):
    def test_router_prefers_parallel_lane_without_relaxing_collisions(self):
        r=lanes([10]);r.config.update(constraints={'physical_junctions':False})
        r.config['signal_bundles']=[{'nets':['N0','A']}]
        r.config['search'].update(bundle_route_penalty=4,max_astar_nodes=5000)
        g=r.g
        g.stubs=[];g.blocked=set();g.pins=set();g.no_turn=set();g.straight_axes={}
        g.xy=lambda p:(p%30,p//30)
        g.neighbors={p:[(q,1 if p//30==q//30 else 2) for q in (p-1,p+1,p-30,p+30) if 0<=q<900 and abs(p%30-q%30)+abs(p//30-q//30)==1] for p in range(900)}
        candidate={'routes':[{'net':'N0','kind':'wire','points':[10*30+x for x in range(3,13)]}]}
        router=Router(r.config,candidate,g)
        path=router.search('A',{8*30+3},{8*30+12})
        self.assertIsNotNone(path)
        self.assertGreater(sum(p//30==9 for p in path),5)
        self.assertFalse(any(p in router.graphs['N0'] for p in path))

    def test_parallel_bus_beats_separated_and_pairs(self):
        bus=lanes([5,6,7,8]);pairs=lanes([5,6,12,13]);separated=lanes([5,8,11,14])
        self.assertLess(bundle_cost(bus.config,bus),bundle_cost(pairs.config,pairs))
        self.assertLess(bundle_cost(pairs.config,pairs),bundle_cost(separated.config,separated))
        self.assertIn((6*30+3,6*30+4),lane_support(bus,'N0'))
        self.assertFalse(lane_support(bus,'UNRELATED'))

    def test_bundle_cost_rotation_invariant(self):
        r=lanes([5,6,7]);before=bundle_cost(r.config,r)
        rotate=lambda n:n%30*30+(29-n//30)
        r.graphs={net:{rotate(p):{rotate(q) for q in ns} for p,ns in graph.items()} for net,graph in r.graphs.items()}
        self.assertEqual(before,bundle_cost(r.config,r))

    def test_diversity_preserves_logic_and_fixed_geometry(self):
        c=load_config(ROOT/'config/alu.json');seed=load_seed(c);original=copy.deepcopy(seed)
        c['components'][0]['fixed']=True
        results=[]
        for number in range(6):
            candidate,detail=diversify(c,seed,random.Random(number))
            if candidate is None:continue
            self.assertEqual(candidate['placements']['U_AND0'],seed['placements']['U_AND0'])
            self.assertEqual(candidate['pin_nets'],seed['pin_nets'])
            self.assertFalse(Geometry(c,candidate).errors)
            self.assertEqual(validate_candidate(c,candidate)['metrics']['hard_violations'],0)
            self.assertNotEqual(candidate['placements'],seed['placements'])
            results.append(detail['type'])
        self.assertGreaterEqual(len(results),3)
        self.assertEqual(seed,original)

    def test_worker_roles_and_disable(self):
        c=load_config(ROOT/'config/alu.json')
        self.assertEqual([i for i in range(12) if explorer_worker(c,i)],[2,5,8,11])
        c['search']['explorer_every']=0
        self.assertFalse(explorer_worker(c,2))
