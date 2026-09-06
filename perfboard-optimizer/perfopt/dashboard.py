"""Low-overhead live Rich dashboard, with ANSI/plain fallback."""
from __future__ import annotations
import sys
import time

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.console import Group
    RICH=True
except ImportError:
    try:
        from pip._vendor.rich.console import Console,Group
        from pip._vendor.rich.live import Live
        from pip._vendor.rich.table import Table
        from pip._vendor.rich.panel import Panel
        RICH=True
    except ImportError:RICH=False


def duration(seconds):
    seconds=max(0,int(seconds));h,rem=divmod(seconds,3600);m,s=divmod(rem,60)
    return f'{h:02}:{m:02}:{s:02}'


def render(state):
    table=Table.grid(padding=(0,2));table.add_column(style='dim');table.add_column()
    best=state['best'];highlight='bold green' if time.monotonic()-state.get('improvement_monotonic',0)<2 else 'bold white'
    entries=[('session / total search',duration(state['session_seconds'])+' / '+duration(state['total_seconds'])),
             ('candidates evaluated',f"[{highlight}]{state['candidates']:,}[/{highlight}] (fully scored board states)"),
             ('workers',str(state['workers'])),('current best',f"[green]{best['disconnected']} unresolved[/green] / {best['hard_violations']} hard violations"),
             ('wire / bends / crossings',f"{best['wire_length']:,} cells / {best['bends']:,} / {best['crossings']:,}"),
             ('visual quality cost',f"{best['quality']:,.2f} (lower is better)"),('candidates/sec',f"{state['candidate_rate']:.2f}"),('route attempts/sec',f"{state['route_rate']:.2f}"),
             ('accepted / rejected / invalid',f"{state['accepted']:,} / {state['rejected']:,} / {state['invalid']:,}"),
             ('last improvement',duration(state['since_improvement'])+' ago'),('checkpoints',f"[cyan]{state['checkpoints']} — saved {state.get('saved_at','—')}[/cyan]"),
             ('status',f"[yellow]{state['status']}[/yellow]"),('controls','P pause · R resume · S save · Q quit · Ctrl+C safe stop')]
    for a,b in entries:table.add_row(a,b)
    workers=Table('Worker','Activity','Scored','c/s','Plateau','CPU s','RSS MiB',expand=True)
    for wid,s in sorted(state['worker_stats'].items()):
        workers.add_row(str(wid),s.get('activity','starting'),f"{s.get('candidates',0):,}",f"{s.get('candidates',0)/max(s.get('elapsed',0),.01):.1f}",str(s.get('plateau',0)),f"{s.get('cpu_seconds',0):.1f}",f"{s.get('memory_bytes',0)/1048576:.0f}" if s.get('memory_bytes') else '—')
    phases=state.get('phase_seconds',{});total=sum(phases.values()) or 1
    phase_text=' · '.join(f'{k}: {v/total:.0%}' for k,v in phases.items())
    return Group(Panel(table,title='PERFBOARD OPTIMIZER — '+state['name'],border_style='cyan'),workers,phase_text,*state.get('events',[])[-4:])


class Dashboard:
    def __init__(self,enabled=True,refresh_rate=5):
        self.enabled=enabled and sys.stdout.isatty();self.rate=refresh_rate;self.live=None;self.console=Console() if RICH else None
        if self.enabled and RICH:self.live=Live('',console=self.console,refresh_per_second=refresh_rate,auto_refresh=False,transient=False);self.live.start()
    def update(self,state):
        if not self.enabled:return
        if self.live:self.live.update(render(state),refresh=True)
        else:
            b=state['best'];sys.stdout.write(f"\033[2J\033[HPERFBOARD OPTIMIZER — {state['name']}\n{state['status']} | {state['workers']} workers | candidates evaluated: {state['candidates']:,}\n{state['candidate_rate']:.2f} candidates/sec | {state['route_rate']:.2f} route attempts/sec\nBest: {b['disconnected']} unresolved; {b['wire_length']} cells; {b['bends']} bends\nP pause / R resume / S save / Q quit\n");sys.stdout.flush()
    def close(self):
        if self.live:self.live.stop()


def read_key():
    if not sys.stdin.isatty():return None
    if sys.platform=='win32':
        import msvcrt
        if msvcrt.kbhit():return msvcrt.getwch().lower()
    else:
        import select
        if select.select([sys.stdin],[],[],0)[0]:return sys.stdin.readline().strip().lower()[:1]
    return None
