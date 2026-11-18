"""Stage 1: one verified utterance -> one translation job -> one stable Turkish text.

Variants are the ones observed in private PS5 sessions (anonymised to their
structure). Timing uses the measured live OCR cadence (36-216 ms, jittered),
not a fixed 20 fps clock.
"""
from bootstrap import configure_paths
configure_paths()
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from ediz_game_translator.capture.capture_pipeline import CaptureRunner, DiagnosticLog
from ediz_game_translator.capture.subtitle_tracking import ActiveSubtitles, Candidate, noise_variant
from ediz_game_translator.storage.subtitle_store import SubtitleStore
from ediz_game_translator.subtitles.overlay_server import SharedOverlayState

# Measured live OCR intervals (seconds): p50 ~0.05, occasional 0.14-0.22 stalls.
FIELD_INTERVALS = [.036, .05, .047, .05, .14, .05, .036, .069, .05, .216, .047, .05]
BOX = (100, 600, 40, 70)


def cand(text, score=.97, box=BOX):
    speaker, body = (text.split(': ', 1) if ': ' in text else ('', text))
    return Candidate(text, speaker, body, score, box)


def run_tracker(texts, box=BOX):
    tracker = ActiveSubtitles(live=True)
    now = 0.; actions = []
    for i, text in enumerate(texts):
        actions.append(tracker.update([cand(text, box=box)] if text else [], now))
        now += FIELD_INTERVALS[i % len(FIELD_INTERVALS)]
    return tracker, [a for frame in actions for a in frame]


class NoiseVariantTests(unittest.TestCase):
    def test_format_spacing_and_glyph_variants_of_field_lines(self):
        pairs = [('Not bad,', 'Notbad,'), ('Not bad,', 'not bad.'),
                 ("I dunno... not sure", 'I dunno.. notsure'),
                 ("I'm cut out for the nine to five.", "l'm cut out for the nine to five."),
                 ("I'm cut out for the nine to five.", "Il'm cut out for the nine to five."),
                 ("I'll be fine. I suspect she'll be relieved to talk to someone.",
                  "Il be fine. I suspect she'll be relieved to talk to someone."),
                 ("I'll be fine. I suspect she'll be relieved to talk to someone.",
                  "Ill be fine. I suspect shell be relieved to talk to someone."),
                 ('We should go to the docks now.', 'We shouId go to the docks n0w.')]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertTrue(noise_variant(a, b))
                self.assertTrue(noise_variant(b, a))

    def test_meaning_changing_minimal_pairs_are_never_noise(self):
        pairs = [('I can go', "I can't go"), ('I can go now.', 'I cant go now.'),
                 ('Turn left here.', 'Turn lift here.'), ("We'll see.", 'Well see.'),
                 ("She'll go.", 'Shell go.'), ('They are now here.', 'They are nowhere.'),
                 ('Take 10 crates.', 'Take 11 crates.'), ('Meet Alex now.', 'Meet Alexa now.'),
                 ('Wait for Peter here.', 'Wait for Miles here.'), ('You okay?', 'You okay.'),
                 ('We have met.', 'We have never met.'), ('No.', 'Go.')]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertFalse(noise_variant(a, b))
                self.assertFalse(noise_variant(b, a))


