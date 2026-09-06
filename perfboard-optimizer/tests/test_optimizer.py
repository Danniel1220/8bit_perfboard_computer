import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
from perfopt.model import load_config,load_seed,initial_candidate,Geometry,digest
from perfopt.logic import validate_functional,equivalence
from perfopt.router import Router
from perfopt.search import validate_candidate,mutate,evaluate
from perfopt.storage import write_checkpoint,read_checkpoint,recover_candidates,RunLock
from perfopt.export import export_best
from perfopt.dashboard import render,RICH

ROOT=Path(__file__).resolve().parents[1]


class OptimizerTests(unittest.TestCase):
    def test_checkpoint_numeric_worker_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'runtime.json'
            payload={'workers':{i:{'candidates':i+1} for i in range(16)}}
            write_checkpoint(path,payload)
            self.assertEqual(read_checkpoint(path)['workers']['12']['candidates'],13)

    def test_fractional_wire_nodes_rejected(self):
        candidate=copy.deepcopy(self.seed)
        candidate['routes'].append({'net':'A0','kind':'wire','points':[1000.5,1001.5]})
        report=validate_candidate(self.config,candidate)
        self.assertIn('Wire node is not an integer grid cell',report['metrics']['errors'])

    def test_negotiated_repair_gets_an_attempt(self):
        r=Router(self.config,self.seed);relaxed=[]
        def blocked(net,starts,goals,relax=False):
            r.attempts+=1;relaxed.append(relax);return None
        r.search=blocked
        r.repair(random.Random(1))
        self.assertIn(True,relaxed)
        self.assertLessEqual(r.attempts,self.config['search']['max_route_attempts'])

    @classmethod
    def setUpClass(cls):cls.config=load_config(ROOT/'config/alu.json');cls.seed=load_seed(cls.config)

    def test_imported_seed_and_exhaustive_logic(self):
        report=validate_candidate(self.config,self.seed,True)
        self.assertEqual(report['metrics']['disconnected'],13)
        self.assertEqual(report['metrics']['hard_violations'],0)
        self.assertEqual(report['functional']['combinational_cases'],524288)
        self.assertEqual(report['functional']['sequential_cases'],8192)
        self.assertFalse(report['complete'])

    def test_pin_escape_injection_is_rejected(self):
        candidate=copy.deepcopy(self.seed);g=Geometry(self.config,candidate)
        p,owner=next(iter(g.reserved.items()));net=next(n for n in g.terminals if n!=owner)
        q=g.neighbors[p][0][0];candidate['routes'].append({'net':net,'points':[p,q],'kind':'wire'})
        report=validate_candidate(self.config,candidate)
        self.assertGreater(report['metrics']['hard_violations'],0);self.assertFalse(report['complete'])

    def test_missing_pin_stub_rejected(self):
        candidate=copy.deepcopy(self.seed);candidate['routes']=candidate['routes'][1:]
        # Explicitly remove a pin record, regardless of seed ordering.
        candidate=copy.deepcopy(self.seed)
        candidate['routes'].remove(next(r for r in candidate['routes'] if r['kind']=='pin'))
        with self.assertRaises(ValueError):validate_candidate(self.config,candidate)

    def test_unused_and_underboard_clearance(self):
        g=Geometry(self.config,self.seed)
        unused=[p for p in g.pin_info if p['net'] is None]
        self.assertTrue(unused)
        for pin in unused:
            for p in pin['path'][1:]:self.assertNotIn(p,g.reserved)
        fixed=[p for p in g.pin_info if p['net'] in self.config['constants'] and p['ref'].startswith('U_')]
        for pin in fixed:self.assertIn(pin['path'][1],g.no_turn)

    def test_every_mutation_is_scored_and_logic_safe(self):
        for kind in self.config['search']['mutation_weights']:
            with self.subTest(kind=kind):
                c=copy.deepcopy(self.config);c['search']['mutation_weights']={kind:1};c['search']['candidate_seconds']=.015;c['search']['max_astar_nodes']=512;c['search']['max_route_attempts']=1
                candidate,detail,logical=mutate(c,self.seed,random.Random(173),1)
                equivalence(c,candidate)
                candidate,metrics,router,times=evaluate(c,candidate,random.Random(174),logical=logical)
                self.assertIn('rank',metrics);self.assertIn('hard_violations',metrics)
                self.assertIn('scoring_validation',times)

    def test_wrong_arithmetic_bit_order_fails(self):
        candidate=copy.deepcopy(self.seed);pins=candidate['pin_nets']['U_ADD0'];pins['3'],pins['5']=pins['5'],pins['3']
        with self.assertRaises(ValueError):validate_functional(self.config,candidate)

    def test_overlap_and_fixed_placement_rejected(self):
        c=copy.deepcopy(self.config);candidate=copy.deepcopy(self.seed)
        ref='U_AND0';spec=next(x for x in c['components'] if x['id']==ref);spec['fixed']=True
        candidate['placements'][ref]['x']+=1;g=Geometry(c,candidate)
        self.assertTrue(any('fixed component' in e for e in g.errors))
        candidate['placements']['U_OR0']=copy.deepcopy(candidate['placements'][ref]);g=Geometry(c,candidate)
        self.assertTrue(any('overlap' in e for e in g.errors))

    def test_checkpoint_atomic_checksum_and_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder);payload={'structure_hash':self.config['_structure_hash'],'candidate':self.seed}
            write_checkpoint(run/'checkpoints/best_0001.json',payload);write_checkpoint(run/'checkpoints/best.json',payload)
            self.assertEqual(read_checkpoint(run/'checkpoints/best.json')['candidate'],self.seed)
            (run/'checkpoints/best.json').write_text('{truncated')
            recovered=list(recover_candidates(run,self.config))
            self.assertTrue(any(error for _,_,error in recovered));self.assertTrue(any(p is not None for _,p,_ in recovered))
            self.assertFalse(list(run.rglob('*.tmp')))

    def test_generic_other_board_complete(self):
        c=copy.deepcopy(self.config);c['board']={**c['board'],'width':14,'height':10};c['packages']={'J':{'kind':'connector','count':2}}
        c['components']=[{'id':name,'package':'J','function':'connector','initial':{'x':x,'y':2,'rotation':0,'edge':edge},'pin_nets':{'1':'A','2':'B'},'fixed':False,'rotations':[0],'edges':[edge],'reorder_pins':True,'group':'io'} for name,x,edge in [('IN',1,'left'),('OUT',12,'right')]]
        c['groups']={'io':{'members':['IN','OUT']}};c['flow_edges']=[];c['symmetry_pairs']=[];c['corridors']=[];c['validation']={'kind':'equivalence_only'}
        candidate=initial_candidate(c);g=Geometry(c,candidate);candidate['routes']=g.stubs
        for y,net in ((2,'A'),(3,'B')):candidate['routes'].append({'net':net,'points':[y*14+x for x in range(3,11)],'kind':'wire'})
        report=validate_candidate(c,candidate,True);self.assertTrue(report['complete'],report['metrics']['errors'])

    def test_export_and_dashboard_render(self):
        report=validate_candidate(self.config,self.seed)
        with tempfile.TemporaryDirectory() as folder:
            export_best(self.config,self.seed,report,folder)
            self.assertIn('INCOMPLETE',Path(folder,'best.svg').read_text())
            self.assertTrue(Path(folder,'connections.csv').exists())
        if RICH:
            from perfopt.dashboard import Console
            console=Console(record=True,width=120,force_terminal=True)
            state={'name':'TEST','best':report['metrics'],'session_seconds':2,'total_seconds':5,'candidates':123,'workers':2,'candidate_rate':10,'route_rate':20,'accepted':10,'rejected':2,'invalid':1,'since_improvement':1,'checkpoints':1,'status':'paused','worker_stats':{},'events':[]}
            console.print(render(state));self.assertIn('123',console.export_text())


if __name__=='__main__':unittest.main()
