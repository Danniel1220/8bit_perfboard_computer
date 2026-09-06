import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
from perfopt.model import load_config,load_seed
from perfopt.search import validate_candidate
from perfopt.portfolio import Portfolio
from perfopt.unfinished import guides
from perfopt.organization import distance,relationships,finish_score

ROOT=Path(__file__).resolve().parents[1]


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.c=load_config(ROOT/'config/alu.json');candidate=load_seed(self.c)
        self.seed={'structure_hash':self.c['_structure_hash'],'candidate':candidate,'metrics':validate_candidate(self.c,candidate)['metrics']}

    def test_distinct_slots_live_exports_and_backup_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Portfolio(self.c,temp,self.seed,12,173688151)
            self.assertEqual([p.role(i)[0] for i in range(12)],['router']*8+['scout']*4)
            for i,a in enumerate(p.slots):
                for b in p.slots[i+1:]:self.assertGreaterEqual(distance(self.c,a['best']['candidate'],b['best']['candidate']),1.5)
            p.export(True)
            for i in range(4):
                svg=Path(temp)/f'layouts/layout-{i+1}/exports/best.svg'
                root=E.parse(svg).getroot();ns={'s':'http://www.w3.org/2000/svg'}
                layer=root.find("s:g[@id='Unfinished-connections']",ns)
                self.assertIsNotNone(layer)
                self.assertEqual(len(layer.findall('s:circle',ns)),340)
            self.assertIn('http-equiv="refresh"',(Path(temp)/'portfolio/live.html').read_text())
            original=copy.deepcopy(p.slots);p.path.write_text('{corrupt')
            recovered=Portfolio(self.c,temp,self.seed,12,173688151)
            self.assertEqual([s['best']['candidate'] for s in recovered.slots],[s['best']['candidate'] for s in original])

    def test_fair_budget_diversity_and_stale_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Portfolio(self.c,temp,self.seed,12,173688151)
            proposal={**copy.deepcopy(self.seed),'role':'scout','slot':0,'worker':8,'epoch':0,'trial_evaluations':299,'baseline_unresolved':170}
            self.assertFalse(p.consider(proposal))
            proposal['trial_evaluations']=300
            with patch('perfopt.portfolio.distance',return_value=100):
                self.assertFalse(p.consider(proposal))  # active slots still young
            for s in p.slots:s['evaluations']=300
            self.assertFalse(p.consider(proposal))  # same placement excluded
            proposal.update(role='router',epoch=99,layout_evaluations=100)
            self.assertFalse(p.consider(proposal))

    def test_admission_uses_merit_and_progress_then_archives(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Portfolio(self.c,temp,self.seed,12,173688151)
            for s in p.slots:s['evaluations']=300
            proposal={**copy.deepcopy(self.seed),'role':'scout','slot':0,'worker':8,'epoch':0,'trial_evaluations':300,'baseline_unresolved':170}
            report=validate_candidate(self.c,proposal['candidate'])
            report['metrics']['finish_score']=1;report['metrics']['rank']=[0,1,170,0,0,0]
            with patch('perfopt.portfolio.distance',return_value=100),patch('perfopt.portfolio.validate_candidate',return_value=report),patch.object(p,'archive') as archive:
                self.assertTrue(p.consider(proposal));archive.assert_called_once()
            self.assertEqual(sum(s['epoch'] for s in p.slots),1)
            m={'finish_score':1000,'disconnected':10}
            self.assertLess(p.admission_score(m,100,300),p.admission_score(m,100,3000))

    def test_guides_join_sections_without_all_pairs(self):
        g=SimpleNamespace(w=30,terminals={'N':[]},blocked=set(),pins=set(),no_turn=set())
        r=SimpleNamespace(g=g,graphs={'N':{}},components=lambda net:[{31},{35},{39}])
        result=guides(r)
        self.assertEqual(len(result),2)
        self.assertEqual(sum(x['distance'] for x in result),8)
        self.assertTrue(all(x['kind']=='guide-not-route' for x in result))

    def test_relationships_ignore_shared_controls(self):
        links=relationships(self.c)
        self.assertGreater(links.get(('adders','b_conditioning'),0),0)
        self.assertGreater(links.get(('and','logic_mux'),0),0)

    def test_initial_routing_is_not_punished_for_exposing_new_wires(self):
        empty={'organization':{'bundle_separation':0},'disconnected':100,'reference_sections':100,'remaining_distance':1000,'wire_length':100,'bends':0}
        routed={**empty,'organization':{'bundle_separation':200},'disconnected':99,'remaining_distance':990}
        self.assertLess(finish_score(self.c,routed),finish_score(self.c,empty))
