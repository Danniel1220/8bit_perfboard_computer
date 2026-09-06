"""Small feedback bundles: log tails, summaries, config and a checksummed best."""
from pathlib import Path
import hashlib
import io
import json
import time
import zipfile
from .storage import read_checkpoint


def bundle(run,output=None,tail_bytes=1024*1024):
    run=Path(run);output=Path(output) if output else run/'diagnostics'/f'diagnostics-{time.strftime("%Y%m%d-%H%M%S")}.zip'
    output.parent.mkdir(parents=True,exist_ok=True);files={}
    for name in ('config-used.json','settings.json','last-session.json','runtime.json','checkpoints/best.json','exports/validation.json','exports/connections.csv'):
        p=run/name
        if p.exists():files[name]=p.read_bytes()
    for p in (run/'logs').glob('*.jsonl'):
        with p.open('rb') as f:
            size=p.stat().st_size;f.seek(max(0,size-tail_bytes));data=f.read()
        if size>tail_bytes:data=data.partition(b'\n')[2]
        files[str(p.relative_to(run))]=data
    for p in sorted((run/'summaries').glob('*.json'))[-12:]:files[str(p.relative_to(run))]=p.read_bytes()
    workers=[]
    for p in (run/'workers').glob('*.state.json'):
        try:
            state=read_checkpoint(p);workers.append({k:state[k] for k in ('worker','seed','lifetime_candidates','stats','metrics','history') if k in state})
        except (ValueError,OSError,KeyError):pass
    files['worker-diagnostics.json']=json.dumps(workers,separators=(',',':')).encode()
    manifest={name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()}
    files['manifest.json']=json.dumps({'schema_version':1,'logs_are_tails':True,'log_tail_limit_bytes':tail_bytes,'files':manifest},indent=2).encode()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in files.items():z.writestr(name.replace('\\','/'),data)
    return output
