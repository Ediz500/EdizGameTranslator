"""Anonymized real-session timing replay. No API; never exports dialogue text."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))


def extract():
    path=Path(os.environ['APPDATA'])/'EdizGameTranslator'/'subtitles.sqlite3'
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        sessions=[r[0] for r in db.execute('''SELECT session FROM subtitles GROUP BY session
            HAVING sum(translated IS NOT NULL)>0 ORDER BY max(observed_utc) DESC LIMIT 2''')][::-1]
        groups=[]
        for session in sessions:
            rows=db.execute('''SELECT accepted_mono,first_seen_mono,end_mono,translated,
                queue_wait_ms,translation_ms,status FROM subtitles WHERE session=? ORDER BY accepted_mono,id''',(session,)).fetchall()
            origin=min(r[0] for r in rows)
            groups.append([dict(accepted=round(a-origin,6),ocr_accept_ms=round((a-first)*1000,3),
                source_end=round(end-origin,6) if end else None,chars=len(tr or ''),words=len((tr or '').split()),
                api_queue_ms=queue or 0,api_ms=latency,old_delivery_marked=status=='translated',
                translated=tr is not None) for a,first,end,tr,queue,latency,status in rows])
        return dict(provenance='Two real local Spider-Man sessions; text/identities removed. Final per-row timing, not a complete HTTP trace.',sessions=groups)
    finally:db.close()


def percentile(values):
    values=sorted(values)
    return dict(p50=statistics.median(values),p95=values[max(0,__import__('math').ceil(.95*len(values))-1)]) if values else {}


def compare(data):
    from ediz_game_translator.storage.subtitle_store import SubtitleStore
    from ediz_game_translator.subtitles.subtitle_display import DisplayManager,reading_seconds
    old=sum(r['old_delivery_marked'] for g in data['sessions'] for r in g)
    total=ready=shown=0;delays=[];waits=[];api=[];max_wait=0
    for group in data['sessions']:
        clock=[0.0];store=SubtitleStore(':memory:');session='offline'
        manager=DisplayManager(store,session,clock=lambda:clock[0]);ids=[];events=[]
        for r in group:
            total+=1
            row=store.accept(session,'Anonymous source',r['accepted'],r['accepted'],0,r['accepted'],.99,'replay')
            if not r['translated']:continue  # No response text/timing: do not invent a translation or a timeout.
            job=store.enqueue_translation(session,row,'Anonymous source','gpt-6.1-sol',r['accepted'])
            ids.append(job)
            ready+=1;api.append(r['api_ms'] or 0)
            at=r['accepted']+(r['api_queue_ms']+(r['api_ms'] or 0))/1000
            events.append((at,job,r))
        events.sort(key=lambda e:e[0]);index=0
        for step in range(120000):
            clock[0]=step*.02
            while index<len(events) and events[index][0]<=clock[0]:
                at,job,r=events[index];index+=1
                if r is None:store.fail_translation(job,at)
                else:store.complete_translation(job,'Örnek çeviri',at,duration=reading_seconds(chars=r['chars'],words=r['words']))
            snapshot=manager.snapshot()
            for b in snapshot['blocks']:manager.ack(b['id'],'offline_simulated_renderer')
            max_wait=max(max_wait,snapshot['waiting'])
            if index==len(events) and not manager.snapshot()['blocks'] and not snapshot['waiting']:break
        records=store.db.execute('SELECT accepted_mono,ready_mono,visible_mono,ended_mono FROM translation_jobs WHERE visible_mono IS NOT NULL').fetchall()
        shown+=len(records)
        delays.extend((v-a)*1000 for a,r,v,e in records);waits.extend((v-r)*1000 for a,r,v,e in records)
        store.close()
    return dict(provenance=data['provenance'],accepted=total,existing_translations=ready,
        old_delivery_marked=old,new_simulated_visible=shown,not_translated=total-ready,
        new_max_waiting=max_wait,recorded_api_ms=percentile(api),new_accept_to_simulated_visible_ms=percentile(delays),
        new_display_wait_ms=percentile(waits),physical_tv_verified=False,paid_requests=0,
        note='Original model timings retained; only 49 existing translations replayed, 8 unproduced responses not modelled. Ideal always-visible simulated renderer. Not a Luna benchmark.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--extract-private',action='store_true');args=p.parse_args()
    path=Path(__file__).resolve().parents[2]/'tests'/'spiderman_display_timing.json'
    if args.extract_private:
        data=extract();path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        print(json.dumps(dict(accepted=sum(map(len,data['sessions'])),translations=sum(r['translated'] for g in data['sessions'] for r in g),old_delivery_marked=sum(r['old_delivery_marked'] for g in data['sessions'] for r in g))))
    else:
        result=compare(json.loads(path.read_text(encoding='utf-8')))
        Path('DISPLAY_REPLAY_RESULT.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
