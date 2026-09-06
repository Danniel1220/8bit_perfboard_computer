"""Nonblocking worker notifications with durable lifecycle acknowledgements."""
import queue
import time
from pathlib import Path
from .storage import atomic_json


class Mailbox:
    def __init__(self,outbox,run,worker,session):
        self.outbox=outbox;self.run=Path(run);self.worker=worker;self.session=session;self.paused=False

    def send(self,kind,**fields):
        if kind=='paused':self.paused=True
        if kind in ('resumed','done','error'):self.paused=False
        message={'kind':kind,'worker':self.worker,**fields}
        if kind in ('paused','resumed','saved','done','error'):
            atomic_json(self.run/'workers'/f'worker_{self.worker}.status.json',
                {**message,'session_id':self.session,'paused':self.paused,'timestamp':time.time()})
        try:self.outbox.put_nowait(message);return True
        except queue.Full:return False
