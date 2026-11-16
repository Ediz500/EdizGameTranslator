"""Only current source translations. No read clocks and no display FIFO."""
import time


class LiveDisplayManager:
    def __init__(self,store,session,clock=time.monotonic):
        self.store,self.session,self.clock=store,session,clock
        self.closed=False;self.browser_required=False
        if session not in store.live_options:store.enable_live_session(session)

    def snapshot(self):
        now=self.clock()
        blocks=[] if self.closed else self.store.live_blocks(self.session,now)
        return dict(blocks=blocks,**self.store.live_stats(self.session,now))

    def ack(self,job,renderer):
        if self.closed or job not in {b['id'] for b in self.snapshot()['blocks']}:return False
        now=self.clock()
        if renderer=='tk_render_submitted' and self.browser_required:
            self.store.ack_observation(job,now,renderer);return False
        with self.store.lock:
            first=self.store.db.execute('SELECT visible_mono FROM translation_jobs WHERE id=?',(job,)).fetchone()[0] is None
        self.store.display_event(job,'visible',now,renderer)
        return first

    def removed(self,ids,renderer):
        if self.closed:return 0
        current={b['id'] for b in self.snapshot()['blocks']}
        return sum(self.store.ack_live_removal(self.session,job,self.clock(),renderer) for job in ids if job not in current)

    def sent(self):
        for b in self.snapshot()['blocks']:self.store.display_event(b['id'],'sent',self.clock())

    def clear(self,reason='user_stop'):
        self.store.cancel_session(self.session,reason);self.closed=True
