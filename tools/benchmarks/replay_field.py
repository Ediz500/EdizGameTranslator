"""Time-faithful replay of a private live session's stored OCR frames.

Reads ``ocr_frames`` (raw OCR texts/scores/boxes + original ``captured_mono``)
from a COPY of a profile's ``subtitles.sqlite3`` and drives the real
``CaptureRunner(live=True)`` + ``LiveDisplayManager`` on a single logical clock.
Translation is a deterministic fake whose output is a function of the exact
English source, so "distinct Turkish per utterance" == "distinct model inputs".

Privacy: the database is opened read-only, nothing is written next to it, and
dialogue text is printed only with --show-text (local console). Never commit
results produced from real sessions.

Usage (local, private):
  python tools/benchmarks/replay_field.py --db <copy.sqlite3> --session <prefix> [--json out.json] [--show-text]
"""
import argparse
import difflib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from PIL import Image  # noqa: E402

from ediz_game_translator.capture.capture_pipeline import CaptureRunner, DiagnosticLog  # noqa: E402
from ediz_game_translator.capture.dialogue_filter import dialogue_candidates  # noqa: E402
from ediz_game_translator.capture.frame_sources import FramePacket  # noqa: E402
from ediz_game_translator.storage.subtitle_store import SubtitleStore  # noqa: E402
from ediz_game_translator.subtitles.live_display import LiveDisplayManager  # noqa: E402

FRAME = (960, 540)
CROP = (18.850114416475975, 75.06864988558354, 91.96224256292906, 95.1441647597254)


def region_size(crop=CROP, frame=FRAME):
    w, h = frame
    return (int(w * crop[2] / 100) - int(w * crop[0] / 100), int(h * crop[3] / 100) - int(h * crop[1] / 100))


def oracle_key(text):
    """Evaluation-only key (never used by the product): fuzzy grouping of OCR readings."""
    text = text.casefold().replace('’', "'")
    text = re.sub(r'^[^:]{1,32}:\s*', '', text)
    text = text.translate(str.maketrans({'l': 'i', '1': 'i', '|': 'i', '0': 'o'}))
    return re.sub(r'[^a-z0-9]', '', text)


def load_frames(path, session_prefix):
    db = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True)
    session = db.execute('SELECT session FROM ocr_frames WHERE session LIKE ? LIMIT 1',
                         (session_prefix + '%',)).fetchone()
    if session is None:
        raise SystemExit('Session not found')
    rows = db.execute('SELECT captured_mono,captured_utc,raw_texts,raw_scores,raw_boxes FROM ocr_frames '
                      'WHERE session=? ORDER BY id', (session[0],)).fetchall()
    db.close()
    return session[0], [dict(mono=m, utc=u, texts=json.loads(t), scores=json.loads(s),
                             boxes=json.loads(b) if b else None) for m, u, t, s, b in rows]


def reference_utterances(frames, size):
    """Oracle: consecutive similar readings (ratio>=.8) form one utterance; >0.6 s silence ends it."""
    groups = []
    open_groups = []
    for f in frames:
        result = SimpleNamespace(txts=f['texts'], scores=f['scores'], boxes=f['boxes'])
        candidates, _ = dialogue_candidates(result, size[0], size[1])
        for c in candidates:
            if not (c.confidence >= .65):
                continue
            key = oracle_key(c.text)
            if len(key) < 2:
                continue
            best = None
            for g in open_groups:
                if f['mono'] - g['last'] > .6:
                    continue
                ratio = difflib.SequenceMatcher(None, key, g['key']).ratio()
                if ratio >= .8 and (best is None or ratio > best[0]):
                    best = (ratio, g)
            if best:
                g = best[1]
                g['last'] = f['mono']; g['frames'] += 1; g['readings'][c.text] += 1
                if len(key) > len(g['key']):
                    g['key'] = key
            else:
                g = dict(first=f['mono'], last=f['mono'], key=key, frames=1, readings=Counter({c.text: 1}))
                groups.append(g); open_groups.append(g)
        open_groups = [g for g in open_groups if f['mono'] - g['last'] <= .6]
    return [g for g in groups if g['frames'] >= 2]