class TrackerTests(unittest.TestCase):
    def test_field_alternation_is_one_track_and_one_dispatch(self):
        for texts in (['Gloria: Not bad,', 'Gloria: Notbad,'] * 4,
                      ["Gloria: I'm cut out for the nine to five.", "Gloria: l'm cut out for the nine to five."] * 6,
                      ['Gloria: your Aunt has been helping me. I dunno... not sure',
                       'Gloria: your Aunt has been helping me. I dunno.. notsure'] * 4):
            with self.subTest(first=texts[0]):
                _, actions = run_tracker(texts)
                self.assertEqual(len({a.track.key for a in actions}), 1)
                self.assertEqual(sum(a.dispatch for a in actions), 1)
                self.assertTrue(all(not a.track.retired for a in actions))

    def test_canonical_is_locked_after_dispatch(self):
        good = "Aunt May: I'll be fine. I suspect she'll be relieved to talk to someone who's been there."
        texts = [good, good.replace("I'll", 'Il'), good.replace("I'll", 'Ill').replace("she'll", 'shell'), good] * 3
        _, actions = run_tracker(texts)
        self.assertEqual(sum(a.dispatch for a in actions), 1)
        self.assertEqual({a.track.canonical for a in actions}, {good})

    def test_dropped_letter_in_long_verified_line_is_not_a_new_utterance(self):
        good = "Aunt May: I'll be fine. I suspect she'll be relieved to talk to someone who's been there."
        texts = [good, good, good.replace('be fine', 'e fine'), good.replace('be fine', 'e fine'), good, good]
        _, actions = run_tracker(texts)
        self.assertEqual(sum(a.dispatch for a in actions), 1)
        for a, b in (("Peter: I can't go there with you tonight.", 'Peter: I can go there with you tonight.'),
                     ('Peter: Meet Alexa near the old station.', 'Peter: Meet Alex near the old station.'),
                     ('Peter: Take 15 crates to the old station.', 'Peter: Take 1 crates to the old station.'),
                     ('Peter: Is she coming to the station tonight?', 'Peter: Is she coming to the station tonight')):
            with self.subTest(b=b):
                _, actions = run_tracker([a, a, b, b, b])
                self.assertEqual(sum(x.dispatch for x in actions), 2)

    def test_damaged_first_reading_waits_for_a_better_one(self):
        bad = "Gloria: l'm cut out for the nine to five."
        good = "Gloria: I'm cut out for the nine to five."
        _, actions = run_tracker([bad, good, bad, good])
        dispatched = [a for a in actions if a.dispatch]
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0].track.canonical, good)

    def test_temporarily_lost_speaker_label_is_same_utterance(self):
        texts = ['Gloria: I heard you were at City Hall.', 'I heard you were at City Hall.',
                 'Gloria I heard you were at City Hall.', 'Gloria: I heard you were at City Hall.']
        _, actions = run_tracker(texts)
        self.assertEqual(sum(a.dispatch for a in actions), 1)
        self.assertEqual(len({a.track.key for a in actions}), 1)

    def test_single_conflicting_reading_does_not_end_verified_utterance(self):
        a = 'Peter: I can go with you now.'; b = "Peter: I can't go with you now."
        tracker, actions = run_tracker([a, a, b, a, a])
        self.assertEqual(sum(x.dispatch for x in actions), 1)
        self.assertFalse(any(t.retired for t in tracker.tracks if t.accepted))

    def test_persistent_meaning_change_becomes_new_utterance(self):
        a = 'Peter: I can go with you now.'; b = "Peter: I can't go with you now."
        tracker, actions = run_tracker([a, a, b, b, b])
        dispatched = [x for x in actions if x.dispatch]
        self.assertEqual([x.track.canonical for x in dispatched], [a, b])

    def test_completely_different_line_and_A_B_A_are_immediate(self):
        a = 'Scout: We should leave now.'; b = 'Scout: Stop right there.'
        _, actions = run_tracker([a, b, a])
        self.assertEqual(sum(x.dispatch for x in actions), 3)

    def test_two_speakers_on_two_rows_stay_independent(self):
        tracker = ActiveSubtitles(live=True); now = 0.; keys = set(); dispatch = 0
        for i in range(6):
            frame = [cand('Peter: I need to go now.', box=(100, 600, 10, 40)),
                     cand('Miles: Wait for me here.' if i % 2 else 'Miles: Wait for me hore.', box=(100, 600, 60, 90))]
            for a in tracker.update(frame, now):
                if a.track.accepted:keys.add(a.track.key)
                dispatch += a.dispatch
            now += .05
        # 'here'/'hore' is a real one-letter difference (not noise): the single
        # alternating reading never confirms, so it neither dispatches nor ends Miles' line.
        self.assertEqual(dispatch, 2)
        self.assertEqual(len(keys), 2)
        self.assertFalse(any(t.retired for t in tracker.tracks if t.accepted))

    def test_short_and_long_lines(self):
        _, short = run_tracker(['Aunt May: I will.', 'Aunt May: I will', 'Aunt May: i will.'])
        self.assertEqual(sum(a.dispatch for a in short), 1)
        _, changed = run_tracker(['Aunt May: I will.', 'Aunt May: I won\'t.', 'Aunt May: I won\'t.'])
        self.assertEqual(sum(a.dispatch for a in changed), 2)


