"""Editable SVG export using the user's component artwork. No rendering during search."""
from __future__ import annotations
import copy
import csv
import json
import os
from pathlib import Path
import xml.etree.ElementTree as E
from .model import Geometry
from .storage import atomic_json
from .router import Router
from .junctions import physical_wires

NS='http://www.w3.org/2000/svg';E.register_namespace('',NS)
def element(tag,attrs=None,parent=None,text=None):
    e=E.Element('{'+NS+'}'+tag,{k:str(v) for k,v in (attrs or {}).items()})
    if text is not None:e.text=text
    if parent is not None:parent.append(e)
    return e


def asset(root,path):
    source=E.parse(Path(root)/path).getroot();g=element('g')
    for child in source:g.append(copy.deepcopy(child))
    return g


def compact(points,w):
    out=[]
    for p in points:
        p=(p%w,p//w)
        if len(out)>1 and (out[-2][0]==out[-1][0]==p[0] or out[-2][1]==out[-1][1]==p[1]):out[-1]=p
        else:out.append(p)
    return out


def export_best(config,candidate,report,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    g=Geometry(config,candidate);pitch=config['board']['svg_pitch'];root_path=config['_root']
    physical=config['constraints'].get('physical_junctions',False);plan=[]
    render_routes=candidate['routes']
    if physical:
        router=Router(config,candidate,g);plan,bad=router.junctions()
        if bad or candidate.get('junctions')!=plan:raise ValueError('Cannot export an invalid/stale physical junction plan')
        render_routes=physical_wires(router,plan)
    root=element('svg',{'viewBox':f'0 0 {g.w*pitch} {g.h*pitch}','width':f"{g.w*config['board']['pitch_mm']}mm",'height':f"{g.h*config['board']['pitch_mm']}mm"})
    element('title',parent=root,text=f"{config['name']} — {report['status']}; {report['metrics']['disconnected']} disconnected sections")
    element('desc',parent=root,text='Thick paths are actual top-side wires ending at individual holes. Thin dashed net-colored links in Underneath-connections join adjacent holes beneath the board. Read validation.json before construction; power and fixed ties are listed separately.')
    grid=element('g',{'id':'Board-grid'},root);element('rect',{'width':g.w*pitch,'height':g.h*pitch,'fill':'white'},grid)
    for y in range(g.h):
        for x in range(g.w):element('circle',{'cx':(x+.5)*pitch,'cy':(y+.5)*pitch,'r':.34,'fill':'#d9dddd'},grid)
    wires=element('g',{'id':'Signal-wires'},root);graphs={}
    for i,r in enumerate(render_routes):
        coords=compact(r['points'],g.w)
        path='M '+' L '.join(f'{(x+.5)*pitch:.2f},{(y+.5)*pitch:.2f}' for x,y in coords)
        group=element('g',{'id':f'wire-{i}','data-net':r['net']},wires);element('title',parent=group,text=r['net'])
        prefix=r['net'].rstrip('0123456789');color=config.get('colors',{}).get(prefix,'#7b58ad')
        for stroke,width in (('#231f20',4.25),(color,3.4)):
            element('path',{'d':path,'fill':'none','stroke':stroke,'stroke-width':width,'stroke-linecap':'round','stroke-linejoin':'round'},group)
        graph=graphs.setdefault(r['net'],{})
        for a,b in zip(r['points'],r['points'][1:]):graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
    components=element('g',{'id':'Components'},root)
    for spec in config['components']:
        ref=spec['id'];p=candidate['placements'][ref];pkg=config['packages'][spec['package']];x,y=p['x'],p['y'];r=p['rotation']
        if pkg['kind']=='ic':
            art=asset(root_path,pkg['asset']);w,h=pkg['size'];t=f'translate({x*pitch} {y*pitch})'
            if r==90:t+=f' translate({h*pitch} 0) rotate(90)'
            if r==180:t+=f' translate({w*pitch} {h*pitch}) rotate(180)'
            if r==270:t+=f' translate(0 {w*pitch}) rotate(270)'
        else:
            n=pkg['count'];edge=p['edge'];art_path=Path(root_path)/f'assets/JST{n}.svg'
            if art_path.exists():art=asset(root_path,f'assets/JST{n}.svg')
            else:
                art=element('g');element('rect',{'x':0,'y':3.6,'width':18,'height':(n+1)*pitch,'fill':'#e6e7e8','stroke':'#231f20','stroke-width':.28},art)
                for i in range(n):element('circle',{'cx':10.8,'cy':10.8+i*pitch,'r':3.12,'fill':'#6d6e71','stroke':'#231f20','stroke-width':.28},art)
            if edge=='left':t=f'translate({(x+.5)*pitch-10.8} {(y+.5)*pitch-10.8})'
            elif edge=='top':t=f'translate({(x+.5)*pitch-10.8} {(y+.5)*pitch+10.8}) rotate(-90)'
            elif edge=='bottom':t=f'translate({(x+n-.5)*pitch+10.8} {(y+.5)*pitch-10.8}) rotate(90)'
            else:t=f'translate({(x+.5)*pitch+10.8} {(y+n-.5)*pitch+10.8}) rotate(180)'
        art.set('id',ref);art.set('transform',t);element('title',parent=art,text=ref);components.append(art)
    for cap in g.caps:
        art=asset(root_path,config['constraints']['capacitors']['asset']);t=f"translate({cap['x']*pitch} {cap['y']*pitch})"
        if cap['rotation']==90:t+=f' translate({2*pitch} 0) rotate(90)'
        art.set('transform',t);art.set('id','C_'+cap['ref']);components.append(art)
    junctions=element('g',{'id':'Electrical-junctions'},root)
    for net,graph in graphs.items():
        for p,neighbors in graph.items():
            if len(neighbors)<3 or p in g.blocked:continue
            x,y=g.xy(p);element('circle',{'cx':(x+.5)*pitch,'cy':(y+.5)*pitch,'r':2.2,'fill':config.get('colors',{}).get(net.rstrip('0123456789'),'#7b58ad'),'stroke':'#231f20','stroke-width':.65,'data-net':net},junctions)
    under=element('g',{'id':'Underneath-connections'},root)
    element('title',parent=under,text='Thin dashed lines: solder connections underneath the perfboard')
    for i,junction in enumerate(plan):
        group=element('g',{'id':f'junction-{i}','data-net':junction['net']},under)
        element('title',parent=group,text=f"{junction['net']}: distinct termination holes linked underneath")
        color=config.get('colors',{}).get(junction['net'].rstrip('0123456789'),'#7b58ad')
        for a,b in junction['underneath']:
            x,y=g.xy(a);u,v=g.xy(b)
            element('path',{'d':f'M {(x+.5)*pitch},{(y+.5)*pitch} L {(u+.5)*pitch},{(v+.5)*pitch}',
                'fill':'none','stroke':color,'stroke-width':.65,'stroke-dasharray':'1.1 0.8','stroke-linecap':'round'},group)
    labels=element('g',{'id':'Reference-labels','font-family':'Arial','font-size':3,'fill':'#666'},root)
    for spec in config['components']:
        p=candidate['placements'][spec['id']];element('text',{'x':(p['x']+.5)*pitch,'y':(p['y']+.5)*pitch-7},labels,spec['id'])
    temporary=directory/'best.svg.tmp';E.ElementTree(root).write(temporary,encoding='utf-8',xml_declaration=True);os.replace(temporary,directory/'best.svg')
    atomic_json(directory/'best.json',{'schema_version':1,'board':config['board'],'candidate':candidate})
    atomic_json(directory/'validation.json',report)
    with (directory/'connections.csv.tmp').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['Net','Component','Physical_pin','Column_zero_based','Row_zero_based','Connection_side'])
        for pin in g.pin_info:
            if pin['net'] is None:continue
            writer.writerow([pin['net'],pin['ref'],pin['pin'],*g.xy(pin['hole']),'underneath' if pin['net'] in config['constants'] else 'top'])
    os.replace(directory/'connections.csv.tmp',directory/'connections.csv')
    with (directory/'underneath-connections.csv.tmp').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['Junction','Net','Center_column','Center_row','Landing_column','Landing_row'])
        for i,j in enumerate(plan):
            for a,b in j['underneath']:writer.writerow([i,j['net'],*g.xy(a),*g.xy(b)])
    os.replace(directory/'underneath-connections.csv.tmp',directory/'underneath-connections.csv')
    atomic_json(directory/'physical-wires.json',{'schema_version':1,'board':config['board'],'wires':render_routes,'junctions':plan})
    atomic_json(directory/'export-complete.json',{'status':report['status'],'rank':report['metrics']['rank']})
