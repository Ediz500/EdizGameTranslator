import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from capture_pipeline import same_line
from dialogue_filter import dialogue_observation
from frame_sources import LatestFrames,FramePacket
from virtual_camera import validate_raw_source_config,VirtualCamera
from obs_capture import ObsSource


def box(x,y,w=400,h=30):
    return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]


class DialogueTests(unittest.TestCase):
    def test_spiderman_hud_is_not_dialogue(self):
        result=SimpleNamespace(txts=['CLOSE','STOP','Yuri Watanabe','1757m','OSCORP',
                                    'Spider-Man: We have to get moving.','Meet me outside.'],
            scores=[.99]*7,boxes=[box(100,10,80),box(1300,40,90),box(1400,80,240),
                box(1450,150,130),box(80,160,160),box(450,200,1000),box(600,240,700)])
        text,score,evidence=dialogue_observation(result,1920,313)
        self.assertEqual(text,'Spider-Man: We have to get moving. Meet me outside.')
        self.assertEqual(len(evidence['rejected']),5)

    def test_real_short_dialogue_not_removed(self):
        for text in ('Stop!','Close the door.','Yuri: Get down!','OSCORP is behind this.'):
            observed,_,_=dialogue_observation(SimpleNamespace(txts=[text],scores=[.99],boxes=[box(700,200)]),1920,313)
            self.assertEqual(observed,text)

    def test_separate_panel_not_joined(self):
        r=SimpleNamespace(txts=['Incoming call from Yuri','Peter: I am on my way.'],scores=[.99,.98],
                          boxes=[box(1250,20,300),box(500,210,920)])
        text,_,evidence=dialogue_observation(r,1920,313)
        self.assertEqual(text,'Peter: I am on my way.')
        self.assertEqual(evidence['rejected'][0]['reason'],'separate_text_cluster')

    def test_punctuation_noise_but_not_meaning_changes(self):
        for a,b in [('Wait here.','Wait here...'),('Wait, here.','Wait here'),("We're ready.",'We’re ready,')]:
            self.assertTrue(same_line(a,b),(a,b))
        for a,b in [('Were here?',"We're here."),('Stop.','Stop?'),('Take 10.','Take 11.'),
                    ('Go east.','Go west.'),('I can go.',"I can't go.")]:
            self.assertFalse(same_line(a,b),(a,b))


