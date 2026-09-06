"""Logical equivalence guard and exhaustive ALU/flag tests, independent of routing."""
from __future__ import annotations
import json
from .model import roles, initial_candidate


def operations(config,candidate):
    result=[]
    for spec in config['components']:
        typ=spec['function'];n=roles(config,candidate,spec)
        if typ=='connector':
            # Cable pin order may change, but its named logical nets may not.
            if sorted(str(x) for x in candidate['pin_nets'][spec['id']].values()) != sorted(str(x) for x in spec['pin_nets'].values()):
                raise ValueError('Connector net multiset changed')
            if not spec.get('reorder_pins') and candidate['pin_nets'][spec['id']]!=spec['pin_nets']:
                raise ValueError('Fixed connector pin order changed')
        elif typ in ('AND','OR','XOR'):
            for i in range(4):
                if n.get(f'q{i}') is not None: result.append((typ,(n[f'a{i}'],n[f'b{i}']),(n[f'q{i}'],)))
        elif typ=='MUX':
            for i in range(4):result.append(('MUX',(n[f'a{i}'],n[f'b{i}'],n['sel'],n['en']),(n[f'q{i}'],)))
        elif typ=='ADD':
            result.append(('ADD',tuple(n[f'a{i}'] for i in range(4))+tuple(n[f'b{i}'] for i in range(4))+(n['ci'],),tuple(n[f'q{i}'] for i in range(4))+(n['co'],)))
        elif typ=='BUF':
            for i in range(8):result.append(('BUF',(n[f'a{i}'],n[f'b{i}'],n['dir'],n['oe']),(n[f'a{i}'],n[f'b{i}'])))
        elif typ=='CMP':result.append(('CMP',tuple(n[f'p{i}'] for i in range(8))+tuple(n[f'q{i}'] for i in range(8))+(n['en'],),(n['eq_n'],)))
        elif typ=='LUT':result.append(('LUT',tuple(n[f'd{i}'] for i in range(8))+tuple(n[f's{i}'] for i in range(3))+(n['en'],),(n['y'],n.get('w'))))
        elif typ=='REG':
            for i in range(4):result.append(('REG',(n[f'd{i}'],n['clk'],n['clr'],n['g1'],n['g2'],n['m'],n['n']),(n[f'q{i}'],)))
        elif typ=='SEL':
            for j in range(2):result.append(('SEL',tuple(n[f'd{j}{i}'] for i in range(4))+(n['s0'],n['s1'],n[f'en{j}']),(n.get(f'q{j}'),)))
        else:raise ValueError(f'Unsupported logical primitive: {typ}')
        if typ!='connector':
            if n.get('VCC')!='VCC' or n.get('GND')!='GND':raise ValueError('IC power pin remapped')
    return result


def signature(config,candidate):
    normalized=[]
    for typ,ins,outs in operations(config,candidate):
        if typ in ('AND','OR','XOR'):ins=tuple(sorted(ins))
        if typ=='CMP':
            pairs=sorted(tuple(sorted((ins[i],ins[8+i]))) for i in range(8))
            ins=tuple(v for pair in pairs for v in pair)+(ins[16],)
        normalized.append((typ,ins,outs))
    return json.dumps(sorted(normalized,key=repr),sort_keys=True)


def equivalence(config,candidate):
    if signature(config,candidate)!=signature(config,initial_candidate(config)):
        raise ValueError('Logical behavior changed: physical assignment is not an allowed equivalent circuit')


