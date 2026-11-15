import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from subtitle_tracking import ActiveSubtitles,equivalent,continuation
from subtitle_store import SubtitleStore
from capture_pipeline import CaptureRunner,DiagnosticLog
from frame_sources import FramePacket
from test_subtitle_tracking import candidate


class DedupRegressionTests(unittest.TestCase):
    def test_recorded_pronoun_glyph_variants_dispatch_once(self):
        for variants in (["I'll be fine. She will be relieved.","Il be fine. She will be relieved.","I'l be fine. She will be relieved."],
                         ["I've got a few minutes before work.","l've got a few minutes before work."]):
            tracker=ActiveSubtitles()
            actions=[tracker.update([candidate(v)],i*.28)[0] for i,v in enumerate(variants)]
            self.assertEqual(sum(a.dispatch for a in actions),1)

    def test_punctuation_and_semantic_boundaries(self):
        self.assertTrue(equivalent('Stay here, until morning.','Stay here until morning...'))
        self.assertTrue(equivalent('Please stay near the station!','Please stay near the station.'))
        self.assertTrue(equivalent('The "negative" part of you.','The “negative” part of you.'))
        for a,b in [('Go!','Go?'),('Il lives near the park.','Ill lives near the park.'),
                    ('Meet Will at the station.','Meet Jill at the station.'),
                    ('I will go.','I will not go.'),('Take 2.','Take 3.')]:
            self.assertFalse(equivalent(a,b),(a,b))

    def test_best_ocr_updates_only_unclaimed_work_without_dispatch(self):
        s=SubtitleStore(':memory:')
        try:
            row=s.accept('s','Original.',0,0,0,0,.99,'test')
            job=s.enqueue_translation('s',row,'Original.','gpt-6-luna',0)
            s.refresh_pending_source('s',row,'Best observed.')
            self.assertEqual(s.claim_translation('s',.1)['source'],'Best observed.')
            s.refresh_pending_source('s',row,'Late correction.')
            self.assertEqual(s.db.execute('SELECT id,source FROM translation_jobs').fetchall(),[(job,'Best observed.')])
        finally:s.close()

    def test_short_repeat_after_two_blank_frames_is_new(self):
        t=ActiveSubtitles();a=t.update([candidate('Go!')],0)[0]
        t.update([],.2);t.update([],.4)
        b=t.update([candidate('Go!')],.6)[0]
        self.assertNotEqual(a.track.key,b.track.key)
        self.assertTrue(b.dispatch)

    def test_single_dropout_does_not_duplicate_short_line(self):
        t=ActiveSubtitles();a=t.update([candidate('Go!')],0)[0]
        t.update([],.2);b=t.update([candidate('Go!')],.4)[0]
        self.assertEqual(a.track.key,b.track.key);self.assertFalse(b.dispatch)

    def test_same_speaker_A_B_A_are_distinct_utterances(self):
        t=ActiveSubtitles()
        actions=[t.update([candidate(v)],i*.2)[0] for i,v in enumerate(['Go!','Stop!','Go!'])]
        self.assertEqual(len({a.track.key for a in actions}),3)
        self.assertEqual(sum(a.dispatch for a in actions),3)
        self.assertEqual(actions[0].track.last_seen,0)

    def test_disjoint_comma_fragments_not_joined(self):
        self.assertIsNone(continuation('If the guard comes,','do not open the gate.'))

    def test_prefix_growth_coalesces_real_pipeline_queue(self):
        s=SubtitleStore(':memory:');i=[0]
        texts=['Voice-A: We should check the','Voice-A: We should check the station.']
        def ocr(_):return SimpleNamespace(txts=[texts[i[0]]],scores=[.99],boxes=None)
        runner=CaptureRunner(lambda:FramePacket(None,i[0],i[0]*.28,100,0),
            lambda _:SimpleNamespace(width=960,height=160),ocr,s,'s',DiagnosticLog(),lambda:None,
            lambda row,text,at:s.enqueue_translation('s',row,text,'gpt-6-luna',at))
        try:
            runner.step();i[0]=1;runner.step()
            rows=s.db.execute('SELECT source FROM translation_jobs').fetchall()
            self.assertEqual(rows,[(texts[1],)])
            self.assertEqual(s.db.execute('SELECT count(*) FROM subtitle_revisions').fetchone()[0],2)
        finally:s.close()

    def test_queue_dedup_is_per_utterance_and_idempotent_after_claim(self):
        s=SubtitleStore(':memory:')
        try:
            row=s.accept('s','Go!',0,0,0,0,.99,'test')
            j=s.enqueue_translation('s',row,'Go!','gpt-6-luna',0)
            s.claim_translation('s',.1)
            self.assertEqual(s.enqueue_translation('s',row,'Go!','gpt-6-luna',.2),j)
            # A real extension after claim must not mutate the in-flight source.
            j2=s.enqueue_translation('s',row,'Go! Stay close.','gpt-6-luna',.3)
            self.assertNotEqual(j,j2)
            row2=s.accept('s','Go!',1,1,1,1,.99,'test')
            self.assertNotEqual(s.enqueue_translation('s',row2,'Go!','gpt-6-luna',1),j)
        finally:s.close()

    def test_timing_stages_and_three_independent_counters(self):
        from subtitle_display import DisplayManager
        s=SubtitleStore(':memory:');clock=[2.]
        try:
            ids=[]
            for i in range(4):
                r=s.accept('s','Go!',0,0,0,.1,.99,'test')
                j=s.enqueue_translation('s',r,'Go!','gpt-6-luna',.1)
                s.claim_translation('s',.2);s.complete_translation(j,'Git!',.5,duration=10)
                s.record_timing(j,dict(prepare_ms=2,request_call_ms=290,result_ms=8,secret='hidden',total_ms=float('nan')))
                ids.append(j)
            d=DisplayManager(s,'s',clock=lambda:clock[0]);state=d.snapshot()
            self.assertEqual([b['id'] for b in state['blocks']],ids[:3])
            for j in ids[:3]:d.ack(j,'test')
            clock[0]=3;state=d.snapshot()
            self.assertEqual([b['remaining'] for b in state['blocks']],[8.5,9,9])
            metrics=s.session_metrics('s')['stages_ms']
            self.assertAlmostEqual(metrics['translation_queue_ms']['p50'],100)
            self.assertAlmostEqual(metrics['request_call_ms']['p50'],290)
            self.assertNotIn('secret',s.db.execute('SELECT metrics FROM translation_timings LIMIT 1').fetchone()[0])
        finally:s.close()

    def test_api_timing_without_network(self):
        from core import TranslationEngine,ContextMemory,BudgetLedger
        with patch('openai.OpenAI') as sdk:
            sdk.return_value.responses.create.return_value=SimpleNamespace(status='completed',output_text='Git!',usage=SimpleNamespace(input_tokens=10,output_tokens=2))
            e=TranslationEngine('offline','gpt-6-luna',ContextMemory('Test',''),BudgetLedger(0,1,10))
            e.translate('Go!')
            self.assertIn('request_call_ms',e.last_timing);self.assertIn('result_ms',e.last_timing)
            e.memory.remember(e.model,'Go!','Git!');e.translate('Go!')
            self.assertTrue(e.last_timing['cache_hit']);self.assertNotIn('request_call_ms',e.last_timing)
