from bootstrap import configure_paths
configure_paths()
import unittest
from types import SimpleNamespace
from ediz_game_translator.capture.subtitle_tracking import ActiveSubtitles,split_speaker
from ediz_game_translator.capture.dialogue_filter import dialogue_candidates
from ediz_game_translator.capture.capture_pipeline import CaptureRunner,DiagnosticLog
from ediz_game_translator.capture.frame_sources import FramePacket
from ediz_game_translator.storage.subtitle_store import SubtitleStore


def result(texts,score=.99):
    return SimpleNamespace(txts=texts,scores=[score]*len(texts),boxes=None)


class FullOCRPathTests(unittest.TestCase):
    def run_frames(self,frames):
        s=SubtitleStore(':memory:');index=[0];sent=[]
        runner=CaptureRunner(lambda:FramePacket(None,index[0],index[0]*.08,100,0),
            lambda _:SimpleNamespace(width=960,height=160),lambda _:frames[index[0]],
            s,'s',DiagnosticLog(),lambda:None,lambda row,text,at:sent.append((row,text)))
        for i in range(len(frames)):index[0]=i;runner.step()
        return s,sent

    def test_short_real_speech_reaches_dispatch_from_ocr(self):
        for text in ('Go!','No!','Oh!','Hi!'):
            s,sent=self.run_frames([result([text])])
            try:self.assertEqual([text for _,text in sent],[text])
            finally:s.close()

    def test_thank_you_is_dialogue_not_a_person_label(self):
        for text in ('Thank You','Thank you.','MJ: Thank You'):
            s,sent=self.run_frames([result([text])])
            try:self.assertEqual([t for _,t in sent],[text])
            finally:s.close()

    def test_titles_and_initials_keep_speaker_boundaries(self):
        texts=['Mr. Fisk: Go!','Dr. Connors: No!','MJ: Hi!']
        s,sent=self.run_frames([result(texts)])
        try:
            self.assertEqual([t for _,t in sent],texts)
            self.assertEqual(s.db.execute('SELECT speaker FROM subtitles ORDER BY id').fetchall(),
                             [('Mr. Fisk',),('Dr. Connors',),('MJ',)])
        finally:s.close()

    def test_inline_titled_speakers_are_not_joined(self):
        cs,_=dialogue_candidates(result(['Mr. Fisk: Go! Dr. Connors: No! MJ: Hi!']),960,160)
        self.assertEqual([(c.speaker,c.body) for c in cs],[('Mr. Fisk','Go!'),('Dr. Connors','No!'),('MJ','Hi!')])

    def test_hud_and_short_random_noise_stay_rejected(self):
        cs,_=dialogue_candidates(result(['CLOSE','STOP','1757m','Yuri Watanabe','Xq!','a!']),960,160)
        self.assertEqual(cs,[])

    def test_go_stop_go_survives_actual_filter(self):
        s,sent=self.run_frames([result([x]) for x in ('Go!','Stop!','Go!')])
        try:
            self.assertEqual([t for _,t in sent],['Go!','Stop!','Go!'])
            self.assertEqual(len({r for r,_ in sent}),3)
        finally:s.close()

    def test_duplicate_glyph_variants_dispatch_once_in_full_path(self):
        s,sent=self.run_frames([result([x]) for x in
            ("MJ: I'll be fine. We should wait here.","MJ: Il be fine. We should wait here.","MJ: I'l be fine. We should wait here.")])
        try:self.assertEqual(len(sent),1)
        finally:s.close()

    def test_low_confidence_short_speech_needs_confirmation(self):
        s,sent=self.run_frames([result(['Go!'],.4),result(['Go!'],.8),result(['Go!'],.8)])
        try:self.assertEqual([t for _,t in sent],['Go!'])
        finally:s.close()

    def test_pending_extension_coalesces_and_speaker_change_does_not(self):
        s,sent=self.run_frames([result(['MJ: We should check the']),
                               result(['MJ: We should check the station.','Mr. Fisk: Go!'])])
        try:
            self.assertEqual(sent[0][0],sent[1][0])
            self.assertNotEqual(sent[1][0],sent[2][0])
            self.assertEqual(len(s.db.execute('SELECT id FROM subtitles').fetchall()),2)
        finally:s.close()