def validate_functional(config,candidate):
    equivalence(config,candidate)
    if config['validation']['kind']=='equivalence_only':
        return {'passed':True,'method':'canonical primitive equivalence','combinational_cases':0,'sequential_cases':0}
    if config['validation']['kind']!='alu8':raise ValueError('Unknown functional validator')
    import numpy as np
    a=np.repeat(np.arange(256,dtype=np.uint16),256)
    b=np.tile(np.arange(256,dtype=np.uint16),256)
    tasks_template=operations(config,candidate)
    cases=0
    for op0 in (0,1):
        for op1 in (0,1):
            for sub in (0,1):
                vals={k:np.full(65536,v,dtype=np.uint16) for k,v in {**config['constants'],'SUB':sub,'OP0':op0,'OP1':op1,'OE_N':0}.items()}
                for i in range(8):vals[f'A{i}']=(a>>i)&1;vals[f'B{i}']=(b>>i)&1
                pending=[x for x in tasks_template if x[0] not in ('REG','SEL')]
                while pending:
                    progress=False
                    for task in pending[:]:
                        typ,ins,outs=task
                        if typ=='BUF':
                            an,bn,direction,enable=ins
                            if direction not in vals or enable not in vals:continue
                            if np.any(vals[direction]):raise ValueError('ALU bus direction must remain B to A')
                            if bn not in vals:continue
                            vals[an]=np.where(vals[enable],2,vals[bn]);pending.remove(task);progress=True;continue
                        if any(n not in vals for n in ins):continue
                        v=[vals[n] for n in ins]
                        if typ=='AND':out=[v[0]&v[1]]
                        elif typ=='OR':out=[v[0]|v[1]]
                        elif typ=='XOR':out=[v[0]^v[1]]
                        elif typ=='MUX':out=[np.where(v[3],0,np.where(v[2],v[1],v[0]))]
                        elif typ=='ADD':
                            total=sum(v[i]<<i for i in range(4))+sum(v[i+4]<<i for i in range(4))+v[8]
                            out=[(total>>i)&1 for i in range(5)]
                        elif typ=='CMP':out=[np.logical_or(v[16],np.any(np.array(v[:8])!=np.array(v[8:16]),axis=0)).astype(np.uint16)]
                        elif typ=='LUT':
                            index=v[8]+2*v[9]+4*v[10]
                            y=np.where(v[11],0,np.take_along_axis(np.array(v[:8]),index[None,:],axis=0)[0]);out=[y,1-y]
                        else:raise ValueError(typ)
                        for n,value in zip(outs,out):
                            if n is not None:vals[n]=value
                        pending.remove(task);progress=True
                    if not progress:raise ValueError('Unresolved combinational dependency or cycle')
                raw=a+(b^(255 if sub else 0))+sub;arith=raw&255
                wanted=arith if (op0,op1)==(0,0) else a^b if (op0,op1)==(1,0) else a&b if (op0,op1)==(0,1) else a|b
                signed_a=a.astype(np.int16);signed_a=np.where(a<128,signed_a,signed_a-256)
                signed_b=b.astype(np.int16);signed_b=np.where(b<128,signed_b,signed_b-256)
                mathematical=signed_a-signed_b if sub else signed_a+signed_b
                expected={'ZERO_N':wanted!=0,'R7':(wanted>>7)&1,'C':(raw>>8)&1,'V':(mathematical < -128)|(mathematical > 127)}
                actual=sum(vals[f'BUS{i}']<<i for i in range(8))
                if not np.array_equal(actual,wanted):raise ValueError('Datapath truth-table failure')
                for n,value in expected.items():
                    if not np.array_equal(vals[n],value):raise ValueError(f'Flag truth-table failure: {n}')
                cases+=65536
    # Every stored state, incoming state, enable, reset, clock-edge and selector.
    specs={x['id']:x for x in config['components']}
    reg=roles(config,candidate,specs[config['validation']['register']])
    sel=roles(config,candidate,specs[config['validation']['selector']])
    if any(reg[k]!=v for k,v in {'clk':'CLK','clr':'CLEAR','g1':'FLAGS_LOAD_N','g2':'GND','m':'GND','n':'GND'}.items()):raise ValueError('Flag control wiring changed')
    if any(sel[k]!=v for k,v in {'s0':'FS0','s1':'FS1','en0':'GND','en1':'VCC','q0':'FLAG'}.items()):raise ValueError('Flag selector controls changed')
    meanings=['C','ZERO_N','R7','V'];sequential=0
    original_reg=roles(config,initial_candidate(config),specs[config['validation']['register']])
    previous_meaning={original_reg[f'q{i}']:original_reg[f'd{i}'] for i in range(4)}
    for old in range(16):
        for incoming in range(16):
            for load_n in (0,1):
                for clear in (0,1):
                    for rising in (0,1):
                        data={n:(incoming>>i)&1 for i,n in enumerate(meanings)}
                        previous={q:(old>>meanings.index(n))&1 for q,n in previous_meaning.items()}
                        stored={reg[f'q{i}']:0 if clear else data[reg[f'd{i}']] if rising and not load_n else previous[reg[f'q{i}']] for i in range(4)}
                        word=0 if clear else incoming if rising and not load_n else old
                        for selector in range(4):
                            if stored[sel[f'd0{selector}']]!=((word>>selector)&1):raise ValueError('Sequential flag behavior failed')
                            sequential+=1
    return {'passed':True,'method':'canonical equivalence + exhaustive ALU and flags','combinational_cases':cases,'sequential_cases':sequential}
