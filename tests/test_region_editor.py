from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

from PIL import Image
from region_geometry import *
from region_profiles import region_for,with_region,normalize_profiles,CROP_KEYS
from frame_sources import FramePacket,LatestFrames
from preview_service import SharedOCR
from region_editor import RegionEditor,ocr_on_region
from core import DEFAULTS,save_settings,load_settings
from obs_capture import ObsSource
from virtual_camera import CaptureConfigurationError


class GeometryTests(unittest.TestCase):
    def test_letterbox_roundtrip_and_resolution_invariance(self):
        rect=(.14,.61,.86,.91)
        for cw,ch in ((1000,600),(500,800),(1400,500)):
            coordinates=[]
            for iw,ih in ((1920,1080),(1280,720),(960,540)):
                v=Viewport.fit(cw,ch,iw,ih)
                x,y,x1,y1=v.rect(rect)
                observed=(*v.inverse(x,y),*v.inverse(x1,y1))
                for a,b in zip(rect,observed):self.assertAlmostEqual(a,b)
                coordinates.append((x,y,x1,y1))
            for coords in coordinates[1:]:
                for a,b in zip(coordinates[0],coords):self.assertAlmostEqual(a,b)

    def test_eight_handles_hit_and_resize(self):
        rect=(.2,.3,.8,.9);v=Viewport.fit(1000,600,1920,1080)
        for name,point in handle_points(rect).items():
            self.assertEqual(hit_test(v,rect,*v.point(*point)),name)
            resized=drag(rect,name,.04,-.03)
            self.assertAlmostEqual(resized[0],.24 if 'w' in name else .2)
            self.assertAlmostEqual(resized[2],.84 if 'e' in name else .8)
            self.assertAlmostEqual(resized[1],.27 if 'n' in name else .3)
            self.assertAlmostEqual(resized[3],.87 if 's' in name else .9)

    def test_move_clamps_and_preserves_size(self):
        rect=(.2,.3,.8,.9)
        moved=drag(rect,'move',10,-10)
        for a,b in zip(moved,(.4,0,1,.6)):self.assertAlmostEqual(a,b)
        self.assertEqual(hit_test(Viewport.fit(100,100,100,100),rect,50,50),'move')

    def test_crossing_handles_minimum_and_invalid_values(self):
        for name in HANDLES:
            valid_region(drag((.2,.3,.8,.9),name,10,-10))
        for rect in ((0,0,0,1),(0,0,1,float('nan')),(-.1,0,1,1),(0,0,True,1)):
            with self.assertRaises(ValueError):valid_region(rect)

    def test_reset_undo_and_no_aliasing(self):
        draft=RegionDraft((.1,.2,.8,.9));draft.change((.2,.3,.7,.8));draft.reset()
        self.assertEqual(draft.rect,DEFAULT_REGION)
        draft.undo();self.assertEqual(draft.rect,(.2,.3,.7,.8))
        draft.undo();self.assertEqual(draft.rect,(.1,.2,.8,.9))

    def test_crop_boxes_mapped_back_to_original_pixels(self):
        engine=MagicMock(return_value=SimpleNamespace(txts=['Hello'],scores=[.98],boxes=[[[0,0],[40,0],[40,20],[0,20]]]))
        result=ocr_on_region(Image.new('RGB',(1000,500)),(.2,.4,.8,.9),engine)
        self.assertEqual(engine.call_args.args[0].size,(600,250))
        self.assertEqual(result['boxes'][0][0],(200,200))
        self.assertEqual(result['boxes'][0][2],(240,220))


