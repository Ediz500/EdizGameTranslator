"""Real pipeline regressions with local synthetic pixels; no game recording."""
from bootstrap import configure_paths
configure_paths()
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image, ImageDraw, ImageFont
from ediz_game_translator.capture.capture_pipeline import CaptureRunner, DiagnosticLog
from ediz_game_translator.capture.source_evidence import SourceEvidence, narrow_glyph_variant
from ediz_game_translator.capture.subtitle_tracking import ActiveSubtitles, Candidate
from ediz_game_translator.storage.subtitle_store import SubtitleStore
from ediz_game_translator.subtitles.overlay_server import SharedOverlayState


LINE='Scout: I think we should leave now.'
BOX=[[20,50],[650,50],[650,88],[20,88]]


def picture(text=LINE):
    image=Image.new('RGB',(960,540),(65,70,75))
    ImageDraw.Draw(image).text((22,52),text,font=ImageFont.load_default(size=22),
                              fill='white',stroke_width=2,stroke_fill='black')
    return image


class EvidencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.now=[100.];self.image=picture();self.texts=[LINE];self.jobs=[]
        self.store=SubtitleStore(':memory:')
        self.clock=patch('ediz_game_translator.capture.capture_pipeline.time.perf_counter',side_effect=lambda:self.now[0])
        self.clock.start()
        def accepted(row,text,now):
            self.jobs.append(self.store.enqueue_translation('s',row,text,'local:ct2-marian',now))
        self.runner=CaptureRunner(lambda:self.image,lambda im:im,
            lambda im:SimpleNamespace(txts=self.texts[:],scores=[.99]*len(self.texts),boxes=[BOX]*len(self.texts)),
            self.store,'s',DiagnosticLog(),lambda:None,accepted,live=True)
        self.state=SharedOverlayState();self.state.bind(self.store,'s',live=True)
        self.state.manager.clock=lambda:self.now[0]

    def tearDown(self):
        self.state.close();self.store.close();self.clock.stop()

    def step(self,dt=0):
        self.now[0]+=dt;self.runner.step();return self.snapshot()

    def snapshot(self):return json.loads(self.state.json())['blocks']

    def ready(self):
        self.step();self.store.complete_translation(self.jobs[-1],'Buradan ayrılmalıyız.',self.now[0])
        return self.snapshot()[0]

    def test_several_blank_ocr_frames_keep_same_job_mask_and_position(self):
        first=self.ready();self.texts=[]
        for _ in range(3):
            block=self.step(.1)[0]
            self.assertEqual(block['id'],first['id'])
            for key in ('mask_rect','body_rect','name_rect','started'):self.assertEqual(block[key],first[key])
        self.texts=[LINE];self.assertEqual(self.step(.1)[0]['id'],first['id'])
        self.assertEqual(len(self.jobs),1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM ocr_frames WHERE raw_texts=?',('[]',)).fetchone()[0],3)

    def test_glyph_noise_needs_pixels_and_keeps_raw_ocr(self):
        first=self.ready()
        for glyph in ('l','Il','l','Il'):
            self.texts=[LINE.replace('I think',glyph+' think')]
            self.assertEqual(self.step(.1)[0]['id'],first['id'])
        self.assertEqual(len(self.jobs),1)
        self.assertEqual(self.store.db.execute('SELECT raw_texts FROM ocr_frames ORDER BY id DESC').fetchone()[0],json.dumps(self.texts,ensure_ascii=False))
        self.assertEqual(self.store.db.execute('SELECT canonical FROM live_sources').fetchone()[0],LINE)

    def test_real_end_removes_text_and_mask_and_late_result_stays_hidden(self):
        self.ready();self.texts=[];self.image=picture('')
        self.step(.04);self.step(.07);self.assertEqual(self.step(.1),[])
        self.store.complete_translation(self.jobs[0],'Gecikmiş eski çeviri.',self.now[0])
        self.assertEqual(self.snapshot(),[])

    def test_pixel_support_cannot_refresh_its_own_deadline(self):
        self.ready();self.texts=[]
        for _ in range(4):self.assertTrue(self.step(.1))
        self.step(.1);self.step(.07)
        self.assertEqual(self.step(.07),[])
        self.assertEqual(len(self.jobs),1)

    def test_real_B_wins_while_its_translation_is_pending_then_A_is_new(self):
        first=self.ready()
        self.texts=['Scout: Stop right there.'];self.image=picture(self.texts[0])
        self.assertEqual(self.step(.04),[])
        self.store.complete_translation(self.jobs[0],'Gecikmiş A.',self.now[0]);self.assertEqual(self.snapshot(),[])
        self.store.complete_translation(self.jobs[1],'Orada dur.',self.now[0]);self.assertEqual(self.snapshot()[0]['text'],'Orada dur.')
        self.texts=[LINE];self.image=picture();self.assertEqual(self.step(.04),[])
        self.assertEqual(len(self.jobs),3)
        self.store.complete_translation(self.jobs[2],'Yeni A.',self.now[0])
        self.assertNotEqual(self.snapshot()[0]['id'],first['id'])

    def test_readable_semantic_changes_always_override_same_old_pixels(self):
        for b in ('Scout: I think we should not leave now.',
                  'Scout: I think Peter should leave now.',
                  'Scout: I think we should leave in 2 minutes.',
                  'Pilot: I think we should leave now.'):
            with self.subTest(b=b):
                # Even inconsistent OCR/image inputs must not merge readable B.
                self.texts=[LINE];self.image=picture();self.step(.04)
                self.store.complete_translation(self.jobs[-1],'Güncel A.',self.now[0])
                self.assertTrue(self.snapshot())
                count=len(self.jobs)
                self.texts=[b];self.assertEqual(self.step(.04),[])
                self.assertEqual(len(self.jobs),count+1)
                self.assertEqual(self.store.db.execute('SELECT canonical FROM live_sources WHERE active=1').fetchone()[0],b)

    def test_no_visual_reference_without_boxes(self):
        self.runner.ocr=lambda im:SimpleNamespace(txts=self.texts[:],scores=[.99]*len(self.texts),boxes=None)
        self.ready();self.assertFalse(self.runner.source_evidence.references)
        self.texts=[];self.step(.05);self.step(.07);self.assertEqual(self.step(.07),[])

    def test_frozen_capture_still_expires_at_original_stale_limit(self):
        self.ready();self.now[0]+=.61
        self.assertEqual(self.snapshot(),[])


class EvidenceRulesTests(unittest.TestCase):
    def seed(self):
        tracker=ActiveSubtitles(live=True);evidence=SourceEvidence()
        c=Candidate(LINE,'Scout',LINE.split(': ',1)[1],.99,(20,650,50,88))
        actions=tracker.update([c],100);actions[0].track.row=1
        evidence.observe(actions,picture(),100)
        self.assertTrue(evidence.references)
        return tracker,evidence,c

    def test_narrow_pronoun_only_not_names_negations_numbers_or_short_phrases(self):
        self.assertTrue(narrow_glyph_variant('I think we should leave now.','Il think we should leave now.'))
        for a,b in [('Il think we should leave now.','I think we should leave now.'),
                    ('I am here.','l am here.'),('Peter should leave now.','Petcr should leave now.'),
                    ('I think we should leave now.','l think we should not leave now.'),
                    ('I need 2 more minutes now.','l need 3 more minutes now.'),
                    ('I think Peter should leave now.','l think Miles should leave now.')]:
            with self.subTest(a=a,b=b):self.assertFalse(narrow_glyph_variant(a,b))

    def test_no_hold_for_blank_or_changed_glyphs(self):
        tracker,evidence,c=self.seed()
        for image in (picture(''),picture('Scout: Please stay outside the building.')):
            output,_,held=evidence.reconcile([],tracker.tracks,image,100.1)
            self.assertEqual(output,[]);self.assertFalse(held)

    def test_no_hold_without_matching_image_for_typo(self):
        tracker,evidence,c=self.seed()
        bad=Candidate(LINE.replace('I think','Il think'),'Scout',c.body.replace('I think','Il think'),.99,c.box)
        output,originals,held=evidence.reconcile([bad],tracker.tracks,picture(''),100.1)
        self.assertEqual(output,[bad]);self.assertFalse(originals);self.assertFalse(held)

    def test_confirmed_absence_never_resurrects_from_old_reference(self):
        tracker,evidence,c=self.seed();tracker.update([],100.01);tracker.update([],100.08)
        output,_,_=evidence.reconcile([],tracker.tracks,picture(),100.2)
        self.assertEqual(output,[])

    def test_changed_speaker_does_not_use_glyph_repair(self):
        tracker,evidence,c=self.seed()
        b=Candidate('Pilot: l think we should leave now.','Pilot','l think we should leave now.',.99,c.box)
        self.assertEqual(evidence.reconcile([b],tracker.tracks,picture(),100.1)[0],[b])

    def test_three_tracks_hold_independently_and_one_real_end_is_not_held(self):
        tracker=ActiveSubtitles(live=True);evidence=SourceEvidence();image=Image.new('RGB',(960,540),(65,70,75))
        candidates=[]
        for i,name in enumerate(('Scout','Pilot','Guard')):
            text=name+': I think we should leave now.';y=50+i*140
            ImageDraw.Draw(image).text((22,y+2),text,font=ImageFont.load_default(size=22),fill='white',stroke_width=2,stroke_fill='black')
            candidates.append(Candidate(text,name,text.split(': ',1)[1],.99,(20,650,y,y+38)))
        actions=tracker.update(candidates,100)
        for i,a in enumerate(actions):a.track.row=i+1
        evidence.observe(actions,image,100)
        ImageDraw.Draw(image).rectangle((0,180,959,240),fill=(65,70,75))
        output,_,held=evidence.reconcile([candidates[0]],tracker.tracks,image,100.1)
        self.assertEqual({c.speaker for c in output},{'Scout','Guard'})
        self.assertEqual(held,{actions[2].track.key})

    def test_flat_image_is_never_evidence(self):
        tracker,evidence,c=self.seed();evidence.references.clear()
        evidence.observe(tracker.update([c],100.1),Image.new('RGB',(960,540),'white'),100.1)
        self.assertFalse(evidence.references)