class CaptureTests(unittest.TestCase):
    def test_cpu_profile_bounds_detector_and_disables_rotation_classifier(self):
        from ocr_profiles import create_ocr
        with patch('rapidocr.RapidOCR') as factory:
            create_ocr('bounded960_cpu2')
        p=factory.call_args.kwargs['params']
        self.assertEqual(p['Det.limit_type'],'max')
        self.assertEqual(p['Det.limit_side_len'],960)
        self.assertFalse(p['Global.use_cls'])
        self.assertEqual(p['EngineConfig.onnxruntime.intra_op_num_threads'],2)

    def test_invalid_profile_and_resolution_fail_closed(self):
        from ocr_profiles import create_ocr
        with self.assertRaises(ValueError):create_ocr('automatic_gpu')
        with self.assertRaises(ValueError):ObsSource('dummy',width=800)

    def test_demo_cannot_feed_diagnostic_camera(self):
        import app
        w=app.MainWindow.__new__(app.MainWindow)
        w.running=True; w.diagnostic_active=True; w.status_var=MagicMock()
        with patch.object(w,'prepare') as prepare:
            w.demo()
        prepare.assert_not_called()

    def test_resolution_contract(self):
        # Historical benchmark contract, deliberately outside the application.
        from legacy_capture import LegacyObsSource as ObsSource
        sdk=MagicMock()
        with patch.dict('sys.modules',{'obsws_python':sdk}):
            for width in (1920,1280,960):
                obs=ObsSource('dummy',width=width)
                # Deliberately stop after SDK call; this test checks dimensions only.
                sdk.ReqClient.return_value.get_source_screenshot.side_effect=RuntimeError('sent')
                with self.assertRaises(RuntimeError):obs.frame('raw')
                sdk.ReqClient.return_value.get_source_screenshot.assert_called_with('raw','png',width,width*9//16,-1)

    def test_latest_mailbox_bounded_skips_counted_and_no_parallel_reads(self):
        stop=threading.Event(); source=MagicMock(); count=[0]; in_read=[False]
        def read():
            self.assertFalse(in_read[0]); in_read[0]=True
            count[0]+=1
            in_read[0]=False
            return count[0]
        source.read.side_effect=read
        frames=LatestFrames(lambda:source,stop,.002)
        try:
            first=frames.read()
            time.sleep(.035)  # Simulates OCR occupied while capture continues.
            second=frames.read()
            self.assertGreater(second.sequence,first.sequence+1)
            self.assertEqual(second.skipped,second.sequence-first.sequence-1)
            self.assertIsInstance(second,FramePacket)
            self.assertLess(time.perf_counter()-second.captured_mono,.15)
            self.assertFalse(hasattr(frames,'queue'))
        finally:frames.close()
        source.close.assert_called_once()
        self.assertFalse(frames.thread.is_alive())
        with self.assertRaises(InterruptedError):frames.read()

    def test_producer_failure_propagated(self):
        source=MagicMock(); source.read.side_effect=RuntimeError('device lost')
        frames=LatestFrames(lambda:source,threading.Event())
        try:
            with self.assertRaises(RuntimeError):frames.read()
        finally:frames.close()

    def test_one_second_dialogue_sampling_simulation(self):
        # Artificial 1-second lines every 2 seconds, not measured game recall.
        lines=[(2*i+.3,2*i+1.3) for i in range(20)]
        def coverage(period):
            samples=[i*period for i in range(200)]
            return sum(any(a<=t<b for t in samples) for a,b in lines)
        self.assertLess(coverage(2.559),20)
        self.assertEqual(coverage(.476),20)
        self.assertEqual(coverage(.28),20)


class CameraSafetyTests(unittest.TestCase):
    def config(self):
        return {'name':'Test','virtual-camera':{'type2':2,'source':'Raw'},
                'sources':[{'name':'Raw','id':'dshow_input','settings':{'video_device_id':'capture-card'},'filters':[]}]}

    def test_program_preview_scene_browser_monitor_and_feedback_rejected(self):
        for mode in (0,1,3,4):
            d=self.config(); d['virtual-camera']['type2']=mode
            with self.assertRaises(ValueError):validate_raw_source_config(d,'Raw')
        for kind in ('browser_source','monitor_capture','scene'):
            d=self.config(); d['sources'][0]['id']=kind
            with self.assertRaises(ValueError):validate_raw_source_config(d,'Raw')
        d=self.config(); d['sources'][0]['settings']['video_device_id']='OBS Virtual Camera'
        with self.assertRaises(ValueError):validate_raw_source_config(d,'Raw')

    def test_filters_and_source_mismatch_rejected(self):
        d=self.config(); d['sources'][0]['filters']=[{'enabled':True}]
        with self.assertRaises(ValueError):validate_raw_source_config(d,'Raw')
        with self.assertRaises(ValueError):validate_raw_source_config(self.config(),'Other')

    def test_cannot_open_translation_without_live_guard(self):
        with patch('virtual_camera.obs_camera_index') as camera:
            with self.assertRaises(ValueError):VirtualCamera('missing','Raw',diagnostic=False)
            with self.assertRaises(ValueError):VirtualCamera('missing','Raw',width=800,diagnostic=True)
        camera.assert_not_called()

    def test_named_device_and_route_recheck_no_fallback(self):
        import cv2,numpy as np
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json'; path.write_text(json.dumps(self.config()))
            cap=MagicMock(); cap.read.return_value=(True,np.zeros((20,30,3),dtype=np.uint8))
            with patch('virtual_camera.obs_camera_index',return_value=4),patch('cv2.VideoCapture',return_value=cap) as factory:
                camera=VirtualCamera(path,'Raw',diagnostic=True)
                self.assertEqual(camera.read().size,(30,20))
                factory.assert_called_once_with(4,cv2.CAP_DSHOW)
                d=self.config(); d['virtual-camera']['type2']=3
                path.write_text(json.dumps(d))
                with self.assertRaises(ValueError):camera.read()
                camera.close()
                self.assertEqual(cap.read.call_count,1)
