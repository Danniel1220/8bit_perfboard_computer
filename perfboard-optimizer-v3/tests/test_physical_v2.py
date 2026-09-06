import copy
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from perfopt.junctions import options,realize,physical_wires,edge
from perfopt.model import load_config,load_seed,Geometry
from perfopt.router import Router
from perfopt.search import validate_candidate
from perfopt.messaging import Mailbox
from perfopt.export import export_best

ROOT=Path(__file__).resolve().parents[1]


def fixture(directions):
    width=30;center=10*width+10;graph={};occ={}
    for delta in directions:
        points=[center+i*delta for i in range(4)]
        for a,b in zip(points,points[1:]):
            graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
            mask=1 if abs(delta)==1 else 2
            for p in (a,b):occ.setdefault(p,{})['N']=occ.get(p,{}).get('N',0)|mask
    g=SimpleNamespace(blocked=set(),pins=set(),no_turn=set(),reserved={},xy=lambda p:(p%width,p//width))
    r=SimpleNamespace(g=g,graphs={'N':graph},occ=occ,fixed_edges=set(),config={'constraints':{'physical_junctions':True}})
    return r,center


class PhysicalRulesTests(unittest.TestCase):
    def test_blank_start_regenerates_stubs_and_junction_plan(self):
        from perfopt.coordinator import find_best
        for length in (1,2):
            with self.subTest(connector_escape_cells=length), tempfile.TemporaryDirectory() as temp:
                config=load_config(ROOT/'config/alu.json')
                config['constraints']['connector_escape_cells']=length
                if length==2:
                    with self.assertRaisesRegex(ValueError,'pin stub enters U_BUS'):
                        find_best(config,Path(temp),blank=True)
                    next(s for s in config['components'] if s['id']=='U_BUS')['initial']['x']+=1
                best,_,warnings=find_best(config,Path(temp),blank=True)
                candidate=best['candidate']
                self.assertFalse(warnings)
                self.assertEqual(candidate['junctions'],[])
                self.assertEqual(candidate['routes'],Geometry(config,candidate).stubs)
                self.assertTrue(all(r['kind']=='pin' for r in candidate['routes']))
                self.assertEqual(validate_candidate(config,candidate)['metrics']['hard_violations'],0)

    def test_three_T_and_rotated_templates(self):
        for ds in ((-30,-1,1),(30,-1,1),(-30,30,1),(-30,30,-1)):
            r,p=fixture(ds)
            self.assertEqual(len(options(r,'N',p)),3)
            for choice in options(r,'N',p):
                self.assertEqual(len(choice['ends']),3)
                self.assertEqual(len(choice['underneath']),2)
                self.assertNotIn(p,choice['ends'][1:] if choice['ends'][0]==p else [])

    def test_bus_crossing_forces_stem_to_own_center(self):
        r,p=fixture((-30,-1,1))
        r.occ[p-30]['other-bus']=1
        self.assertEqual([o['owner'] for o in options(r,'N',p)],[p-30])

    def test_plus_templates_rotated_and_blocked_landings(self):
        r,p=fixture((-30,30,-1,1));self.assertEqual(len(options(r,'N',p)),4)
        r.occ[p-30]['upper']=1;r.occ[p+30]['lower']=1
        self.assertFalse(options(r,'N',p))

    def test_fixed_stub_cannot_be_replaced_by_underneath_link(self):
        r,p=fixture((-30,-1,1));r.fixed_edges.add(('N',edge(p,p-30)))
        self.assertEqual([o['owner'] for o in options(r,'N',p)],[p-30])

    def test_top_wire_ends_and_underlinks_reconstruct_same_net(self):
        for ds in ((-30,-1,1),(-30,30,-1,1)):
            r,p=fixture(ds);plan,bad=realize(r);self.assertFalse(bad)
            wires=physical_wires(r,plan)
            endpoints=[n for w in wires for n in (w['points'][0],w['points'][-1])]
            self.assertEqual(len(endpoints),len(set(endpoints)))
            self.assertEqual(sum(p in (w['points'][0],w['points'][-1]) for w in wires),1)
            top={edge(a,b) for w in wires for a,b in zip(w['points'],w['points'][1:])}
            under={edge(a,b) for j in plan for a,b in j['underneath']}
            logical={edge(a,b) for a,ns in r.graphs['N'].items() for b in ns}
            self.assertFalse(top&under);self.assertEqual(top|under,logical)

    def test_overlapping_landing_holes_rejected(self):
        r,p=fixture((-30,-1,1));q=p+8
        r.graphs['N'][q]={q-30,q-1,q+1}
        def forced(router,net,center):
            return [{'net':net,'center':center,'owner':center-30,'ends':[center,999], 'underneath':[]}]
        with patch('perfopt.junctions.options',side_effect=forced):
            _,bad=realize(r);self.assertEqual(len(bad),2)

    def test_inclusive_IC_escape_in_all_rotations(self):
        base=load_config(ROOT/'config/alu.json')
        for count in (1,2,3):
            for rotation in (0,90,180,270):
                c=copy.deepcopy(base);spec=copy.deepcopy(c['components'][0]);c['components']=[spec]
                c['constraints']['ic_escape_cells']=count
                candidate={'placements':{spec['id']:{'x':20,'y':20,'rotation':rotation}},'pin_nets':{spec['id']:spec['pin_nets']},'routes':[]}
                g=Geometry(c,candidate)
                pin=next(p for p in g.pin_info if p['net'] not in (None,'VCC','GND'))
                self.assertEqual(len(pin['path']),count+1)
                for node in pin['path'][1:]:self.assertEqual(g.reserved[node],pin['net'])
                for node in pin['path'][1:-1]:self.assertIn(node,g.no_turn)
                self.assertNotIn(pin['path'][-1],g.no_turn)

    def test_JST_protection_is_outside_housing(self):
        c=load_config(ROOT/'config/alu.json');spec=next(s for s in c['components'] if s['id']=='J_A');c['components']=[spec]
        candidate={'placements':{spec['id']:spec['initial']},'pin_nets':{spec['id']:spec['pin_nets']},'routes':[]}
        g=Geometry(c,candidate);pin=g.pin_info[0]
        self.assertIn(pin['path'][1],g.blocked)
        self.assertNotIn(pin['path'][2],g.blocked)
        self.assertEqual(g.reserved[pin['path'][2]],pin['net'])
        self.assertIn(pin['path'][2],g.no_turn)
        self.assertNotIn(pin['path'][3],g.no_turn)

    def test_fresh_seed(self):
        c=load_config(ROOT/'config/alu.json');candidate=load_seed(c)
        report=validate_candidate(c,candidate)
        self.assertEqual(report['metrics']['hard_violations'],0)
        self.assertEqual(report['metrics']['disconnected'],170)
        self.assertFalse(candidate['junctions'])
        candidate['junctions']=[{'invalid':'stale'}]
        with self.assertRaises(ValueError):validate_candidate(c,candidate)

    def test_export_uses_real_gaps_and_underside_group(self):
        c=load_config(ROOT/'config/example-connector-board.json')
        c['board'].update(width=30,height=20)
        c['constraints'].update(ic_escape_cells=1,connector_escape_cells=1,physical_junctions=True)
        c['components']=[{'id':name,'package':'J','function':'connector','initial':{'x':x,'y':y,'rotation':0,'edge':side},
            'pin_nets':{'1':'A','2':'B'},'fixed':False,'rotations':[0],'edges':[side],'reorder_pins':True,'group':'io'}
            for name,x,y,side in [('L',1,8,'left'),('R',28,8,'right'),('T',15,1,'top')]]
        c['groups']={'io':{'members':['L','R','T']}}
        from perfopt.model import initial_candidate
        candidate=initial_candidate(c);candidate['routes']=Geometry(c,candidate).stubs
        candidate['routes'] += [{'net':'A','kind':'wire','points':[8*30+x for x in range(4,26)]},
            {'net':'A','kind':'wire','points':[y*30+15 for y in range(4,9)]}]
        r=Router(c,candidate);candidate['junctions']=r.junctions()[0]
        report=validate_candidate(c,candidate);self.assertEqual(report['metrics']['hard_violations'],0)
        self.assertEqual(len(candidate['junctions']),1)
        with tempfile.TemporaryDirectory() as folder:
            export_best(c,candidate,report,folder)
            import xml.etree.ElementTree as ET
            svg=ET.parse(Path(folder)/'best.svg').getroot()
            group=next(e for e in svg if e.get('id')=='Underneath-connections')
            self.assertEqual(len(list(group.iter('{http://www.w3.org/2000/svg}path'))),2)
            physical=json.loads((Path(folder)/'physical-wires.json').read_text())
            ends=[node for wire in physical['wires'] for node in (wire['points'][0],wire['points'][-1])]
            self.assertEqual(len(ends),len(set(ends)))
            self.assertEqual(len((Path(folder)/'underneath-connections.csv').read_text().splitlines()),3)

    def test_full_queue_does_not_kill_worker_and_status_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            q=queue.Queue(maxsize=1);q.put('full');mail=Mailbox(q,folder,0,'test')
            self.assertFalse(mail.send('strategy',level=3))
            self.assertFalse(mail.send('paused'))
            path=Path(folder)/'workers/worker_0.status.json'
            self.assertTrue(json.loads(path.read_text())['paused'])
            self.assertFalse(mail.send('saved'))
            self.assertTrue(json.loads(path.read_text())['paused'])
            self.assertFalse(mail.send('done'))
            self.assertEqual(json.loads(path.read_text())['kind'],'done')
