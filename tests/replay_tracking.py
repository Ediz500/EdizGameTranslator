"""Private local JSONL replay; emits hashes/times/metrics, never dialogue text."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from subtitle_tracking import ActiveSubtitles
from dialogue_filter import dialogue_candidates
from capture_pipeline import CaptureRunner,DiagnosticLog
from frame_sources import FramePacket
from subtitle_store import SubtitleStore
from collections import Counter


def replay(path,database=None):
    data=Path(path).read_bytes()
    frames=[r for r in (json.loads(l) for l in data.decode('utf-8').splitlines()) if r.get('kind')=='frame']
    tracker=ActiveSubtitles(); times=[]; events=[]; counts={}
    first=frames[0]['received_mono']
    tracks={}
    for i,f in enumerate(frames):
        start=time.perf_counter()
        candidates,_=dialogue_candidates(SimpleNamespace(txts=f.get('raw_texts'),scores=f.get('raw_scores'),
                                         boxes=f.get('raw_boxes')),f.get('image_width') or 960,160)
        actions=tracker.update(candidates,f['received_mono'])
        times.append((time.perf_counter()-start)*1000)
        for a in actions:
            counts[a.reason]=counts.get(a.reason,0)+1
            if a.new:events.append(dict(frame=i,seconds=round(f['received_mono']-first,3),
                                speaker_id=hashlib.sha256(a.track.speaker.encode()).hexdigest()[:12]))
            tracks[a.track.key]=a.track
    report=dict(sha256=hashlib.sha256(data).hexdigest(),frames=len(frames),
        old_accepts=sum(bool(f.get('accepted')) for f in frames),new_canonicals=len(events),
        old_mixed_speaker_accepts=sum(bool(f.get('accepted')) and len(__import__('subtitle_tracking').SPEAKER.findall(f.get('text','')))>1 for f in frames),
        reason_counts=counts,tracking_ms=dict(p50=statistics.median(times),p95=sorted(times)[int(.95*len(times))]),events=events)
    if database:
        if Path(database).exists():raise ValueError('Choose a new private replay database; existing files are never overwritten')
        store=SubtitleStore(database); current=[None]; dispatches=[]
        def frame():
            r=current[0]
            return FramePacket(SimpleNamespace(width=r.get('image_width') or 960),r.get('frame_sequence',0),r['received_mono'],r['received_utc'],0)
        def ocr(_):
            r=current[0]
            return SimpleNamespace(txts=r['raw_texts'],scores=r['raw_scores'],boxes=r.get('raw_boxes'))
        runner=CaptureRunner(frame,lambda _:SimpleNamespace(width=current[0].get('image_width') or 960,height=160),ocr,
            store,'private-offline-replay',DiagnosticLog(),lambda:None,lambda row,text,at:dispatches.append((row,text)))
        try:
            for r in frames:
                current[0]=r; runner.step()
            from subtitle_tracking import SPEAKER
            db=store.db
            grouped=[]
            for row_id, in db.execute('SELECT id FROM subtitles ORDER BY id'):
                stamps=[r[0] for r in db.execute('''SELECT f.captured_mono FROM subtitle_observations o
                    JOIN ocr_frames f ON f.id=o.frame_id WHERE o.subtitle_id=?''',(row_id,))]
                indices=[i for i,f in enumerate(frames) if f['received_mono'] in stamps]
                grouped.append(dict(canonical=row_id,first_frame=min(indices),last_frame=max(indices),
                    old_accepted_frames=[i for i in indices if frames[i].get('accepted')]))
            report['canonical_groups']=grouped
            report['database_verification']=dict(
                canonical_rows=db.execute('SELECT count(*) FROM subtitles').fetchone()[0],
                raw_frame_rows=db.execute('SELECT count(*) FROM ocr_frames').fetchone()[0],
                observation_rows=db.execute('SELECT count(*) FROM subtitle_observations').fetchone()[0],
                revision_rows=db.execute('SELECT count(*) FROM subtitle_revisions').fetchone()[0],
                dispatch_events=len(dispatches),mixed_speaker_dispatches=sum(len(SPEAKER.findall(t))>1 for _,t in dispatches),
                unlinked_pending=db.execute('SELECT count(*) FROM subtitle_observations WHERE subtitle_id IS NULL').fetchone()[0],
                ocr_replayed_not_executed=True,
                tracking_pipeline_ms={k:v for k,v in runner.metrics.summary()['stages'].items()
                                      if k in ('decision_ms','storage_ms','dispatch_ms','cycle_ms')})
        finally:
            store.close()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('input'); parser.add_argument('--output',default='TRACKING_REPLAY.json')
    parser.add_argument('--database',help='New private SQLite file, ignored by Git; contains real dialogue')
    args=parser.parse_args(); report=replay(args.input,args.database)
    Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='events'},indent=2))