def replay(path, session_prefix, translation_ms=93.0, decision_ms=45.0):
    session_id, frames = load_frames(path, session_prefix)
    size = region_size()
    store = SubtitleStore(':memory:')
    clock = [frames[0]['mono']]
    jobs = {}
    queue = []
    current = [None]
    region = Image.new('RGB', size, (60, 60, 60))
    full = Image.new('RGB', FRAME, (60, 60, 60))

    def frame():
        f = current[0]
        return FramePacket(full, 0, f['mono'], f['utc'], 0)

    def ocr(_):
        f = current[0]
        return SimpleNamespace(txts=f['texts'], scores=f['scores'], boxes=f['boxes'])

    def accept(row, text, decided):
        job = store.enqueue_translation('replay', row, text, 'local:replay', decided)
        jobs[job] = dict(row=row, source=text, accepted=decided)
        queue.append(job)

    perf = patch('ediz_game_translator.capture.capture_pipeline.time.perf_counter',
                 side_effect=lambda: clock[0])
    perf.start()
    try:
        runner = CaptureRunner(frame, lambda _: region, ocr, store, 'replay', DiagnosticLog(), lambda: None,
                               accept, live=True, crop_rect=tuple(v / 100 for v in CROP))
        manager = LiveDisplayManager(store, 'replay', clock=lambda: clock[0])
        timeline = []  # (time, tuple(job ids visible))
        worker_free = [frames[0]['mono']]
        pending = []  # (ready_time, job)

        def sample(t):
            clock[0] = t
            blocks = manager.snapshot()['blocks']
            ids = tuple(sorted(b['id'] for b in blocks))
            if not timeline or timeline[-1][1] != ids:
                timeline.append((t, ids))

        def drain_until(t):
            while queue:
                job = queue.pop(0)
                start = max(worker_free[0], jobs[job]['accepted'])
                ready = start + translation_ms / 1000
                worker_free[0] = ready
                pending.append((ready, job, start))
            pending.sort()
            while pending and pending[0][0] <= t:
                ready, job, start = pending.pop(0)
                clock[0] = start
                claimed = store.claim_translation('replay', start)
                if claimed is None or claimed['id'] != job:
                    # Cancelled before start: the real coordinator never claims it.
                    jobs[job]['translated'] = None
                    continue
                text = 'TR<' + jobs[job]['source'] + '>'
                store.complete_translation(job, text, ready)
                jobs[job]['translated'] = text; jobs[job]['ready'] = ready
                sample(ready)

        for f in frames:
            drain_until(f['mono'])
            current[0] = f
            clock[0] = f['mono'] + decision_ms / 1000
            runner.step()
            sample(clock[0])
        drain_until(frames[-1]['mono'] + 5)
        sample(frames[-1]['mono'] + 5)
        cancel = Counter(r for (r,) in store.db.execute(
            "SELECT COALESCE(cancel_reason,display_state) FROM translation_jobs"))
        rows = {r: t for r, t in store.db.execute('SELECT id,track_key FROM subtitles')}
    finally:
        perf.stop()
    for job, info in jobs.items():
        info['track'] = rows.get(info['row'])
    return session_id, frames, jobs, timeline, cancel, store


def evaluate(frames, jobs, timeline):
    size = region_size()
    truth = reference_utterances(frames, size)
    # Assign each job to the oracle utterance active at acceptance with the most similar text.
    for job, info in jobs.items():
        key = oracle_key(info['source']); best = None
        for i, g in enumerate(truth):
            if g['first'] - .2 <= info['accepted'] <= g['last'] + .7:
                ratio = difflib.SequenceMatcher(None, key, g['key']).ratio()
                if ratio >= .6 and (best is None or ratio > best[0]):
                    best = (ratio, i)
        info['utterance'] = best[1] if best else None
    per = defaultdict(list)
    for job, info in sorted(jobs.items()):
        if info['utterance'] is not None:
            per[info['utterance']].append(job)
    # Visibility of each utterance from its first visible moment to its last OCR sighting.
    def visible_at(t):
        ids = ()
        for when, current in timeline:
            if when > t:
                break
            ids = current
        return ids
    gaps = []; changes = []; missed = []
    events = timeline
    for i, g in enumerate(truth):
        own = set(per.get(i, []))
        if not own:
            missed.append(i); continue
        first_visible = next((t for t, ids in events if own & set(ids)), None)
        if first_visible is None or first_visible > g['last']:
            gaps.append(dict(utterance=i, blank_ms=0, gaps=0, never_visible=True)); continue
        blank = 0.; count = 0; last_texts = []
        span = [(t, ids) for t, ids in events if first_visible <= t <= g['last']]
        span.append((g['last'], visible_at(g['last'])))
        for (t0, ids0), (t1, _) in zip(span, span[1:]):
            mine = own & set(ids0)
            if not mine:
                blank += t1 - t0
                if t1 > t0:
                    count += 1
            else:
                text = jobs[max(mine)].get('translated')
                if not last_texts or last_texts[-1] != text:
                    last_texts.append(text)
        gaps.append(dict(utterance=i, blank_ms=round(blank * 1000), gaps=count, never_visible=False))
        changes.append(max(0, len(last_texts) - 1))
    jobs_per = [len(per.get(i, [])) for i in range(len(truth))]
    distinct = [len({jobs[j].get('translated') for j in per.get(i, []) if jobs[j].get('translated')}) for i in range(len(truth))]
    sources = [len({jobs[j]['source'] for j in per.get(i, [])}) for i in range(len(truth))]
    return dict(utterances=len(truth), jobs=len(jobs),
                distinct_source_extra=sum(max(0, n - 1) for n in sources),
                tracks=len({i['track'] for i in jobs.values()}),
                extra_jobs=sum(max(0, n - 1) for n in jobs_per),
                utterances_with_extra_jobs=sum(n > 1 for n in jobs_per),
                distinct_translation_extra=sum(max(0, n - 1) for n in distinct),
                visible_text_changes=sum(changes),
                intra_utterance_blank_ms=sum(g['blank_ms'] for g in gaps),
                intra_utterance_gaps=sum(g['gaps'] for g in gaps),
                never_visible=sum(g['never_visible'] for g in gaps),
                missed_utterances=len(missed)), truth, per, gaps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--json')
    parser.add_argument('--show-text', action='store_true')
    args = parser.parse_args()
    session, frames, jobs, timeline, cancel, _ = replay(args.db, args.session)
    summary, truth, per, gaps = evaluate(frames, jobs, timeline)
    summary.update(session=session[:8], frames=len(frames), cancel_reasons=dict(cancel))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.show_text:
        for i, g in enumerate(truth):
            own = per.get(i, [])
            print(f"U{i} {g['frames']}f jobs={len(own)} gap={gaps[[x['utterance'] for x in gaps].index(i)] if i in [x['utterance'] for x in gaps] else 'MISSED'}")
            for j in own:
                print('    ', repr(jobs[j]['source'][-60:]), '->', jobs[j].get('translated') is not None)
    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
