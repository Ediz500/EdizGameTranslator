"""Anonymized reproductions; original private game log is never checked in."""
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from subtitle_tracking import ActiveSubtitles,Candidate,equivalent,continuation
from dialogue_filter import dialogue_candidates
from subtitle_store import SubtitleStore
from capture_pipeline import CaptureRunner,DiagnosticLog
from frame_sources import FramePacket


def candidate(body,speaker='Voice-A',score=.99,box=(300,650,110,150)):
    return Candidate(f'{speaker}: {body}',speaker,body,score,box)


class TrackingTests(unittest.TestCase):
    def test_nine_missing_pronoun_variants_are_one_track(self):
        tracker=ActiveSubtitles(); events=[]; keys=[]
        good="Then it's up to us to locate him. I've been checking some records..."
        bad=good.replace("I've","'ve")
        for i in range(9):
            a=tracker.update([candidate(good if i%2==0 else bad)],i*.28)[0]
            events.append(a.new); keys.append(a.track.key)
        self.assertEqual(sum(events),1)
        self.assertEqual(len(set(keys)),1)
        self.assertEqual(a.track.canonical,candidate(good).text)

    def test_joined_word_and_apostrophe_observations_not_new_replies(self):
        for variants in (["I'll let you know what I discover.",'Ill let you know what I discover.',"I' ll let you know what I discover."],
                         ['The company bought the property last year.','The company bought the property lastyear.']):
            tracker=ActiveSubtitles(); actions=[tracker.update([candidate(text)],i*.28)[0] for i,text in enumerate(variants)]
            self.assertEqual(sum(a.new for a in actions),1)

    def test_real_semantic_changes_are_not_equivalent(self):
        for a,b in [('I can meet you by the old bridge.',"I can't meet you by the old bridge."),
                    ('No guards remain at the gate.','Guards remain at the gate.'),
                    ('We have never met this person.','We have met this person.'),
                    ('Meet Alex near the station.','Meet Alexa near the station.'),
                    ('Take 10 crates to the station.','Take 11 crates to the station.'),
                    ('We should go east this evening.','We should go west this evening.'),
                    ('I will find the missing report.','I will fine the missing report.'),
                    ('They are nowhere near the park.','They are now here near the park.'),
                    ("We're ready to leave the station.",'Were ready to leave the station.')]:
            self.assertFalse(equivalent(a,b),(a,b))
            tracker=ActiveSubtitles()
            first=tracker.update([candidate(a)],0)[0]
            second=tracker.update([candidate(b)],.28)[0]
            self.assertNotEqual(first.track.key,second.track.key,(a,b))

    def test_protected_prefix_change_is_not_an_extension(self):
        for a,b in [('I think we can','I think we cannot leave.'),('Meet agent Alex','Meet agent Alexa tonight.'),
                    ('Please take 1','Please take 10 crates.'),('I like the car','I like the carpet.')]:
            self.assertIsNone(continuation(a,b))

    def test_growth_and_unfinished_sentence_fragments(self):
        tracker=ActiveSubtitles()
        a=tracker.update([candidate('We should check the')],0)[0]
        b=tracker.update([candidate('We should check the station.')],.28)[0]
        self.assertEqual(a.track.key,b.track.key)
        self.assertEqual(b.reason,'extension')
        c=tracker.update([candidate('Look at the office next.')],.56)[0]
        self.assertNotEqual(b.track.key,c.track.key)
        tracker=ActiveSubtitles()
        a=tracker.update([candidate('We know she is not at the office,')],0)[0]
        b=tracker.update([candidate('perhaps you can find a clue there.')],.28)[0]
        self.assertNotEqual(a.track.key,b.track.key)
        # A comma is insufficient evidence for joining disjoint fragments.
        self.assertTrue(b.dispatch)
        self.assertTrue(b.new)

    def test_same_text_different_speaker_or_position_does_not_merge(self):
        tracker=ActiveSubtitles()
        a=tracker.update([candidate('Stay away from the gate.')],0)[0]
        b=tracker.update([candidate('Stay away from the gate.',speaker='Voice-B')],.28)[0]
        c=tracker.update([candidate('Stay away from the gate.',box=(300,650,20,45))],.4)[0]
        self.assertNotEqual(a.track.key,b.track.key)
        self.assertNotEqual(a.track.key,c.track.key)

    def test_short_occlusion_retained_but_later_repeat_is_new(self):
        tracker=ActiveSubtitles(); a=tracker.update([candidate('Wait until the guard leaves.')],0)[0]
        tracker.update([],.28)
        b=tracker.update([candidate('Wait until the guard leaves.')],.56)[0]
        self.assertEqual(a.track.key,b.track.key)
        c=tracker.update([candidate('Wait until the guard leaves.')],2)[0]
        self.assertNotEqual(a.track.key,c.track.key)

    def test_low_confidence_does_not_count_as_confirmation(self):
        tracker=ActiveSubtitles()
        self.assertFalse(tracker.update([candidate('Wait until the guard leaves.',score=.4)],0)[0].new)
        self.assertFalse(tracker.update([candidate('Wait until the guard leaves.',score=.7)],.28)[0].new)
        self.assertTrue(tracker.update([candidate('Wait until the guard leaves.',score=.7)],.56)[0].new)

    def test_glyph_noise_in_common_word_but_not_a_person_name(self):
        tracker=ActiveSubtitles()
        self.assertFalse(tracker.update([candidate('F0llow the guards to the bridge.',score=.8)],0)[0].new)
        self.assertTrue(tracker.update([candidate('Follow the guards to the bridge.',score=.9)],.28)[0].new)
        self.assertEqual(len(tracker.tracks),1)
        self.assertFalse(equivalent('Meet F0rest near the station.','Meet Forest near the station.'))

    def test_multiple_speakers_are_separate_with_wraps(self):
        r=SimpleNamespace(txts=['Voice-A: That was close.','Voice-B: We need to search',
                               'the station before dawn.'],scores=[.99]*3,
            boxes=[[[350,80],[600,80],[600,100],[350,100]],
                   [[300,114],[660,114],[660,134],[300,134]],
                   [[400,136],[560,136],[560,154],[400,154]]])
        candidates,_=dialogue_candidates(r,960,160)
        self.assertEqual([c.speaker for c in candidates],['Voice-A','Voice-B'])
        self.assertEqual(candidates[1].body,'We need to search the station before dawn.')
        self.assertNotIn('Voice-B',candidates[0].text)

    def test_invalid_scores_and_inline_mixed_speakers(self):
        for score in (float('nan'),float('inf'),1.1,.3):
            candidates,_=dialogue_candidates(SimpleNamespace(txts=['Voice-A: Stay here.'],scores=[score],boxes=None),960,160)
            self.assertEqual(candidates,[])
        candidates,_=dialogue_candidates(SimpleNamespace(txts=['Voice-A: Stay here. Voice-B: We need to leave.'],scores=[.99],boxes=None),960,160)
        self.assertEqual([c.speaker for c in candidates],['Voice-A','Voice-B'])


