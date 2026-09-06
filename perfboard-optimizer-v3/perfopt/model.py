"""Board-independent geometry and configuration. No search or global mutable state."""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path


def digest(value):
    # Normalize integer dictionary keys exactly as a JSON round trip does.
    # Otherwise worker IDs 0..11 sort differently before/after loading.
    normalized=json.loads(json.dumps(value))
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_config(path):
    path = Path(path).resolve()
    c = json.loads(path.read_text(encoding='utf-8'))
    if c.get('schema_version') != 1:
        raise ValueError('Unsupported configuration schema_version')
    w, h = c['board']['width'], c['board']['height']
    if not isinstance(w, int) or not isinstance(h, int) or min(w, h) < 4:
        raise ValueError('Board dimensions must be integer grid cells >= 4')
    if c['board']['pitch_mm'] <= 0:
        raise ValueError('pitch_mm must be positive')
    if c['constraints']['crossings'] != 'orthogonal_straight_only':
        raise ValueError('Only orthogonal_straight_only crossings are supported')
    cap=c['constraints']['capacitors']
    if cap['horizontal']!='right_adjacent' or cap['vertical']!='bottom_adjacent':
        raise ValueError('Supported capacitor rules are right_adjacent / bottom_adjacent')
    for key in ('active_escape_cells','fixed_tie_no_turn_cells','connector_inset'):
        value=c['constraints'][key]
        if not isinstance(value,int) or value<0:raise ValueError(f'{key} must be a nonnegative integer')
    for key in ('ic_escape_cells','connector_escape_cells'):
        if key in c['constraints'] and (type(c['constraints'][key]) is not int or c['constraints'][key]<1):
            raise ValueError(f'{key} must be a positive integer')
    if c['constraints']['active_escape_cells']<1 or c['constraints']['fixed_tie_no_turn_cells']>c['constraints']['active_escape_cells']:
        raise ValueError('Escape length must be positive and cover fixed-tie clearance length')
    weights=c['search']['mutation_weights']
    allowed={'route','move','rotate','group_move','connector_move','connector_order','gate_channels','mux_channels','input_swap'}
    if not weights or set(weights)-allowed or any(not isinstance(v,(int,float)) or v<0 for v in weights.values()) or sum(weights.values())<=0:
        raise ValueError('mutation_weights must contain supported names with nonnegative weights and a positive total')
    for key in ('candidate_seconds','max_astar_nodes','max_route_attempts','plateau_candidates','plateau_seconds','worker_state_seconds','adopt_seconds','summary_seconds','checkpoint_retention'):
        if key in c['search'] and c['search'][key]<=0:raise ValueError(f'Search setting {key} must be positive')
    for key in ('exploration_initial_candidates','explorer_every','exploration_interval_candidates','exploration_grace_candidates','placement_restart_attempts','bundle_spacing_cells'):
        if key in c['search'] and (type(c['search'][key]) is not int or c['search'][key] < (0 if key in ('explorer_every','exploration_initial_candidates') else 1)):
            raise ValueError(f'{key} must be an integer with a valid positive range (explorer_every may be zero)')
    penalty=c['search'].get('bundle_route_penalty',0)
    if not isinstance(penalty,(int,float)) or not math.isfinite(penalty) or penalty<0:raise ValueError('bundle_route_penalty must be finite and nonnegative')
    known_nets={net for spec in c['components'] for net in spec['pin_nets'].values() if net is not None}
    bundled=set()
    for bundle in c.get('signal_bundles',[]):
        nets=bundle.get('nets',[])
        if len(nets)<2 or any(not isinstance(net,str) or net not in known_nets or net in c['constants'] for net in nets) or len(set(nets))!=len(nets) or bundled.intersection(nets):
            raise ValueError('signal_bundles must contain distinct known signal nets, each in at most one bundle')
        bundled.update(nets)
    ids = [x['id'] for x in c['components']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate component ID')
    for x in c['components']:
        package = c['packages'][x['package']]
        if package['kind'] not in ('ic', 'connector'):
            raise ValueError('Unknown package kind')
        expected = set(package.get('pins', {})) if package['kind'] == 'ic' else {str(i+1) for i in range(package['count'])}
        if set(x['pin_nets']) != expected:
            raise ValueError(f"Missing/extra physical pin assignments: {x['id']}")
        if not x['rotations'] or any(r not in (0, 90, 180, 270) for r in x['rotations']):
            raise ValueError('Rotations must be right angles')
    # Search settings and aesthetic weights can change while resuming a board.
    c['_structure_hash'] = digest({k:v for k,v in c.items() if k not in ('search','weights','colors','seed')})
    c['_config_path'] = str(path)
    c['_root'] = str(path.parent.parent)
    return c


def initial_candidate(c):
    return {'placements':{x['id']:copy.deepcopy(x['initial']) for x in c['components']},
            'pin_nets':{x['id']:copy.deepcopy(x['pin_nets']) for x in c['components']}, 'routes':[]}


def load_seed(c, blank=False):
    if blank:
        return initial_candidate(c)
    return json.loads((Path(c['_root']) / c['seed']).read_text())['candidate']


def transform(x, y, w, h, angle):
    return {0:(x,y), 90:(h-1-y,x), 180:(w-1-x,h-1-y), 270:(y,w-1-x)}[angle]


def vector(x, y, angle):
    return {0:(x,y), 90:(-y,x), 180:(-x,-y), 270:(y,-x)}[angle]


class Geometry:
    def __init__(self, config, candidate):
        self.config = config
        self.w, self.h = config['board']['width'], config['board']['height']
        self.blocked, self.pins, self.no_turn = set(), set(), set()
        self.straight_axes = {}
        self.reserved, self.terminals, self.bodies, self.centers = {}, {}, {}, {}
        self.stubs, self.ties, self.caps, self.errors, self.pin_info = [], [], [], [], []
        self.body_owner = {}
        specs = {x['id']:x for x in config['components']}
        if set(candidate['placements']) != set(specs) or set(candidate['pin_nets']) != set(specs):
            raise ValueError('Candidate component set differs from configuration')
        for ref, spec in specs.items():
            p = candidate['placements'][ref]
            pkg = config['packages'][spec['package']]
            if not all(isinstance(p.get(k),int) for k in ('x','y','rotation')):
                raise ValueError('Noninteger placement')
            x, y, r = p['x'], p['y'], p['rotation']
            if r not in spec['rotations']:
                self.errors.append(f'{ref}: illegal rotation')
            if r not in (0,90,180,270):
                raise ValueError('Unsupported rotation')
            if spec.get('fixed') and p != spec['initial']:
                self.errors.append(f'{ref}: fixed component moved')
            if set(candidate['pin_nets'][ref]) != set(spec['pin_nets']):
                raise ValueError(f'{ref}: physical pin set changed')
            if pkg['kind'] == 'ic':
                w,h = pkg['size']; bw,bh = (w,h) if r in (0,180) else (h,w)
                self.add_body(ref, x, y, bw, bh)
                for number, pin in pkg['pins'].items():
                    a,b = transform(*pin['at'],w,h,r)
                    dx,dy = vector(*pin['out'],r)
                    net = candidate['pin_nets'][ref][number]
                    self.add_pin(ref,number,net,(x+a,y+b),(dx,dy),True)
                if spec.get('capacitor'):
                    cap = (x+bw,y+1,1,2,0) if r in (0,180) else (x+1,y+bh,2,1,90)
                    self.caps.append({'ref':ref,'x':cap[0],'y':cap[1],'rotation':cap[4]})
                    self.add_body('C_'+ref,*cap[:4])
            else:
                edge = p.get('edge')
                if edge not in spec['edges']:
                    self.errors.append(f'{ref}: illegal connector edge')
                n = pkg['count']; inset = config['constraints']['connector_inset']
                if edge in ('left','right'):
                    if x != (inset if edge=='left' else self.w-1-inset):
                        self.errors.append(f'{ref}: connector off edge rail')
                    self.add_body(ref,x-1,y-1,3,n+2)
                    coords = [(x,y+i) for i in range(n)]; direction = (1,0) if edge=='left' else (-1,0)
                elif edge in ('top','bottom'):
                    if y != (inset if edge=='top' else self.h-1-inset):
                        self.errors.append(f'{ref}: connector off edge rail')
                    self.add_body(ref,x-1,y-1,n+2,3)
                    coords = [(x+i,y) for i in range(n)]; direction = (0,1) if edge=='top' else (0,-1)
                else:
                    raise ValueError('Unknown connector edge')
                for i,loc in enumerate(coords):
                    self.add_pin(ref,str(i+1),candidate['pin_nets'][ref][str(i+1)],loc,direction,False)
        for item in config.get('keepouts',[]):
            self.add_body('keepout',*item['rect'])
        for cell,net in self.reserved.items():
            if cell in self.blocked:
                self.errors.append(f'Escape blocked by component at {self.xy(cell)} ({net})')
        # A stub may cross its own pin/body, but not another component or capacitor.
        for pin in self.pin_info:
            if pin['net'] is None or pin['net'] in config['constants']:
                continue
            for cell in pin['path']:
                owner = self.body_owner.get(cell)
                if owner is not None and owner != pin['ref']:
                    self.errors.append(f"{pin['ref']}: pin stub enters {owner}")
        self.neighbors = []
        for n in range(self.w*self.h):
            x,y = self.xy(n)
            self.neighbors.append([(self.node(x+dx,y+dy),a) for dx,dy,a in ((1,0,1),(-1,0,1),(0,1,2),(0,-1,2)) if 0<=x+dx<self.w and 0<=y+dy<self.h])

    def node(self,x,y): return y*self.w+x
    def xy(self,n): return n%self.w,n//self.w

    def add_body(self,ref,x,y,w,h):
        cells=set()
        if min(x,y)<0 or x+w>self.w or y+h>self.h:
            self.errors.append(f'{ref}: body outside board')
        for a in range(x,x+w):
            for b in range(y,y+h):
                if not(0<=a<self.w and 0<=b<self.h): continue
                cell=self.node(a,b);cells.add(cell)
                if cell in self.body_owner:
                    self.errors.append(f'{ref}: body overlaps {self.body_owner[cell]} at {(a,b)}')
                self.body_owner[cell]=ref
        self.bodies[ref]=cells;self.centers[ref]=(x+(w-1)/2,y+(h-1)/2)
        self.blocked.update(cells)

    def add_pin(self,ref,number,net,loc,direction,is_ic):
        x,y=loc;dx,dy=direction
        count=self.config['constraints']['active_escape_cells']
        rules=self.config['constraints']; modern='ic_escape_cells' in rules
        if modern:
            # IC endpoint N is turnable; connector protected cells start outside
            # its one-cell housing margin and are strictly straight/unbranched.
            count=rules['ic_escape_cells'] if is_ic else 2+rules.get('connector_escape_cells',1)
        if net in self.config['constants']:count=max(count,rules['fixed_tie_no_turn_cells'])
        coords=[(x+k*dx,y+k*dy) for k in range(count+1)]
        checked=coords if net is not None and net not in self.config['constants'] else coords[:1]
        if any(not(0<=a<self.w and 0<=b<self.h) for a,b in checked):
            self.errors.append(f'{ref}.{number}: pin/escape outside board')
        path=[self.node(a,b) for a,b in coords]
        self.pins.add(path[0])
        self.pin_info.append({'ref':ref,'pin':number,'net':net,'hole':path[0],'path':path,'is_ic':is_ic})
        if modern and not is_ic:
            owner=net if net is not None else f'__connector_clearance_{ref}_{number}'
            for n in path[2:-1]:
                if n in self.reserved and self.reserved[n]!=owner:self.errors.append(f'Conflicting connector clearance at {self.xy(n)}')
                self.reserved[n]=owner;self.no_turn.add(n)
        if net is None: return
        if net in self.config['constants']:
            self.ties.append({'ref':ref,'pin':number,'net':net,'hole':path[0]})
            if is_ic:
                self.no_turn.update(self.node(a,b) for a,b in coords[1:1+self.config['constraints']['fixed_tie_no_turn_cells']] if 0<=a<self.w and 0<=b<self.h)
            return
        self.terminals.setdefault(net,[]).append(path[0])
        self.stubs.append({'net':net,'points':path,'kind':'pin'})
        if is_ic:
            for n in path[1:]:
                if n in self.reserved and self.reserved[n]!=net:
                    self.errors.append(f'Conflicting active escape reservations at {self.xy(n)}')
                self.reserved[n]=net
        if modern:
            protected=path[1:] if is_ic else path[2:-1]
            for n in protected:
                if n in self.reserved and self.reserved[n]!=net:self.errors.append(f'Conflicting escape reservation at {self.xy(n)}')
                self.reserved[n]=net
            for n in path[1:-1]:
                self.no_turn.add(n);self.straight_axes[n]=1 if dx else 2

    def available(self,p,net):
        return 0<=p<self.w*self.h and p not in self.blocked and p not in self.pins and self.reserved.get(p,net)==net


def roles(config, candidate, spec):
    return {pin['role']:candidate['pin_nets'][spec['id']][n] for n,pin in config['packages'][spec['package']].get('pins',{}).items()}
