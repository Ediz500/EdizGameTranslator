"""Daily-use transition regressions. No paid API or physical camera calls."""
from bootstrap import configure_paths
configure_paths()
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

from ediz_game_translator.core import DEFAULTS, load_settings
from ediz_game_translator.storage import region_profiles as profiles
from ediz_game_translator.capture import virtual_camera as camera


class TransitionTests(unittest.TestCase):
    def test_production_obs_client_has_no_screenshot_path(self):
        from ediz_game_translator.capture.obs_capture import ObsSource
        self.assertFalse(hasattr(ObsSource,'frame'))

    def test_legacy_capture_migrates_without_losing_user_data(self):
        with tempfile.TemporaryDirectory() as folder, patch('ediz_game_translator.core.config_folder',return_value=Path(folder)):
            old=deepcopy(DEFAULTS)
            old.update(capture_method='websocket',game='Legacy',crop_top=52,budget_try=321,
                       estimated_total_usd=1.25,token_total_in=987,lore='Existing note')
            (Path(folder)/'settings.json').write_text(json.dumps(old))
            loaded=load_settings()
        self.assertEqual(loaded['capture_method'],'virtual_camera')
        for key in ('game','crop_top','lore'):
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
        with patch('ediz_game_translator.capture.virtual_camera.obs_camera_index') as index:
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


