"""Daily-use transition regressions. No paid API or physical camera calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
import sqlite3
from contextlib import ExitStack,closing
from urllib.request import urlopen
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from core import DEFAULTS, load_settings
import region_profiles as profiles
import virtual_camera as camera


class TransitionTests(unittest.TestCase):
    def test_production_obs_client_has_no_screenshot_path(self):
        from obs_capture import ObsSource
        self.assertFalse(hasattr(ObsSource,'frame'))

    def test_legacy_capture_migrates_without_losing_user_data(self):
        with tempfile.TemporaryDirectory() as folder, patch('core.config_folder',return_value=Path(folder)):
            old=deepcopy(DEFAULTS)
            old.update(capture_method='websocket',game='Legacy',crop_top=52,budget_try=321,
                       estimated_total_usd=1.25,token_total_in=987,lore='Existing note')
            (Path(folder)/'settings.json').write_text(json.dumps(old))
            loaded=load_settings()
        self.assertEqual(loaded['capture_method'],'virtual_camera')
        for key in ('game','crop_top','budget_try','estimated_total_usd','token_total_in','lore'):
            self.assertEqual(loaded[key],old[key])

    def test_rename_preserves_region_and_rejects_collision(self):
        original=profiles.with_region(deepcopy(DEFAULTS),'Old',(.1,.2,.8,.9))
        renamed=profiles.rename_game(original,'Old','New')
        self.assertEqual(profiles.region_for(renamed,'New'),(.1,.2,.8,.9))
        self.assertNotIn('old',renamed['ocr_regions'])
        self.assertIn('old',original['ocr_regions'])
        with self.assertRaises(ValueError):profiles.rename_game(renamed,'New',' ')
        second=profiles.with_region(renamed,'Other',(0,.5,1,.9))
        with self.assertRaises(ValueError):profiles.rename_game(second,'New','Other')

    def test_route_log_detects_unsaved_program_change(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'obs.txt'
            p.write_text('12:00:00.001: Starting Virtual Camera output to Source : Raw\n',encoding='utf-8')
            guard=camera.RouteLog(p)
            guard.check('Raw')
            with p.open('a',encoding='utf-8') as f:f.write('12:00:00.002: Changing Virtual Camera output to Program\n')
            with self.assertRaises(camera.CaptureConfigurationError):guard.check('Raw')

    def test_missing_partial_or_truncated_route_proof_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'obs.txt';p.write_text('unrelated\n')
            guard=camera.RouteLog(p)
            with self.assertRaises(ValueError):guard.check('Raw')
            with p.open('a') as f:f.write('12: Starting Virtual Camera output to Source : Raw\n')
            guard.check('Raw')
            with p.open('a') as f:f.write('12: Changing Virtual Camera output to Pro')
            with self.assertRaises(ValueError):guard.check('Raw')
            p.write_text('x')
            with self.assertRaises(ValueError):guard.check('Raw')

    def test_live_camera_needs_live_validator_before_device_open(self):
        with patch('virtual_camera.obs_camera_index') as index:
            with self.assertRaises(camera.CaptureConfigurationError):
                camera.VirtualCamera('missing','Raw',diagnostic=False)
        index.assert_not_called()

    def test_guard_checks_live_source_even_inside_old_cache_window(self):
        obs=MagicMock()
        obs.client.get_scene_collection_list.return_value.current_scene_collection_name='Test'
        obs.client.get_virtual_cam_status.return_value.output_active=True
        obs.client.get_input_settings.return_value=SimpleNamespace(input_kind='dshow_input',input_settings={'video_device_id':'card'})
        obs.client.get_source_filter_list.return_value.filters=[]
        route=MagicMock()
        guard=camera.LiveObsGuard(obs,route=route)
        guard('Test','Raw')
        obs.client.get_source_filter_list.return_value.filters=[{'filterEnabled':True}]
        with self.assertRaises(ValueError):guard('Test','Raw')
        self.assertGreaterEqual(route.check.call_count,2)

    def test_active_collection_discovery_and_ambiguous_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'APPDATA':folder}):
            d=Path(folder)/'obs-studio'/'basic'/'scenes';d.mkdir(parents=True)
            (d/'active.json').write_text('{"name":"Active"}')
            obs=MagicMock();obs.client.get_scene_collection_list.return_value.current_scene_collection_name='Active'
            self.assertEqual(camera.resolve_collection_path(obs),d/'active.json')
            (d/'copy.json').write_text('{"name":"Active"}')
            with self.assertRaises(ValueError):camera.resolve_collection_path(obs)

    def test_installed_openai_sdk_serializes_sol_contract_without_network(self):
        import httpx2 as httpx
        import openai
        from core import TranslationEngine,BudgetLedger,ContextMemory
        requests=[];original=openai.OpenAI
        def reply(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200,json=dict(id='resp_offline',object='response',created_at=0,
                status='completed',model='gpt-6.1-sol',output=[dict(type='message',id='msg_local',role='assistant',
                status='completed',content=[dict(type='output_text',text='Beni takip et!',annotations=[])])],
                usage=dict(input_tokens=100,output_tokens=10,total_tokens=110)))
        client=httpx.Client(transport=httpx.MockTransport(reply))
        with patch('openai.OpenAI',side_effect=lambda **kw:original(**kw,http_client=client)):
            ledger=BudgetLedger(0,1,10)
            engine=TranslationEngine('offline-test-key','gpt-6.1-sol',ContextMemory('Test',''),ledger)
            try:translated,usage=engine.translate('Follow me!')
            finally:engine.client.close()
        self.assertEqual(translated,'Beni takip et!')
        self.assertEqual(len(requests),1)
        req=requests[0]
        self.assertEqual((req['model'],req['reasoning'],req['store'],req['service_tier']),
                         ('gpt-6.1-sol',{'effort':'low'},False,'default'))
        self.assertEqual(req['max_output_tokens'],250)
        self.assertFalse(ledger.blocked)

    def test_incomplete_response_charged_but_not_used_as_subtitle(self):
        from core import TranslationEngine,BudgetLedger,ContextMemory
        sdk=MagicMock();sdk.OpenAI.return_value.responses.create.return_value=SimpleNamespace(
            status='incomplete',output_text='Half',usage=SimpleNamespace(input_tokens=100,output_tokens=250))
        ledger=BudgetLedger(0,1,10)
        with patch.dict(sys.modules,{'openai':sdk}):
            engine=TranslationEngine('offline','gpt-6.1-sol',ContextMemory('Test',''),ledger)
            with self.assertRaises(RuntimeError):engine.translate('Follow me!')
        self.assertGreater(ledger.usd,0);self.assertFalse(ledger.pending)


@unittest.skipUnless(sys.platform=='win32','Windows Tk only')
class DailyGuiTests(unittest.TestCase):
    """Real controller, tracking, SQLite, budget, HTTP and Tk. Mock I/O only."""
    def setUp(self):
        import app,tkinter as tk,numpy as np
        self.app=app;self.stack=ExitStack()
        self.folder=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for target in ('app.config_folder','core.config_folder'):
            self.stack.enter_context(patch(target,return_value=self.folder))
        self.stack.enter_context(patch('app.secret_get',return_value=''))
        self.secret_save=self.stack.enter_context(patch('app.secret_save'))
        self.message=self.stack.enter_context(patch('app.messagebox.showerror'))
        self.stack.enter_context(patch('app.messagebox.showwarning'))
        self.obs=MagicMock()
        c=self.obs.client
        c.get_scene_collection_list.return_value.current_scene_collection_name='Test'
        c.get_virtual_cam_status.return_value.output_active=True
        c.get_input_settings.return_value=SimpleNamespace(input_kind='dshow_input',input_settings={'video_device_id':'raw-card'})
        c.get_source_filter_list.return_value.filters=[]
        self.stack.enter_context(patch.object(app.MainWindow,'_obs',return_value=self.obs))
        self.route=self.stack.enter_context(patch('virtual_camera.RouteLog')).return_value
        self.stack.enter_context(patch('virtual_camera.obs_camera_index',return_value=7))
        self.cap=MagicMock();pixels=np.zeros((540,960,3),dtype=np.uint8)
        def read():time.sleep(.015);return True,pixels
        self.cap.read.side_effect=read
        self.device=self.stack.enter_context(patch('cv2.VideoCapture',return_value=self.cap))
        self.ocr=self.stack.enter_context(patch('app.create_ocr')).return_value
        self.ocr.return_value=SimpleNamespace(txts=['Follow me!'],scores=[.99],boxes=None)
        self.sdk=MagicMock()
        self.sdk.OpenAI.return_value.responses.create.return_value=SimpleNamespace(
            status='completed',output_text='Beni takip et!',usage=SimpleNamespace(input_tokens=100,output_tokens=10))
        self.stack.enter_context(patch.dict(sys.modules,{'openai':self.sdk}))
        self.root=tk.Tk();self.w=app.MainWindow(self.root)
        config={'name':'Test','virtual-camera':{'type2':2,'source':'Raw'},
                'sources':[{'name':'Raw','id':'dshow_input','settings':{'video_device_id':'raw-card'},'filters':[]}]}
        self.config=self.folder/'collection.json';self.config.write_text(json.dumps(config))
        self.w.camera_config.set(str(self.config));self.w.source.set('Raw');self.w.api_key.set('offline-test-key')
        self.w.show_desktop.set(False);self.root.update()

    def tearDown(self):
        self.w.close();self.root.mainloop();self.stack.close()

    def wait(self,predicate,timeout=4):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_live_virtual_camera_to_fake_api_and_real_http_overlay(self):
        self.w.start()
        self.wait(lambda:self.w.overlay_state.current()=='Beni takip et!')
        self.assertTrue(self.w.running);self.assertEqual(self.w.start_btn['text'],'■  DURDUR')
        with urlopen('http://127.0.0.1:8788/state',timeout=2) as r:
            self.assertEqual(json.load(r)['text'],'Beni takip et!')
        self.assertEqual(self.sdk.OpenAI.return_value.responses.create.call_count,1)
        self.device.assert_called_once();self.obs.frame.assert_not_called()
        self.assertGreater(self.w.ledger.usd,0);self.assertFalse(self.w.ledger.pending)
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT status,translated FROM subtitles').fetchall(),[('translated','Beni takip et!')])

    def test_no_api_client_if_route_cannot_be_verified(self):
        self.route.check.side_effect=camera.CaptureConfigurationError('Unsafe route')
        self.w.start();self.wait(lambda:not self.w.running)
        self.sdk.OpenAI.assert_not_called();self.device.assert_not_called()
        self.assertEqual(self.w.overlay_state.current(),'')

    def test_simultaneous_speakers_have_separate_requests(self):
        self.ocr.return_value=SimpleNamespace(txts=['Scout: Stay close.','Pilot: I see them.'],scores=[.99,.99],
            boxes=[[[200,20],[760,20],[760,40],[200,40]],[[200,80],[760,80],[760,100],[200,100]]])
        self.w.start();requests=self.sdk.OpenAI.return_value.responses.create
        self.wait(lambda:requests.call_count==2)
        for call in requests.call_args_list:
            current=call.kwargs['input'].split('YENİ İNGİLİZCE ALTYAZI:\n')[-1]
            self.assertNotEqual('Scout:' in current,'Pilot:' in current)
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subtitles').fetchone()[0],2)

    def test_route_failure_during_slow_api_clears_overlay_and_hides_result(self):
        entered=threading.Event();release=threading.Event()
        def slow(**kw):
            entered.set();release.wait(3)
            return SimpleNamespace(status='completed',output_text='OLD',usage=SimpleNamespace(input_tokens=100,output_tokens=10))
        self.sdk.OpenAI.return_value.responses.create.side_effect=slow
        self.w.start();self.wait(entered.is_set)
        before=self.ocr.call_count
        self.wait(lambda:self.ocr.call_count>before)  # Capture/OCR did not wait for AI.
        self.route.check.side_effect=camera.CaptureConfigurationError('Route changed')
        try:self.wait(lambda:self.w.stop_evt.is_set())
        finally:release.set()
        self.wait(lambda:all(not t.is_alive() for t in self.w.workers))
        self.assertEqual(self.w.overlay_state.current(),'')
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT translation_state,display_state,cancel_reason FROM translation_jobs').fetchone(),('completed','cancelled','source_lost'))

    def test_diagnostic_mode_never_constructs_api(self):
        self.w.diagnostic_mode.set(True);self.w.start()
        self.wait(lambda:self.ocr.call_count>=2)
        self.sdk.OpenAI.assert_not_called()
        self.assertEqual(self.w.overlay_state.current(),'')

    def test_two_pages_and_game_rename_save_restore_without_secret_writes(self):
        self.assertEqual(set(self.w.pages),{'Ana Sayfa','Ayarlar'})
        self.assertFalse(self.w.advanced_open.get())
        self.w._change_game('Another Game')
        self.w._change_game('Renamed Game',rename=True)
        self.assertEqual(load_settings()['game'],'Renamed Game')
        self.secret_save.assert_not_called()
        self.w.show_page('Ayarlar');self.root.update()
        self.root.geometry('900x650');self.root.update()
        self.assertTrue(self.w.pages['Ayarlar'].outer.winfo_viewable())
        self.assertFalse(self.w.pages['Ana Sayfa'].outer.winfo_viewable())

    def test_game_save_failure_is_atomic_and_does_not_overwrite_profile(self):
        old=deepcopy(self.w.settings)
        with patch('app.save_settings',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.w._change_game('New')
        self.assertEqual(self.w.settings,old)
        self.assertEqual(self.w.game.get(),old['game'])

    def test_manual_pump_then_close_leaves_no_pump_timer(self):
        self.w.pump();first=self.w.pump_after
        self.w.pump();second=self.w.pump_after
        self.assertNotIn(first,self.root.tk.call('after','info'))
        self.w.close()
        remaining=self.root.tk.call('after','info')
        self.assertNotIn(first,remaining);self.assertNotIn(second,remaining)

    def test_native_read_clock_starts_even_if_unacknowledged_browser_is_polling(self):
        self.w.overlay_state.set('Yerel görüntü',10)
        self.w.overlay_state.browser_seen=time.monotonic()
        self.w.overlay.enabled=True
        with patch.object(self.w.overlay,'render_blocks'):
            self.w.pump()
        self.assertIsNotNone(self.w.overlay_state.snapshot()['blocks'][0]['started'])

    def test_model_changes_apply_next_session_without_mixing_active_job_prices(self):
        entered=threading.Event();release=threading.Event()
        def slow(**kw):
            entered.set();release.wait(3)
            return SimpleNamespace(status='completed',output_text='Çeviri',usage=SimpleNamespace(input_tokens=100,output_tokens=10))
        self.sdk.OpenAI.return_value.responses.create.side_effect=slow
        self.w.start();self.wait(entered.is_set)
        try:
            self.w.model.set('gpt-6.1-terra');self.w.save_preferences()
            self.ocr.return_value=SimpleNamespace(txts=['Head towards the bridge!'],scores=[.99],boxes=None)
        finally:release.set()
        self.wait(lambda:self.sdk.OpenAI.return_value.responses.create.call_count>=2)
        self.assertTrue(all(c.kwargs['model']=='gpt-6-luna' for c in self.sdk.OpenAI.return_value.responses.create.call_args_list))
        self.assertEqual(self.w.settings['model'],'gpt-6.1-terra')

    def test_locked_budget_prevents_live_camera_and_api_start(self):
        self.w.ledger.blocked=True
        self.w.start()
        self.assertFalse(self.w.running)
        self.device.assert_not_called();self.sdk.OpenAI.assert_not_called()

    def test_ready_result_in_same_session_is_not_expired_by_ocr_generation(self):
        self.w.running=True;self.w.latest_seq=4;self.w.session_id=2
        self.w.post_session(2,'translated',4,'EXPIRED','Source',0,0,time.perf_counter()-10)
        self.w.pump()
        self.assertEqual(self.w.overlay_state.current(),'')
        self.assertEqual(self.w.last_translation_var.get(),'EXPIRED')

    def test_translation_survives_old_five_second_policy_and_ocr_disappearance(self):
        self.w.settings['translation_max_age']=.01
        def response(**kw):
            time.sleep(.08)
            return SimpleNamespace(status='completed',output_text='Late',usage=SimpleNamespace(input_tokens=100,output_tokens=10))
        self.sdk.OpenAI.return_value.responses.create.side_effect=response
        self.w.start();self.wait(lambda:self.sdk.OpenAI.return_value.responses.create.call_count>0)
        def saved():
            with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
                return db.execute('SELECT status FROM subtitles').fetchone()[0]=='translated'
        self.wait(saved)
        self.assertFalse(self.w.ledger.pending)
        self.w.latest_seq+=1
        self.w.post_session(self.w.session_id,'clear',self.w.latest_seq)
        self.root.update()
        self.assertEqual(self.w.overlay_state.current(),'Late')
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT status FROM subtitles').fetchone()[0],'translated')
