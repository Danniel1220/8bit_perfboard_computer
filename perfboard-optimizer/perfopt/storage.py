"""Checksummed atomic checkpoints, bounded JSONL logs and crash recovery."""
from __future__ import annotations
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import shutil
import time
import uuid
from .model import digest


def stamp():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds')


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('w',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,separators=(',',':'),ensure_ascii=False);f.flush();os.fsync(f.fileno())
        # A short retry handles scanners briefly opening a checkpoint on Windows.
        for attempt in range(8):
            try:os.replace(temporary,path);break
            except PermissionError:
                if attempt==7:raise
                time.sleep(0.025*(attempt+1))
        if os.name!='nt':
            fd=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:
        if temporary.exists():temporary.unlink()


def write_checkpoint(path,payload):
    atomic_json(path,{'schema_version':1,'sha256':digest(payload),'payload':payload})


def read_checkpoint(path,config=None):
    envelope=json.loads(Path(path).read_text(encoding='utf-8'))
    if envelope.get('schema_version')!=1 or digest(envelope['payload'])!=envelope.get('sha256'):
        raise ValueError(f'Checkpoint checksum/schema invalid: {path}')
    p=envelope['payload']
    if config and p['structure_hash']!=config['_structure_hash']:
        raise ValueError('Checkpoint board/constraint definition differs from config; use a new run directory')
    return p


def recover_candidates(run,config):
    run=Path(run)
    files=[run/'checkpoints/best.json',*sorted((run/'checkpoints').glob('best_*.json'),reverse=True),*sorted((run/'workers').glob('worker_*.best.json'))]
    for path in files:
        if not path.exists():continue
        try:yield path,read_checkpoint(path,config),None
        except (ValueError,KeyError,OSError,json.JSONDecodeError) as e:yield path,None,str(e)


def tuples(value):return tuple(tuples(x) for x in value) if isinstance(value,list) else value


class JsonLog:
    def __init__(self,path,max_bytes=20*1024*1024,backups=3):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.max_bytes=max_bytes;self.backups=backups;self.f=self.path.open('a',encoding='utf-8',buffering=1)

    def write(self,event,**fields):
        self.f.write(json.dumps({'schema_version':1,'timestamp':stamp(),'event':event,**fields},separators=(',',':'))+'\n')
        if self.f.tell()>self.max_bytes:self.rotate()

    def rotate(self):
        self.f.close()
        for i in range(self.backups,0,-1):
            source=self.path.with_name(self.path.name+f'.{i}.gz')
            if not source.exists():continue
            if i==self.backups:source.unlink()
            else:os.replace(source,self.path.with_name(self.path.name+f'.{i+1}.gz'))
        with self.path.open('rb') as src,gzip.open(str(self.path)+'.1.gz','wb',compresslevel=1) as dst:shutil.copyfileobj(src,dst)
        self.path.write_text('');self.f=self.path.open('a',encoding='utf-8',buffering=1)

    def close(self):self.f.close()


class RunLock:
    """OS lock releases after process death; no manual stale lock cleanup needed."""
    def __init__(self,path):self.path=Path(path);self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b')
        try:
            self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('This run directory is already being optimized by another process')
        return self
    def __exit__(self,*args):
        if self.file:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            self.file.close()