class StorageTests(unittest.TestCase):
    def test_seen_reopens_short_occlusion_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SubtitleStore(Path(folder)/'test.sqlite3')
            row=store.accept('s','Original.',0,0,100,0,.99,'high_confidence')
            store.finish(row,.28,100.28)
            store.seen(row,.56,100.56)
            self.assertEqual(store.db.execute('SELECT text,end_mono,last_seen_mono FROM subtitles').fetchone(),('Original.',None,.56))
            store.close()
    def test_additive_migration_preserves_existing_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.execute('''CREATE TABLE subtitles (id INTEGER PRIMARY KEY,session TEXT,text TEXT,
                    first_seen_mono REAL,last_seen_mono REAL,observed_utc REAL,accepted_mono REAL,
                    end_mono REAL,end_utc REAL,confidence REAL,reason TEXT,status TEXT,translated TEXT,
                    updated_utc REAL,queue_wait_ms REAL,translation_ms REAL)''')
                db.execute("INSERT INTO subtitles (id,text,status) VALUES (1,'Original text.','translated')");db.commit()
            store=SubtitleStore(path); store.close()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT text,canonical_text FROM subtitles').fetchone(),('Original text.','Original text.'))

    def test_raw_observations_and_corrections_are_immutable_and_no_repeat_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.sqlite3'; store=SubtitleStore(path)
            inputs=['Voice-A:Ill let you know what I discover.',"Voice-A: I'll let you know what I discover."]
            counter=[0]
            def frame():
                return FramePacket(SimpleNamespace(width=960),counter[0]+1,counter[0]*.28,100+counter[0]*.28,1)
            def ocr(_):return SimpleNamespace(txts=[inputs[counter[0]]],scores=[.98],boxes=None)
            dispatch=MagicMock()
            runner=CaptureRunner(frame,lambda _:SimpleNamespace(width=960,height=160),ocr,store,'test',DiagnosticLog(),MagicMock(),dispatch)
            runner.step();counter[0]=1;runner.step()
            store.close()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM subtitles').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT text,canonical_text FROM subtitles').fetchone(),tuple(inputs))
                raw=[json.loads(r[0])[0] for r in db.execute('SELECT raw_texts FROM ocr_frames ORDER BY id')]
                self.assertEqual(raw,inputs)
                self.assertEqual(db.execute('SELECT observed_text FROM subtitle_observations ORDER BY id').fetchall(),[(x,) for x in inputs])
                self.assertEqual(db.execute('SELECT count(*) FROM subtitle_revisions').fetchone()[0],2)
            dispatch.assert_called_once()

    def test_overlapping_speaker_leaving_invalidates_old_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SubtitleStore(Path(folder)/'test.sqlite3');count=[0]
            results=[['Voice-B: We need to leave.'],['Voice-A: That was close.','Voice-B: We need to leave.'],['Voice-B: We need to leave.']]
            def ocr(_):
                texts=results[count[0]]
                return SimpleNamespace(txts=texts,scores=[.99]*len(texts),boxes=None)
            change=MagicMock();dispatch=MagicMock()
            runner=CaptureRunner(lambda:FramePacket(None,count[0],count[0]*.28,100,1),lambda _:SimpleNamespace(width=960,height=160),
                ocr,store,'test',DiagnosticLog(),change,dispatch)
            for i in range(3):count[0]=i;runner.step()
            self.assertEqual(change.call_count,3)
            self.assertEqual(dispatch.call_count,2)
            self.assertTrue(all(len(__import__('subtitle_tracking').SPEAKER.findall(c.args[1]))==1 for c in dispatch.call_args_list))
            store.close()
