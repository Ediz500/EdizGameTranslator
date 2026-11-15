"""Three independent read clocks; the FIFO backlog lives in SQLite, not RAM."""
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class ReadingConfig:
    minimum: float=1.3
    chars_per_second: float=17
    words_per_second: float=3.3
    lead: float=.25
    acceleration: float=1.5
    slots: int=3


READING=ReadingConfig()


def reading_seconds(text='',*,chars=None,words=None):
    chars=len(text) if chars is None else chars
    words=len(text.split()) if words is None else words
    return max(READING.minimum,chars/READING.chars_per_second+READING.lead,words/READING.words_per_second+READING.lead)


class DisplayManager:
    def __init__(self,store,session,clock=time.monotonic):
        self.store,self.session,self.clock=store,session,clock
        self.active=[];self.last=clock();self.closed=False

    def _advance(self,now):
        elapsed=max(0,now-self.last);self.last=now
        for block in self.active:
            if block['started'] is not None:block['remaining']=max(0,block['remaining']-elapsed*block['speed'])
        ended=[b for b in self.active if b['started'] is not None and b['remaining']<=1e-9]
        for b in ended:self.store.display_event(b['id'],'ended',now)
        self.active=[b for b in self.active if b not in ended]

    def snapshot(self):
        now=self.clock();self._advance(now)
        if not self.closed:
            while len(self.active)<READING.slots:
                job=self.store.offer_next(self.session,now)
                if job is None:break
                self.active.append(dict(**job,remaining=job['duration'],speed=1,started=None))
        stats=self.store.queue_stats(self.session)
        for i,b in enumerate(self.active):
            busy=len(self.active)==READING.slots
            b['speed']=READING.acceleration if busy and (stats['waiting']>=2 or stats['waiting']==1 and i==0) else 1
        return dict(blocks=[dict(b) for b in self.active],**stats)

    def ack(self,job,renderer):
        now=self.clock();self._advance(now)
        for b in self.active:
            if b['id']==job and not self.closed:
                first=b['started'] is None
                if first:b['started']=now
                self.store.display_event(job,'visible',now,renderer)
                return first
        return False

    def sent(self):
        now=self.clock()
        for b in self.active:self.store.display_event(b['id'],'sent',now)

    def clear(self,reason='user_stop'):
        self.store.cancel_session(self.session,reason)
        self.active=[];self.closed=True;self.last=self.clock()