class PipelineTests(unittest.TestCase):
    """CaptureRunner + SQLite + live display: what OBS would be sent."""
    def setUp(self):
        self.now = [100.]; self.texts = []; self.jobs = []
        self.store = SubtitleStore(':memory:')
        self.clock = patch('ediz_game_translator.capture.capture_pipeline.time.perf_counter',
                           side_effect=lambda: self.now[0])
        self.clock.start()
        image = Image.new('RGB', (960, 540), (60, 60, 60))

        def accepted(row, text, now):
            self.jobs.append((self.store.enqueue_translation('s', row, text, 'local:ct2-marian', now), text))
        box = [[100, 40], [600, 40], [600, 70], [100, 70]]
        self.runner = CaptureRunner(lambda: image, lambda im: im,
            lambda im: SimpleNamespace(txts=self.texts[:], scores=[.97] * len(self.texts), boxes=[box] * len(self.texts)),
            self.store, 's', DiagnosticLog(), lambda: None, accepted, live=True)
        self.state = SharedOverlayState(); self.state.bind(self.store, 's', live=True)
        self.state.manager.clock = lambda: self.now[0]

    def tearDown(self):
        self.state.close(); self.store.close(); self.clock.stop()

    def blocks(self):
        return json.loads(self.state.json())['blocks']

    def finish_jobs(self):
        for job, text in self.jobs:
            row = self.store.db.execute('SELECT translation_state,display_state FROM translation_jobs WHERE id=?', (job,)).fetchone()
            if row[0] == 'queued' and row[1] not in ('cancelled', 'skipped'):
                self.store.claim_translation('s', self.now[0])
                self.store.complete_translation(job, 'TR<' + text + '>', self.now[0])

    def test_alternating_variants_keep_one_job_and_one_visible_text(self):
        seen = []
        for i in range(16):
            self.texts = ['Gloria: Not bad,'] if i % 2 == 0 else ['Gloria: Notbad,']
            self.runner.step(); self.finish_jobs()
            blocks = self.blocks()
            if i > 0:
                self.assertEqual(len(blocks), 1, i)
                seen.append((blocks[0]['id'], blocks[0]['text']))
            self.now[0] += FIELD_INTERVALS[i % len(FIELD_INTERVALS)]
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(len(set(seen)), 1)

    def test_pending_near_B_keeps_A_then_confirmed_B_replaces_without_A_returning(self):
        a = 'Peter: I can go with you now.'; b = "Peter: I can't go with you now."
        self.texts = [a]; self.runner.step(); self.finish_jobs(); self.now[0] += .05
        first = self.blocks(); self.assertEqual(len(first), 1)
        self.texts = [b]; self.runner.step(); self.now[0] += .05
        held = self.blocks()
        self.assertEqual([x['id'] for x in held], [first[0]['id']])  # one contested reading: A stays
        self.runner.step(); self.now[0] += .05                      # second consecutive B: new utterance
        self.assertEqual(self.blocks(), [])                           # A removed at once, B pending
        self.assertEqual(len(self.jobs), 2)
        self.finish_jobs()
        self.assertEqual([x['text'] for x in self.blocks()], ['TR<' + b + '>'])
        cancelled = self.store.db.execute("SELECT cancel_reason FROM translation_jobs WHERE id=?", (self.jobs[0][0],)).fetchone()[0]
        self.assertEqual(cancelled, 'source_replaced')

    def test_late_old_result_cannot_return(self):
        a = 'Scout: We should leave now.'; b = 'Scout: Stop right there.'
        self.texts = [a]; self.runner.step(); self.now[0] += .05
        self.texts = [b]; self.runner.step(); self.now[0] += .05
        self.store.claim_translation('s', self.now[0])
        self.store.complete_translation(self.jobs[0][0], 'Eski A.', self.now[0])
        self.assertNotIn('Eski A.', [x['text'] for x in self.blocks()])


if __name__ == '__main__':
    unittest.main()