@unittest.skipUnless(sys.platform=='win32','Windows Tk only')
class DailyGuiTests(unittest.TestCase):
    """Real controller, tracking, SQLite, local engine, HTTP and Tk. Mock I/O only."""
    def setUp(self):
        from ediz_game_translator import app
        import tkinter as tk
        import numpy as np
        self.app=app;self.stack=ExitStack()
        self.folder=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for target in ('ediz_game_translator.app.config_folder','ediz_game_translator.core.config_folder'):
            self.stack.enter_context(patch(target,return_value=self.folder))
        self.stack.enter_context(patch('ediz_game_translator.app.secret_get',return_value=''))
        self.secret_save=self.stack.enter_context(patch('ediz_game_translator.app.secret_save'))
        self.message=self.stack.enter_context(patch('ediz_game_translator.app.messagebox.showerror'))
        self.stack.enter_context(patch('ediz_game_translator.app.messagebox.showwarning'))
        self.obs=MagicMock()
        c=self.obs.client
        c.get_scene_collection_list.return_value.current_scene_collection_name='Test'
        c.get_virtual_cam_status.return_value.output_active=True
        c.get_input_settings.return_value=SimpleNamespace(input_kind='dshow_input',input_settings={'video_device_id':'raw-card'})
        c.get_source_filter_list.return_value.filters=[]
        self.stack.enter_context(patch.object(app.MainWindow,'_obs',return_value=self.obs))
        self.route=self.stack.enter_context(patch('ediz_game_translator.capture.virtual_camera.RouteLog')).return_value
        self.stack.enter_context(patch('ediz_game_translator.capture.virtual_camera.obs_camera_index',return_value=7))
        self.cap=MagicMock();pixels=np.zeros((540,960,3),dtype=np.uint8)
        def read():time.sleep(.015);return True,pixels
        self.cap.read.side_effect=read
        self.device=self.stack.enter_context(patch('cv2.VideoCapture',return_value=self.cap))
        self.ocr=self.stack.enter_context(patch('ediz_game_translator.app.create_ocr')).return_value
        self.ocr.return_value=SimpleNamespace(txts=['Follow me!'],scores=[.99],boxes=None)
        from cloud_guard import NoCloudImports
        self.cloud_guard=self.stack.enter_context(NoCloudImports())
        self.local=MagicMock();self.local.closed=False
        self.local.translate.return_value=dict(text='Beni takip et!',complete=True,processing_ms=1)
        self.local_factory=self.stack.enter_context(patch('ediz_game_translator.app.WarmNMTClient',return_value=self.local))
        self.stack.enter_context(patch('ediz_game_translator.app.model_manifest',return_value=(self.folder,{})))
        import customtkinter as ctk
        from ediz_game_translator.subtitles.overlay_server import launch_server
        self.stack.enter_context(patch('ediz_game_translator.app.launch_server',side_effect=lambda state:launch_server(state,0)))
        self.root=ctk.CTk();self.w=app.MainWindow(self.root)
        config={'name':'Test','virtual-camera':{'type2':2,'source':'Raw'},
                'sources':[{'name':'Raw','id':'dshow_input','settings':{'video_device_id':'raw-card'},'filters':[]}]}
        self.config=self.folder/'collection.json';self.config.write_text(json.dumps(config))
        self.w.camera_config.set(str(self.config));self.w.source.set('Raw')
        self.w.show_desktop.set(False);self.root.update()

    def tearDown(self):
        self.w.close();self.root.mainloop();self.stack.close()

    def wait(self,predicate,timeout=4):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_live_virtual_camera_to_local_engine_and_real_http_overlay(self):
        self.w.start()
        self.wait(lambda:self.w.overlay_state.current()=='Beni takip et!')
        self.assertTrue(self.w.running);self.assertEqual(self.w.start_btn['text'],'■  DURDUR')
        with urlopen(f'http://127.0.0.1:{self.w.server.server_port}/state',timeout=2) as r:
            self.assertEqual(json.load(r)['text'],'Beni takip et!')
        self.assertEqual(self.local.translate.call_count,1)
        self.assertEqual(self.cloud_guard.attempts,[])
        self.device.assert_called_once();self.obs.frame.assert_not_called()
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT status,translated FROM subtitles').fetchall(),[('translated','Beni takip et!')])

    def test_start_reloads_only_the_ediz_obs_browser_source(self):
        port=self.w.server.server_port;raw=self.obs.client.get_input_settings.return_value
        urls={'Ediz Türkçe Altyazı':f'http://127.0.0.1:{port}/overlay','Kick Chat':'https://chat.example.invalid/'}
        self.obs.client.get_input_list.return_value=SimpleNamespace(inputs=[{'inputName':n} for n in urls])
        self.obs.client.get_input_settings.side_effect=lambda name:(SimpleNamespace(input_kind='browser_source',
            input_settings={'url':urls[name]}) if name in urls else raw)
        self.w.start()
        self.wait(lambda:self.obs.client.press_input_properties_button.called)
        self.obs.client.press_input_properties_button.assert_any_call('Ediz Türkçe Altyazı','refreshnocache')
        self.assertNotIn(('Kick Chat','refreshnocache'),[c.args for c in self.obs.client.press_input_properties_button.call_args_list])
        for forbidden in ('set_input_settings','create_input','remove_input','set_current_program_scene','start_stream','stop_virtual_cam'):
            getattr(self.obs.client,forbidden).assert_not_called()

    def test_live_translation_refused_without_owned_overlay_port(self):
        self.w.server.shutdown();self.w.server.server_close();self.w.server=None
        self.w.start()
        self.assertFalse(self.w.running);self.message.assert_called()
        self.device.assert_not_called();self.local_factory.assert_not_called()

    def test_no_local_engine_if_route_cannot_be_verified(self):
        self.route.check.side_effect=camera.CaptureConfigurationError('Unsafe route')
        self.w.start();self.wait(lambda:not self.w.running)
        self.assertEqual(self.cloud_guard.attempts,[]);self.device.assert_not_called()
        self.assertEqual(self.w.overlay_state.current(),'')

    def test_simultaneous_speakers_have_separate_requests(self):
        self.ocr.return_value=SimpleNamespace(txts=['Scout: Stay close.','Pilot: I see them.'],scores=[.99,.99],
            boxes=[[[200,20],[760,20],[760,40],[200,40]],[[200,80],[760,80],[760,100],[200,100]]])
        self.w.start();requests=self.local.translate
        self.wait(lambda:requests.call_count==2)
        for call in requests.call_args_list:
            self.assertIn(call.args[0],('Stay close.','I see them.'))
        self.assertEqual(self.cloud_guard.attempts,[])
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM subtitles').fetchone()[0],2)

    def test_route_failure_during_slow_translation_clears_overlay_and_hides_result(self):
        entered=threading.Event();release=threading.Event()
        def slow(source):
            entered.set();release.wait(3)
            return dict(text='OLD',complete=True,processing_ms=1)
        self.local.translate.side_effect=slow
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

    def test_diagnostic_mode_never_constructs_cloud_sdk(self):
        self.w.diagnostic_mode.set(True);self.w.start()
        self.wait(lambda:self.ocr.call_count>=2)
        self.assertEqual(self.cloud_guard.attempts,[])
        self.assertEqual(self.w.overlay_state.current(),'')

    def test_five_pages_and_game_rename_save_restore_without_secret_writes(self):
        self.assertEqual(set(self.w.pages),{'Canlı Çeviri','Altyazı Tasarımı','Oyun Profilleri','Bağlantılar','Tanılama'})
        self.assertFalse(self.w.advanced_open.get())
        self.w._change_game('Another Game')
        self.w._change_game('Renamed Game',rename=True)
        self.assertEqual(load_settings()['game'],'Renamed Game')
        self.secret_save.assert_not_called()
        self.w.show_page('Bağlantılar');self.root.update()
        self.root.geometry('900x650');self.root.update()
        self.assertTrue(self.w.pages['Bağlantılar'].outer.winfo_viewable())
        self.assertFalse(self.w.pages['Canlı Çeviri'].outer.winfo_viewable())

    def test_game_save_failure_is_atomic_and_does_not_overwrite_profile(self):
        old=deepcopy(self.w.settings)
        with patch('ediz_game_translator.app.save_settings',side_effect=OSError('full')):
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

    def test_native_clock_waits_for_browser_when_both_renderers_are_active(self):
        self.w.overlay_state.set('Yerel görüntü',10)
        self.w.overlay_state.browser_seen=time.monotonic()
        self.w.overlay.enabled=True
        with patch.object(self.w.overlay,'render_blocks'):
            self.w.pump()
        state=self.w.overlay_state.snapshot()
        self.assertIsNone(state['blocks'][0]['started'])
        self.w.overlay_state.ack([state['blocks'][0]['id']],state['generation'])
        self.assertIsNotNone(self.w.overlay_state.snapshot()['blocks'][0]['started'])

    def test_legacy_cloud_preference_is_ignored_without_affecting_local_engine(self):
        entered=threading.Event();release=threading.Event()
        def slow(source):
            entered.set();release.wait(3)
            return dict(text='Çeviri',complete=True,processing_ms=1)
        self.local.translate.side_effect=slow
        self.w.start();self.wait(entered.is_set)
        try:
            self.w.settings['model']='obsolete-preference';self.w.save_preferences()
            self.ocr.return_value=SimpleNamespace(txts=['Head towards the bridge!'],scores=[.99],boxes=None)
        finally:release.set()
        self.wait(lambda:self.local.translate.call_count>=2)
        self.local_factory.assert_called_once();self.assertEqual(self.cloud_guard.attempts,[])
        self.assertNotIn('model',load_settings())

    def test_no_budget_component_is_needed_for_local_translation(self):
        self.assertFalse(hasattr(self.w,'ledger'))
        self.w.start()
        self.wait(lambda:self.w.overlay_state.current()=='Beni takip et!')
        self.assertTrue(self.w.running)
        self.assertEqual(self.cloud_guard.attempts,[])

    def test_ready_result_in_same_session_is_not_expired_by_ocr_generation(self):
        self.w.running=True;self.w.latest_seq=4;self.w.session_id=2
        self.w.post_session(2,'translated',4,'EXPIRED','Source',0,0,time.perf_counter()-10)
        self.w.pump()
        self.assertEqual(self.w.overlay_state.current(),'')
        self.assertEqual(self.w.last_translation_var.get(),'EXPIRED')

    def test_source_disappearance_removes_translation_but_preserves_history(self):
        self.w.start();self.wait(lambda:self.w.overlay_state.current()=='Beni takip et!')
        began=time.monotonic()
        self.ocr.return_value=SimpleNamespace(txts=[],scores=[],boxes=None)
        self.wait(lambda:self.w.overlay_state.current()=='',timeout=1)
        self.assertLess(time.monotonic()-began,.6)
        with closing(sqlite3.connect(self.folder/'subtitles.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT translated FROM translation_jobs').fetchone()[0],'Beni takip et!')

    def test_late_result_after_source_disappearance_never_reappears(self):
        entered=threading.Event();release=threading.Event()
        def slow(source):
            entered.set();release.wait(3)
            return dict(text='Late',complete=True,processing_ms=1)
        self.local.translate.side_effect=slow
        self.w.start();self.wait(entered.is_set)
        self.ocr.return_value=SimpleNamespace(txts=[],scores=[],boxes=None)
        self.wait(lambda:self.w.subtitle_store.db.execute('SELECT active FROM live_sources').fetchone()[0]==0)
        release.set()
        self.wait(lambda:self.w.subtitle_store.db.execute('SELECT translation_state FROM translation_jobs').fetchone()[0]=='completed')
        self.assertEqual(self.w.overlay_state.current(),'')

    def test_game_style_save_is_separate_from_obs_credentials_and_resets_preview(self):
        self.w.speaker_color.set('#FFD166');self.w.show_speaker.set(False)
        self.w.save_subtitle_style();self.secret_save.assert_not_called()
        self.w.show_speaker.set(True);self.w.reset_subtitle_style()
        self.assertFalse(self.w.show_speaker.get())
        self.assertEqual(self.w.overlay_state.snapshot()['style']['speaker_color'],'#FFD166')

    def test_window_and_widget_scaling_125_and_150_preserve_primary_controls(self):
        import customtkinter as ctk
        try:
            for scale in (1.25,1.5):
                ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale)
                self.root.geometry('1100x620');self.w.show_page('Canlı Çeviri');self.root.update()
                self.assertTrue(self.w.start_btn.winfo_viewable())
                right=self.w.start_btn.winfo_rootx()+self.w.start_btn.winfo_width()
                self.assertLessEqual(right,self.root.winfo_rootx()+self.root.winfo_width())
                for page in self.w.pages:
                    self.w.show_page(page);self.root.update()
                    self.assertTrue(self.w.pages[page].outer.winfo_viewable())
        finally:
            ctk.set_widget_scaling(1);ctk.set_window_scaling(1)

    def test_native_names_mask_and_resolution_scaling_use_shared_geometry(self):
        from ediz_game_translator.subtitles.canvas_view import draw_captions
        from ediz_game_translator.subtitles.layout import arrange_blocks
        from ediz_game_translator.storage.subtitle_styles import DEFAULT_STYLE
        c=self.w.style_canvas;style=dict(DEFAULT_STYLE)
        sample=dict(id=1,text='Burada kal.',speaker='Scout',bounds=[.2,.8,.8,.9],source_size=[960,540])
        blocks=arrange_blocks([sample],style);draw_captions(c,blocks,style,960,540)
        self.assertEqual(c.itemcget(c.find_withtag('mask')[0],'fill'),'#000000')
        self.assertEqual(c.itemcget(c.find_withtag('speaker')[0],'fill'),'#50E2BE')
        self.assertEqual(c.itemcget(c.find_withtag('dialogue')[0],'fill'),'#FFFFFF')
        small_font=c.itemcget(c.find_withtag('dialogue')[0],'font')
        sample['source_size']=[1920,1080]
        draw_captions(c,arrange_blocks([sample],style),style,960,540)
        self.assertEqual(c.itemcget(c.find_withtag('dialogue')[0],'font'),small_font)
        draw_captions(c,blocks,dict(style,show_speaker=False),960,540)
        self.assertFalse(c.find_withtag('speaker'))
        draw_captions(c,[],style,960,540);self.assertFalse(c.find_withtag('mask'))
