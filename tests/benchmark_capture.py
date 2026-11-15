"""Deterministic OCR-output replay, NOT image OCR or a game benchmark."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import clean_ocr, key_for


class LegacyGate:
    """P1 capture_worker acceptance rule copied before replacing it."""
    def __init__(self):
        self.seen = self.submitted = ''
        self.streak = 0
        self.blank = None

    def observe(self, text, confidence, now):
        key = key_for(text)
        if key:
            self.blank = None
            self.streak = self.streak + 1 if key == self.seen else 1
            self.seen = key
            if self.streak >= 2 and key != self.submitted:
                self.submitted = key
                return text
        else:
            if self.blank is None:
                self.blank = now
            if now - self.blank > 1.8:
                self.seen = self.submitted = ''
                self.streak = 0


def replay(factory, interval, phase=0):
    results = []
    for case in json.loads(Path(__file__).with_name('subtitle_sequences.json').read_text()):
        gate = factory()
        accepted = []
        for i in range(int(case['segments'][-1][1] / interval) + 1):
            now = round(phase + i * interval, 6)
            segment = next((s for s in case['segments'] if s[0] <= now < s[1]), None)
            if segment:
                text = gate.observe(clean_ocr(segment[2]), segment[3], now)
                if text:
                    accepted.append(text)
        # Known OCR glyph confusion allowed for matching ground truth, not arbitrary fuzzy matching.
        normalize = lambda t: clean_ocr(t).casefold().replace('0', 'o')
        expected = [normalize(t) for t in case['expected']]
        actual = [normalize(t) for t in accepted]
        hits = sum(t in actual for t in expected)
        false = sum(t not in expected for t in actual)
        duplicates = len(actual) - len(set(actual))
        results.append(dict(name=case['name'], expected=len(expected), captured=hits,
                            false_accepts=false, duplicates=duplicates, accepted=accepted))
    expected = sum(r['expected'] for r in results)
    hits = sum(r['captured'] for r in results)
    return dict(interval=interval, phase=phase, expected=expected, captured=hits, missed=expected-hits,
                recall=hits/expected, false_accepts=sum(r['false_accepts'] for r in results),
                cases=results)


class NewGateAdapter:
    def __init__(self):
        from capture_pipeline import SubtitleGate
        self.gate = SubtitleGate()

    def observe(self, text, confidence, now):
        d = self.gate.observe(text, confidence, now)
        return d.text if d.accepted else None


if __name__ == '__main__':
    report = dict(kind='synthetic_ocr_output_replay_not_real_game',
        old=replay(LegacyGate,.8), old_faster=replay(LegacyGate,.28),
        new_same_cadence=replay(NewGateAdapter,.8), new=replay(NewGateAdapter,.28),
        new_phases=[replay(NewGateAdapter,.28,p*.28)['recall'] for p in (0,.25,.5,.75)])
    Path('OCR_REPLAY_BENCHMARK.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
