"""Deterministic time, real SQLite; no paid API or hardware."""
import unittest
from subtitle_store import SubtitleStore
from subtitle_display import DisplayManager,reading_seconds


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.time=[0.0];self.store=SubtitleStore(':memory:')
        self.manager=DisplayManager(self.store,'session',clock=lambda:self.time[0])

    def tearDown(self):self.store.close()

    def add(self,text='Kısa.',duration=10,ready=True):
        row=self.store.accept('session','source',0,0,0,0,.99,'test',speaker='Scout')
        job=self.store.enqueue_translation('session',row,'source','gpt-6-luna',self.time[0])
        if ready:self.store.complete_translation(job,text,self.time[0],duration=duration)
        return job

    def show(self):
        state=self.manager.snapshot()
        for b in state['blocks']:self.manager.ack(b['id'],'test_renderer')
        return self.manager.snapshot()

    def test_reading_formula_ignores_separate_speaker(self):
        self.assertEqual(reading_seconds('Git!'),1.3)
        self.assertAlmostEqual(reading_seconds('a'*170),10.25)
        self.assertAlmostEqual(reading_seconds(chars=0,words=33),10.25)

    def test_three_blocks_fourth_waits_without_reset(self):
        ids=[self.add() for _ in range(3)];self.show()
        self.time[0]=2;fourth=self.add();state=self.show()
        self.assertEqual([b['id'] for b in state['blocks']],ids)
        self.assertEqual(state['waiting'],1)
        self.assertEqual([b['remaining'] for b in state['blocks']],[8,8,8])
        self.assertEqual([b['speed'] for b in state['blocks']],[1.5,1,1])
        self.assertNotIn(fourth,ids)

    def test_one_pending_accelerates_oldest_and_refill_is_fresh(self):
        first=self.add(duration=2);others=[self.add(duration=10) for _ in range(2)];self.show()
        fourth=self.add();self.show();self.time[0]=2;state=self.show()
        self.assertEqual([b['id'] for b in state['blocks']],others+[fourth])
        self.assertEqual([b['remaining'] for b in state['blocks']],[8,8,10])
        self.assertEqual([b['speed'] for b in state['blocks']],[1,1,1])
        self.assertEqual(self.store.db.execute('SELECT display_state FROM translation_jobs WHERE id=?',(first,)).fetchone()[0],'completed')

    def test_two_pending_accelerates_all_then_restores_without_refund(self):
        self.add(duration=3);self.add(duration=10);self.add(duration=10);self.show()
        self.add();self.add();state=self.show()
        self.assertEqual([b['speed'] for b in state['blocks']],[1.5]*3)
        self.time[0]=2;state=self.show()
        self.assertEqual([b['remaining'] for b in state['blocks']],[7,7,10])
        self.assertEqual([b['speed'] for b in state['blocks']],[1.5,1,1])

    def test_no_timer_before_renderer_ack_and_no_redraw_reset(self):
        job=self.add(duration=3);self.manager.snapshot();self.time[0]=20
        self.assertEqual(self.manager.snapshot()['blocks'][0]['remaining'],3)
        self.manager.ack(job,'browser_dom_ack');self.time[0]=21
        self.assertEqual(self.manager.snapshot()['blocks'][0]['remaining'],2)
        self.manager.ack(job,'browser_dom_ack');self.time[0]=22
        self.assertEqual(self.manager.snapshot()['blocks'][0]['remaining'],1)

    def test_reverse_api_completion_preserves_order_and_error_unblocks(self):
        first=self.add(ready=False);second=self.add()
        self.assertEqual(self.manager.snapshot()['blocks'],[])
        self.store.complete_translation(first,'Önce',0,duration=10)
        self.assertEqual([b['id'] for b in self.show()['blocks']],[first,second])

    def test_error_is_explicit_and_next_speaker_still_displays(self):
        first=self.add(ready=False);second=self.add()
        self.store.fail_translation(first,0)
        self.assertEqual([b['id'] for b in self.show()['blocks']],[second])

    def test_stop_cancels_all_states_and_rejects_late_results(self):
        ids=[self.add() for _ in range(4)];late=self.add(ready=False);self.show()
        self.manager.clear('user_stop')
        self.store.complete_translation(late,'Geç',1,duration=10)
        self.assertFalse(self.manager.snapshot()['blocks'])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM translation_jobs WHERE display_state='cancelled'").fetchone()[0],5)

    def test_browser_ack_after_native_ack_is_recorded_without_clock_reset(self):
        job=self.add(duration=10);self.manager.snapshot()
        self.manager.ack(job,'tk_render_submitted');self.time[0]=2
        self.manager.ack(job,'browser_dom_ack')
        self.assertEqual(self.manager.snapshot()['blocks'][0]['remaining'],8)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM render_acks').fetchone()[0],2)

    def test_persistent_backlog_has_bounded_active_memory_no_silent_drop(self):
        for _ in range(1000):self.add(duration=1.3)
        state=self.show();self.assertEqual(state['waiting'],997)
        self.assertEqual(len(self.manager.active),3)
        self.assertGreater(state['backlog_seconds'],400)
        for _ in range(500):self.time[0]+=1;state=self.show()
        counts=self.store.db.execute('SELECT display_state,count(*) FROM translation_jobs GROUP BY display_state').fetchall()
        self.assertEqual(sum(n for _,n in counts),1000)
        self.assertNotIn('cancelled',dict(counts))