class ProfileTests(unittest.TestCase):
    def test_profiles_roundtrip_separate_games_without_cloud_fields(self):
        original=dict(DEFAULTS)
        first=with_region(original,'Game A',(.1,.2,.8,.9))
        second=with_region(first,'Game B',(.2,.3,.9,1))
        self.assertNotIn('game a',original['ocr_regions'])
        with tempfile.TemporaryDirectory() as folder,patch('core.config_folder',return_value=Path(folder)):
            save_settings(second);loaded=load_settings()
        self.assertEqual(region_for(loaded,'GAME A'),(.1,.2,.8,.9))
        self.assertEqual(region_for(loaded,'Game B'),(.2,.3,.9,1))
        self.assertEqual(region_for(loaded,'New Game'),DEFAULT_REGION)
        self.assertNotIn('budget_try',loaded)
        self.assertEqual(loaded['game'],'Game B')

    def test_legacy_settings_and_corrupt_profiles_ignore_cloud_fields(self):
        s=dict(DEFAULTS);s.update(game='Legacy',crop_top=50,crop_bottom=90)
        self.assertEqual(region_for(s,'Legacy'),(0,.5,1,.9))
        with tempfile.TemporaryDirectory() as folder,patch('core.config_folder',return_value=Path(folder)):
            (Path(folder)/'settings.json').write_text('{"budget_try": 123, "ocr_regions": []}')
            loaded=load_settings()
        self.assertNotIn('budget_try',loaded)
        self.assertEqual(loaded['ocr_regions'],{})

    def test_no_hidden_credentials_and_failed_save_keeps_file(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.config_folder',return_value=Path(folder)):
            save_settings({'game':'Original'})
            before=(Path(folder)/'settings.json').read_bytes()
            with self.assertRaises(ValueError):
                save_settings({'ocr_regions':{'x':{'name':'Game','rect':[0,.5,1,.9],'api_key':'dummy'}}})
            self.assertEqual((Path(folder)/'settings.json').read_bytes(),before)


class SharingTests(unittest.TestCase):
    def test_peek_neither_consumes_nor_requests_a_frame(self):
        source=MagicMock();source.read.return_value=Image.new('RGB',(100,100))
        frames=LatestFrames(lambda:source,threading.Event(),period=10)
        try:
            first=frames.read();consumed=frames.consumed
            for _ in range(20):self.assertEqual(frames.peek().sequence,first.sequence)
            self.assertEqual(frames.consumed,consumed)
            source.read.assert_called_once()
        finally:frames.close()

    def test_shared_ocr_initializes_once_and_serializes_calls(self):
        active=[False];calls=[]
        def engine(image):
            self.assertFalse(active[0]);active[0]=True;time.sleep(.01);calls.append(image);active[0]=False
        factory=MagicMock(return_value=engine);service=SharedOCR(factory)
        workers=[threading.Thread(target=service,args=(i,)) for i in range(3)]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        factory.assert_called_once();self.assertEqual(len(calls),3)

    def test_raw_preview_rejects_browser_display_camera_loop_and_own_windows(self):
        obs=ObsSource.__new__(ObsSource);obs.client=MagicMock();obs._validated=None
        for kind,settings in [('browser_source',{}),('monitor_capture',{}),('scene',{}),
                              ('dshow_input',{'video_device_id':'OBS Virtual Camera'}),
                              ('window_capture',{'window':'Preview:Qt:obs64.exe'})]:
            obs.client.get_input_settings.return_value=SimpleNamespace(input_kind=kind,input_settings=settings)
            with self.assertRaises(CaptureConfigurationError):obs.validate_raw_source('source')
        obs.client.get_input_settings.return_value=SimpleNamespace(input_kind='dshow_input',input_settings={'video_device_id':'card'})
        obs.client.get_source_filter_list.return_value.filters=[]
        obs.validate_raw_source('source')


@unittest.skipUnless(sys.platform=='win32','Windows Tk only')
class EditorWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.geometry('100x80+0+0')
        self.packet=FramePacket(Image.new('RGB',(1920,1080),'#344859'),1,0,0,1)
        self.provider=MagicMock(return_value=(self.packet,'Synthetic fixture'))
        self.save=MagicMock();self.closed=MagicMock();self.jobs=[]
        self.editor=RegionEditor(self.root,'Test Game',(.1,.5,.9,.9),self.provider,
            lambda:lambda _:SimpleNamespace(txts=['Read this.'],scores=[.98],boxes=[[[0,0],[50,0],[50,20],[0,20]]]),
            self.jobs.append,self.save,self.closed)
        self.root.update()

    def tearDown(self):
        self.editor.close();self.root.destroy()

    def tick(self):
        self.editor.window.after_cancel(self.editor.after_id)
        self.editor._tick();self.root.update_idletasks()

    def test_real_window_handles_letterbox_resize_pause_and_undo(self):
        e=self.editor
        self.assertTrue(e.window.winfo_viewable())
        self.assertEqual(len(e.canvas.find_withtag('handle')),8)
        original=e.draft.rect
        x,y=e.view.point(.5,.7)
        e._press(SimpleNamespace(x=x,y=y));e._motion(SimpleNamespace(x=x+30,y=y-10));e._release(None)
        self.assertTrue(e.paused);self.assertNotEqual(e.draft.rect,original)
        e.undo();self.assertEqual(e.draft.rect,original)
        e.window.geometry('800x620');self.root.update()
        self.assertEqual(e.draft.rect,original)
        e.reset();self.assertEqual(e.draft.rect,DEFAULT_REGION)
        e.undo();self.assertEqual(e.draft.rect,original)

    def test_ocr_snapshot_boxes_and_stale_result_after_edit(self):
        e=self.editor;e.test_ocr();self.assertTrue(e.paused)
        self.assertEqual(len(self.jobs),1)
        self.jobs.pop()();self.tick()
        self.assertEqual(e.result['texts'],['Read this.'])
        self.assertEqual(len(e.canvas.find_withtag('ocr_box')),1)
        e.test_ocr();e.reset();self.jobs.pop()();self.tick()
        self.assertIsNone(e.result)

    def test_cancel_does_not_save_and_ocr_completion_after_close_is_safe(self):
        e=self.editor;e.test_ocr();job=self.jobs.pop();e.cancel();job()
        self.save.assert_not_called();self.closed.assert_called_once()
        self.assertTrue(e.closed)

    def test_save_and_failed_save(self):
        self.save.side_effect=OSError('disk full');self.editor.save()
        self.assertFalse(self.editor.closed)
        self.save.side_effect=None;self.editor.save()
        self.assertTrue(self.editor.closed)
        self.assertEqual(self.save.call_args.args[0],(.1,.5,.9,.9))

    def test_pause_prevents_frame_changes_without_stopping_source(self):
        e=self.editor;e.toggle_pause();count=self.provider.call_count
        self.provider.return_value=(FramePacket(Image.new('RGB',(960,540)),2,0,0,1),'new')
        e.next_preview=0;self.tick()
        self.assertEqual(e.packet.sequence,1);self.assertEqual(self.provider.call_count,count)
        e.toggle_pause();self.tick();self.assertEqual(e.packet.sequence,2)


@unittest.skipUnless(sys.platform=='win32','Windows Tk only')
class ControllerTests(unittest.TestCase):
    def setUp(self):
        import app,tkinter as tk
        self.app=app;self.stack=ExitStack();self.folder=self.stack.enter_context(tempfile.TemporaryDirectory())
        for target in ('app.config_folder','core.config_folder'):
            self.stack.enter_context(patch(target,return_value=Path(self.folder)))
        self.stack.enter_context(patch('app.secret_get',return_value=''))
        self.stack.enter_context(patch('app.secret_save'))
        self.api=self.stack.enter_context(patch('app.WarmNMTClient'))
        self.obs=MagicMock();self.obs.frame.return_value=Image.new('RGB',(960,540),'#283038')
        def read():
            time.sleep(.015)
            self.obs.validate_raw_source('Raw input')
            return Image.new('RGB',(960,540),'#283038')
        self.obs.read.side_effect=read
        self.stack.enter_context(patch('app.VirtualCamera',return_value=self.obs))
        self.source_factory=self.stack.enter_context(patch.object(app.MainWindow,'_obs',return_value=self.obs))
        self.engine=MagicMock(return_value=SimpleNamespace(txts=['Follow me!'],scores=[.99],boxes=None))
        self.ocr_factory=self.stack.enter_context(patch('app.create_ocr',return_value=self.engine))
        self.root=tk.Tk();self.main=app.MainWindow(self.root)
        self.main.game.set('Game A');self.main.source.set('Raw input')
        self.main.camera_config.set('mock-collection.json')
        self.main.diagnostic_mode.set(True)
        self.root.update()

    def tearDown(self):
        self.main.close();self.root.mainloop()
        self.api.assert_not_called()
        self.stack.close()

    def wait(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertTrue(predicate())

    def test_preview_only_cancel_and_ocr_reuse_one_camera(self):
        before=dict(self.main.settings)
        self.main.open_region_editor();e=self.main.region_editor
        self.wait(lambda:e.packet is not None)
        self.source_factory.assert_called_once();self.ocr_factory.assert_not_called()
        e.test_ocr();self.wait(lambda:not e.in_test)
        self.assertEqual(e.result['texts'],['Follow me!'])
        e.test_ocr();self.wait(lambda:not e.in_test)
        self.ocr_factory.assert_called_once();self.source_factory.assert_called_once()
        e.cancel();self.wait(lambda:all(not w.is_alive() for w in self.main.workers))
        self.assertEqual(self.main.settings,before)
        self.assertFalse((Path(self.folder)/'settings.json').exists())
        self.obs.close.assert_called_once()

    def test_running_capture_editor_save_keeps_one_camera_and_current_roi(self):
        self.main.start();self.wait(lambda:self.main.capture_feed is not None and self.main.capture_feed.peek() is not None)
        feed=self.main.capture_feed
        self.main.open_region_editor();e=self.main.region_editor
        self.wait(lambda:e.packet is not None)
        self.assertIs(self.main.capture_feed,feed)
        self.assertIsNone(self.main.preview_stop)
        e.draft.change((.2,.4,.8,.9));e.save()
        self.assertTrue(self.main.running)
        count=self.engine.call_count
        self.wait(lambda:self.engine.call_count>count)
        self.assertEqual(self.engine.call_args.args[0].size,(960,156))
        self.source_factory.assert_called_once();self.obs.close.assert_not_called()
        self.assertEqual(self.main.settings['crop_top'],40)
        self.assertEqual(region_for(load_settings(),'Game A'),(.2,.4,.8,.9))

    def test_profile_restore_in_reopened_real_main_window(self):
        import tkinter as tk
        self.main.open_region_editor();e=self.main.region_editor
        e.draft.change((.2,.4,.8,.9));e.save()
        self.main.close();self.root.mainloop()
        self.root=tk.Tk();self.main=self.app.MainWindow(self.root);self.root.update()
        self.assertEqual(self.main.game.get(),'Game A')
        self.assertEqual(tuple(float(self.main.crop_vars[k].get())/100 for k in CROP_KEYS),(.2,.4,.8,.9))

    def test_failed_save_changes_neither_ui_settings_nor_profile(self):
        self.main.open_region_editor();e=self.main.region_editor
        before=dict(self.main.settings)
        e.draft.change((.2,.4,.8,.9))
        with patch('app.save_settings',side_effect=OSError('disk full')):e.save()
        self.assertFalse(e.closed);self.assertEqual(self.main.settings,before)
        self.assertEqual(float(self.main.crop_vars['crop_top'].get()),65)

    def test_profile_change_during_edit_rejected(self):
        self.main.open_region_editor();e=self.main.region_editor
        self.main.game.set('Other Game');e.save()
        self.assertFalse(e.closed);self.assertEqual(self.main.settings['ocr_regions'],{})

    def test_unsafe_source_never_published_and_no_fallback_camera(self):
        self.obs.validate_raw_source.side_effect=CaptureConfigurationError('Unsafe source')
        self.main.open_region_editor();e=self.main.region_editor
        self.wait(lambda:all(not w.is_alive() for w in self.main.workers))
        self.assertIsNone(e.packet);self.obs.frame.assert_not_called()
        self.source_factory.assert_called_once()

    def test_closing_main_waits_for_editor_ocr_without_late_tk_calls(self):
        entered=threading.Event();release=threading.Event()
        def slow(image):
            entered.set();release.wait(3)
            return SimpleNamespace(txts=['Done'],scores=[.99],boxes=None)
        self.ocr_factory.return_value=slow
        self.main.open_region_editor();e=self.main.region_editor
        self.wait(lambda:e.packet is not None)
        e.test_ocr();self.wait(entered.is_set)
        try:
            self.main.close();self.assertTrue(e.closed)
            self.assertTrue(any(w.is_alive() for w in self.main.workers))
        finally:release.set()
        self.root.mainloop()
