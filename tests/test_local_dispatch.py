from bootstrap import configure_paths
configure_paths()
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from ediz_game_translator.storage.subtitle_store import SubtitleStore
from ediz_game_translator.subtitles.subtitle_display import DisplayManager
from ediz_game_translator.translation.translation_dispatch import LocalTranslationCoordinator
from ediz_game_translator.translation.translation_memory import SafeTranslationMemory
from ediz_game_translator.translation.light_translation import LocalEngineError,WarmNMTClient,validate_capacity


class ConcurrentDispatchTests(unittest.TestCase):
    def setUp(self):self.store=SubtitleStore(':memory:')
    def tearDown(self):self.store.close()
    def add(self,text):
        now=time.monotonic()
        row=self.store.accept('s',text,now,now,0,now,.99,'test')
        return row,self.store.enqueue_translation('s',row,text,'local:ct2-marian',now)
    def settings(self):
        return dict(game='Test',local_python='unused',local_model_path='unused',local_device='cpu',
                    local_compute_type='int8',local_workers=2,local_threads=1)

    def test_warm_single_engine_parallel_results_do_not_block_behind_older_job(self):
        _,first=self.add('First.');_,second=self.add('Second.')
        stop=threading.Event();results=[];errors=[];engine=MagicMock();engine.closed=False
        def translate(text):
            time.sleep(.15 if text=='First.' else .01)
            return dict(text='Birinci.' if text=='First.' else 'İkinci.',complete=True,processing_ms=1)
        engine.translate.side_effect=translate
        def completed(job,text,*_):
            results.append(job['id'])
        factory=MagicMock(return_value=engine)
        c=LocalTranslationCoordinator(self.settings(),self.store,'s',stop,completed,errors.append,factory)
        t=threading.Thread(target=c.run);t.start()
        deadline=time.monotonic()+2
        while not results and time.monotonic()<deadline:time.sleep(.005)
        manager=DisplayManager(self.store,'s',ready_first=True)
        self.assertEqual([b['id'] for b in manager.snapshot()['blocks']],[second])
        deadline=time.monotonic()+2
        while len(results)<2 and time.monotonic()<deadline:time.sleep(.005)
        self.assertEqual([b['id'] for b in manager.snapshot()['blocks']],[second,first])
        stop.set();t.join(2);self.assertFalse(t.is_alive())
        self.assertEqual(results,[second,first]);factory.assert_called_once()
        self.assertEqual(c.peak_active,2);self.assertFalse(errors)
        self.assertNotIn('api_called',{r[1] for r in self.store.db.execute('PRAGMA table_info(translation_jobs)')})

    def test_same_utterance_revisions_never_run_concurrently(self):
        row,first=self.add('We should check the')
        self.store.claim_translation('s',time.monotonic())
        second=self.store.enqueue_translation('s',row,'We should check the station.','local:ct2-marian',time.monotonic())
        _,other=self.add('Go!')
        self.assertEqual(self.store.claim_translation('s',time.monotonic())['id'],other)
        self.assertIsNone(self.store.claim_translation('s',time.monotonic()))
        self.store.complete_translation(first,'Bakmalıyız',time.monotonic())
        self.assertEqual(self.store.claim_translation('s',time.monotonic())['id'],second)
        self.assertEqual(self.store.db.execute('SELECT display_state FROM translation_jobs WHERE id=?',(first,)).fetchone()[0],'skipped')

    def test_ready_order_three_slots_preserve_timers_and_all_jobs(self):
        jobs=[self.add(f'Line {i}.')[1] for i in range(5)]
        now=[10.]
        for j in jobs[1:]:self.store.complete_translation(j,'Hazır.',9,duration=10)
        d=DisplayManager(self.store,'s',clock=lambda:now[0],ready_first=True)
        s=d.snapshot();self.assertEqual([b['id'] for b in s['blocks']],jobs[1:4])
        for b in s['blocks']:d.ack(b['id'],'browser_dom_ack')
        now[0]=11;self.store.complete_translation(jobs[0],'Geç.',10,duration=10)
        s=d.snapshot();self.assertEqual([b['remaining'] for b in s['blocks']],[8.5,9,9])
        self.assertEqual(s['waiting'],2)
        now[0]=30;s=d.snapshot()
        self.assertEqual({b['id'] for b in s['blocks']},{jobs[0],jobs[4]})
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM translation_jobs').fetchone()[0],5)

    def test_browser_priority_native_ack_does_not_start_clock_early(self):
        _,job=self.add('Go!');self.store.complete_translation(job,'Git!',0,duration=10)
        now=[0.];d=DisplayManager(self.store,'s',clock=lambda:now[0],ready_first=True);d.browser_required=True
        d.snapshot();self.assertFalse(d.ack(job,'tk_render_submitted'))
        now[0]=2;self.assertEqual(d.snapshot()['blocks'][0]['remaining'],10)
        self.assertTrue(d.ack(job,'browser_dom_ack'));now[0]=3
        self.assertEqual(d.snapshot()['blocks'][0]['remaining'],9)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM render_acks').fetchone()[0],2)

    def test_capacity_and_missing_model_fail_without_cloud(self):
        with self.assertRaises(ValueError):validate_capacity(2,2,'cuda')
        with self.assertRaises(ValueError):validate_capacity(99,1,'cpu')
        from cloud_guard import NoCloudImports
        with NoCloudImports(),patch('ediz_game_translator.translation.light_translation.subprocess.Popen') as p:
            with self.assertRaises(LocalEngineError):WarmNMTClient('unused','missing-model')
            p.assert_not_called()

    def test_cancel_model_loading_terminates_child_without_waiting_for_load_timeout(self):
        stop=threading.Event();released=threading.Event();process=MagicMock()
        process.poll.return_value=None;process.terminate.side_effect=released.set
        def reader(client):released.wait(2)
        timer=threading.Timer(.05,stop.set);timer.start();began=time.monotonic()
        with patch('ediz_game_translator.translation.light_translation.model_manifest'),patch('pathlib.Path.is_file',return_value=True),patch('ediz_game_translator.translation.light_translation.subprocess.Popen',return_value=process),patch.object(WarmNMTClient,'_read',reader):
            with self.assertRaisesRegex(LocalEngineError,'kullanıcı'):WarmNMTClient('python','model',stop_event=stop)
        timer.join();self.assertLess(time.monotonic()-began,.7);process.terminate.assert_called_once()



class SafeMemoryTests(unittest.TestCase):
    def test_short_lines_never_automatically_cached(self):
        m=SafeTranslationMemory('Game','Model')
        for text in ('Right','Fine','Go'):
            m.remember(text,'MJ',['Before.'],'Tamam.')
            self.assertEqual(m.lookup(text,'MJ',['Before.']),(None,None))

    def test_long_cache_requires_same_speaker_game_and_context(self):
        text='We should leave the station now.'
        m=SafeTranslationMemory('Game','Model');m.remember(text,'MJ',['Before.'],'Gidelim.')
        self.assertEqual(m.lookup(text,'MJ',['Before.'])[0],'Gidelim.')
        self.assertIsNone(m.lookup(text,'Fisk',['Before.'])[0])
        self.assertIsNone(m.lookup(text,'MJ',['Different.'])[0])
        self.assertIsNone(SafeTranslationMemory('Other','Model').lookup(text,'MJ',['Before.'])[0])
