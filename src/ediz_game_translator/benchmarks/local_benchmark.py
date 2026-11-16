"""Read-only real-corpus export, latency audit and isolated offline benchmark.

No paid API calls. Export and run results contain private dialogue; ignored by Git.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from types import SimpleNamespace,ModuleType

from ediz_game_translator.translation.local_translation import LOCAL_MODELS,LocalWorkerClient
from ediz_game_translator.capture.subtitle_tracking import equivalent,split_speaker,normalized


def percentiles(values):
    v=sorted(values)
    return dict(n=len(v),p50=statistics.median(v),p95=v[math.ceil(.95*len(v))-1],min=v[0],max=v[-1]) if v else dict(n=0,p50=None,p95=None)


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)


def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def export_corpus(database,limit=75):
    if not 50<=limit<=100:raise ValueError('Choose 50–100 lines')
    db=readonly(database)
    try:
        db.row_factory=sqlite3.Row
        columns={r[1] for r in db.execute('PRAGMA table_info(translation_jobs)')}
        # Read-only historical references; the local runtime has no SDK or
        # billing columns. Never create them merely to export a benchmark.
        refs=([dict(r) for r in db.execute("SELECT id,source,translated,session,api_called FROM translation_jobs WHERE model='gpt-6-luna' AND translation_state='completed'")]
              if 'api_called' in columns else [])
        rows=[dict(r) for r in db.execute('SELECT id,session,COALESCE(canonical_text,text) AS text,confidence,first_seen_mono FROM subtitles ORDER BY session,first_seen_mono,id')]
    finally:db.close()
    from ediz_game_translator.capture.dialogue_filter import dialogue_candidates
    entries=[];previous={}
    for row in rows:
        candidates,_=dialogue_candidates(SimpleNamespace(txts=[row['text']],scores=[row['confidence']],boxes=None),960,160)
        for candidate in candidates:
            speaker,body=candidate.speaker,candidate.body
            # Speaker-labelled game dialogue only: excludes HUD and blank noise.
            if not speaker or len(body)<3 or '\ufffd' in body:continue
            history=previous.setdefault(row['session'],[])
            context='\n'.join(history[-2:])
            if not history or not equivalent(history[-1],candidate.text):history.append(candidate.text)
            if any(equivalent(e['source'],body) or normalized(e['source'])==normalized(body) for e in entries):continue
            reference=[]
            for r in refs:
                rs,rb=split_speaker(r['source'])
                if rs.casefold()==speaker.casefold() and equivalent(rb,body):
                    reference.append(dict(job_id=r['id'],text=r['translated'],api_called=bool(r['api_called'])))
            entries.append(dict(id=f"sqlite-{row['id']}-{len(entries)}",subtitle_id=row['id'],session=row['session'],
                speaker=speaker,source=body,context=context,
                length_group='short' if len(body)<=60 else 'long',confidence=row['confidence'],
                luna_references=reference,ocr_review_required=True))
    # Balance length groups; shuffle deterministically to avoid warm-up bias.
    short=[e for e in entries if e['length_group']=='short'];long=[e for e in entries if e['length_group']=='long']
    chosen=short[:limit//2]+long[:limit//2]
    chosen_ids={e['id'] for e in chosen}
    chosen += [e for e in entries if e['id'] not in chosen_ids][:max(0,limit-len(chosen))]
    random.Random(3060).shuffle(chosen)
    return dict(schema=1,source_database=str(Path(database).resolve()),requested=limit,available_distinct=len(entries),
        selected=len(chosen),target_met=len(chosen)>=50,seed=3060,
        source='Recorded Spider-Man OCR; no invented fillers; human OCR review required',
        luna_is_gold_reference=False,short_max_chars=60,entries=chosen)


def audit(database):
    db=readonly(database);db.row_factory=sqlite3.Row
    try:
        jobs=[dict(r) for r in db.execute('''SELECT j.*,s.first_seen_mono,s.last_seen_mono
            FROM translation_jobs j JOIN subtitles s ON s.id=j.subtitle_id ORDER BY j.session,j.id''')]
        for job in jobs:
            # Old databases keep api_called DEFAULT 1. A new local job must
            # never be counted as a historical paid request because of that
            # inherited default. Prefer its new start clock when available.
            start=job.get('translation_start_mono')
            if start is not None:job['api_start_mono']=start
            else:job.setdefault('api_start_mono',None)
            job['api_called']=bool(job.get('api_called')) and not job['model'].startswith('local:')
        stages={}
        for name,a,b,api_only in [('ocr_accept_ms','first_seen_mono','accepted_mono',False),
                ('queue_ms','accepted_mono','api_start_mono',False),('api_ms','api_start_mono','ready_mono',True),
                ('result_to_sent_ms','ready_mono','overlay_sent_mono',False),
                ('result_to_renderer_ms','ready_mono','visible_mono',False),
                ('first_seen_to_renderer_ms','first_seen_mono','visible_mono',False)]:
            stages[name]=percentiles([(j[b]-j[a])*1000 for j in jobs if j[a] is not None and j[b] is not None and j[b]>=j[a]
                        and (not api_only or j['api_called'] and j['translation_state']=='completed')])
            stages[name]['invalid_negative_samples']=sum(j[a] is not None and j[b] is not None and j[b]<j[a] for j in jobs)
        first=[];later=[];seen=set();sessions=[]
        for j in jobs:
            if not j['api_called'] or j['translation_state']!='completed' or j['api_start_mono'] is None or j['ready_mono'] is None:continue
            duration=(j['ready_mono']-j['api_start_mono'])*1000
            if j['session'] not in seen:
                first.append(duration);seen.add(j['session'])
                sessions.append(dict(session=j['session'],first_job=j['id'],first_api_ms=duration,
                    first_queue_ms=(j['api_start_mono']-j['accepted_mono'])*1000))
            else:later.append(duration)
        duplicates=[]
        for a,b in zip(jobs,jobs[1:]):
            if a['session']!=b['session']:continue
            sa,ba=split_speaker(a['source']);sb,bb=split_speaker(b['source'])
            if sa.casefold()==sb.casefold() and equivalent(ba,bb):duplicates.append([a['id'],b['id']])
        frames=[dict(r) for r in db.execute('SELECT * FROM ocr_frames ORDER BY session,captured_mono,id')]
        from ediz_game_translator.capture.dialogue_filter import dialogue_candidates
        from ediz_game_translator.capture.subtitle_tracking import ActiveSubtitles
        baseline_module=ModuleType('_baseline_tracking');sys.modules[baseline_module.__name__]=baseline_module
        source=Path(__file__).resolve().parents[1].joinpath('capture/subtitle_tracking.py').read_text(encoding='utf-8')
        exec(compile(source,'baseline_subtitle_tracking.py','exec'),baseline_module.__dict__)
        replays=[]
        for session in sorted({f['session'] for f in frames}):
            before=baseline_module.ActiveSubtitles();after=ActiveSubtitles();counts=[0,0];new_counts=[0,0];cost=[]
            for f in (f for f in frames if f['session']==session):
                candidates,_=dialogue_candidates(SimpleNamespace(txts=json.loads(f['raw_texts']),scores=json.loads(f['raw_scores']),
                    boxes=json.loads(f['raw_boxes']) if f['raw_boxes'] else None),960,160)
                for i,tracker in enumerate((before,after)):
                    began=time.perf_counter();actions=tracker.update(candidates,f['captured_mono'])
                    if i:cost.append((time.perf_counter()-began)*1000)
                    counts[i]+=sum(a.dispatch for a in actions);new_counts[i]+=sum(a.new for a in actions)
            replays.append(dict(session=session,before_dispatch=counts[0],after_dispatch=counts[1],
                                before_tracks=new_counts[0],after_tracks=new_counts[1],tracking_ms=percentiles(cost)))
        return dict(jobs=len(jobs),paid_calls_made=0,stages_ms=stages,first_api_ms=percentiles(first),later_api_ms=percentiles(later),
            sessions=sessions,adjacent_equivalent_job_pairs=duplicates,replays=replays,raw_frames=len(frames),
            limits=['Historical api_ms includes client call and result processing; transport/server breakdown unavailable.',
                    'First request is first recorded paid call per session, not proven process cold start.',
                    'Renderer acknowledgement does not measure physical PS5/TV pixels.',
                    'Replay uses saved OCR outputs, not fresh OCR or model generation.'])
    finally:db.close()


class ResourceSampler:
    def __init__(self):self.samples=[];self.stop=threading.Event();self.pid=None
    def __enter__(self):
        import psutil
        self.psutil=psutil;psutil.cpu_percent()
        self.observed_processes=sorted({r.info['name'] for r in psutil.process_iter(['name'])
            if (r.info['name'] or '').casefold() in ('obs64.exe','edizgametranslator.exe','python.exe','pythonw.exe')})
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start();return self
    def _run(self):
        p=self.psutil
        last_cpu=None
        while not self.stop.is_set():
            sample=dict(at=time.monotonic(),system_cpu_percent=p.cpu_percent(),ram_used_mib=p.virtual_memory().used/2**20,
                        ram_available_mib=p.virtual_memory().available/2**20)
            if self.pid:
                try:
                    process=p.Process(self.pid)
                    # Windows venv launchers delegate to a child python.exe.
                    # Account for the entire owned process tree, not just the launcher.
                    processes=[process]+process.children(recursive=True)
                    sample.update(worker_rss_mib=sum(x.memory_info().rss for x in processes)/2**20,
                                  worker_cpu_seconds=sum(sum(x.cpu_times()[:2]) for x in processes),
                                  worker_process_count=len(processes))
                    if last_cpu:
                        sample['worker_cpu_one_core_percent']=100*(sample['worker_cpu_seconds']-last_cpu[1])/(sample['at']-last_cpu[0])
                    last_cpu=(sample['at'],sample['worker_cpu_seconds'])
                except p.Error:pass
            try:
                r=subprocess.run(['nvidia-smi','--query-gpu=memory.used,memory.free,utilization.gpu,utilization.memory',
                    '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if r.returncode==0:
                    fields=[float(v.strip()) for v in r.stdout.splitlines()[0].split(',')]
                    sample.update(zip(('gpu_used_mib','gpu_free_mib','gpu_util_percent','gpu_memory_util_percent'),fields))
            except (OSError,ValueError,subprocess.TimeoutExpired):pass
            self.samples.append(sample);self.stop.wait(.25)
    def __exit__(self,*_):self.stop.set();self.thread.join(timeout=3)


def run_benchmark(args):
    corpus=json.loads(Path(args.corpus).read_text(encoding='utf-8'))
    if not corpus.get('target_met'):raise ValueError('Corpus has fewer than 50 distinct lines; add genuine recordings first.')
    if args.experimental_context and not args.model.startswith('translategemma'):raise ValueError('Context mode is TranslateGemma-only')
    client=None;results=[];failure=None;cold_wall=None;warmup=None
    with ResourceSampler() as resources:
        try:
            started=time.perf_counter()
            client=LocalWorkerClient(args.python,args.model,args.path,args.precision,
                on_start=lambda pid:setattr(resources,'pid',pid))
            cold_wall=(time.perf_counter()-started)*1000;resources.pid=client.process.pid
            # Warm-up excluded from p50/p95; no application cache is used.
            warmup=client.translate('Please wait here until I return.')
            for repeat in range(args.repeats):
                for e in corpus['entries']:
                    began=time.perf_counter()
                    try:
                        response=client.translate(e['source'],e['context'] if args.experimental_context else '',args.experimental_context)
                        results.append(dict(id=e['id'],repeat=repeat,length_group=e['length_group'],
                            roundtrip_ms=(time.perf_counter()-began)*1000,**response))
                    except Exception as exc:
                        results.append(dict(id=e['id'],repeat=repeat,length_group=e['length_group'],error=str(exc),complete=False))
                        raise
        except Exception as exc:failure=f'{type(exc).__name__}: {exc}'
        finally:
            if client:client.close()
    summary={}
    for group in ('all','short','long'):
        rows=[r for r in results if group=='all' or r['length_group']==group]
        good=[r for r in rows if r.get('complete')]
        summary[group]=dict(attempted=len(rows),complete=len(good),
            full_sentence_ms=percentiles([r['full_sentence_ms'] for r in good]),
            worker_roundtrip_ms=percentiles([r['roundtrip_ms'] for r in good]),
            execution_failure_rate=(len(rows)-len(good))/len(rows) if rows else None)
    report=dict(model_id=LOCAL_MODELS[args.model],precision=args.precision,workload_label=args.workload,
        workload_verified=False,experimental_context=args.experimental_context,
        cold_process_to_ready_ms=cold_wall,ready=client.ready if client else None,
        warmup=warmup,summary=summary,results=results,resources=resources.samples,
        failure=failure,paid_calls_made=0,downloads_made=0,quality_error_rate=None,
        quality_status='Human review required; recorded Luna translations are not gold.',
        corpus_sha256=hashlib.sha256(Path(args.corpus).read_bytes()).hexdigest())
    report['observed_process_names']=resources.observed_processes
    report['resource_summary']={key:percentiles([s[key] for s in resources.samples if key in s])
        for key in ('worker_rss_mib','worker_cpu_one_core_percent','system_cpu_percent','ram_available_mib',
                    'gpu_used_mib','gpu_free_mib','gpu_util_percent','gpu_memory_util_percent')}
    report['resource_sampling_note']='250 ms plus nvidia-smi command time; may miss brief peaks. GPU usage is device-wide, including OBS/OCR; torch allocated/reserved metrics are worker-only.'
    return report


QUALITY_FIELDS=['accuracy_1_5','naturalness_1_5','names_error','negation_error',
                'meaning_loss','incomplete','extra_text','review_notes']


def review_sheet(corpus_path,result_path,output):
    corpus=json.loads(Path(corpus_path).read_text(encoding='utf-8'))
    result=json.loads(Path(result_path).read_text(encoding='utf-8'))
    if result['corpus_sha256']!=hashlib.sha256(Path(corpus_path).read_bytes()).hexdigest():
        raise ValueError('Corpus/result mismatch')
    entries={e['id']:e for e in corpus['entries']}
    with Path(output).open('x',encoding='utf-8-sig',newline='') as f:
        fields=['id','repeat','length_group','speaker','source','local_text','luna_reference_not_gold','execution_complete']+QUALITY_FIELDS
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in result['results']:
            e=entries[r['id']]
            writer.writerow(dict(id=e['id'],repeat=r['repeat'],length_group=e['length_group'],speaker=e['speaker'],
                source=e['source'],local_text=r.get('text',''),execution_complete=r.get('complete',False),
                luna_reference_not_gold=' | '.join(ref['text'] for ref in e['luna_references'])))


def quality_summary(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    flags=QUALITY_FIELDS[2:-1];reviewed=[]
    for r in rows:
        if all(r.get(k) in ('0','1') for k in flags) and all(r.get(k) in ('1','2','3','4','5') for k in QUALITY_FIELDS[:2]):reviewed.append(r)
    result=dict(rows=len(rows),reviewed=len(reviewed),unreviewed=len(rows)-len(reviewed),groups={})
    for group in ('all','short','long'):
        subset=[r for r in reviewed if group=='all' or r['length_group']==group]
        result['groups'][group]=dict(n=len(subset),
            quality_error_rate=sum(any(r[k]=='1' for k in flags) for r in subset)/len(subset) if subset else None,
            accuracy_mean=statistics.mean(int(r['accuracy_1_5']) for r in subset) if subset else None,
            naturalness_mean=statistics.mean(int(r['naturalness_1_5']) for r in subset) if subset else None,
            error_counts={k:sum(r[k]=='1' for r in subset) for k in flags})
    return result


def download(args):
    if not args.allow_download:raise ValueError('Explicit --allow-download is required')
    from huggingface_hub import HfApi,snapshot_download
    model_id=LOCAL_MODELS[args.model];revision=HfApi().model_info(model_id).sha
    folder=Path(args.path).resolve()
    if folder.exists() and any(folder.iterdir()):raise ValueError('Choose a new empty model folder')
    snapshot_download(model_id,revision=revision,local_dir=folder,
        allow_patterns=['*.json','*.safetensors','*.model','*.jinja','README.md'])
    write_new(folder/'ediz_model.json',dict(model_id=model_id,revision=revision,downloaded_utc=time.time()))


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    e=sub.add_parser('export');e.add_argument('--database',required=True);e.add_argument('--output',required=True);e.add_argument('--limit',type=int,default=75)
    a=sub.add_parser('audit');a.add_argument('--database',required=True);a.add_argument('--output',required=True)
    r=sub.add_parser('run');r.add_argument('--corpus',required=True);r.add_argument('--output',required=True)
    r.add_argument('--model',choices=LOCAL_MODELS,required=True);r.add_argument('--path',required=True);r.add_argument('--python',default=sys.executable)
    r.add_argument('--precision',choices=['nf4','bf16'],default='nf4');r.add_argument('--repeats',type=int,default=3)
    r.add_argument('--experimental-context',action='store_true');r.add_argument('--workload',choices=['idle','obs-ocr'],required=True)
    d=sub.add_parser('download');d.add_argument('--allow-download',action='store_true');d.add_argument('--model',choices=LOCAL_MODELS,required=True);d.add_argument('--path',required=True)
    v=sub.add_parser('review');v.add_argument('--corpus',required=True);v.add_argument('--result',required=True);v.add_argument('--output',required=True)
    q=sub.add_parser('quality');q.add_argument('--review',required=True);q.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command=='download':download(args);return
    if Path(args.output).exists():raise FileExistsError('Choose a new output file')
    if args.command=='review':review_sheet(args.corpus,args.result,args.output);return
    if args.command=='export':report=export_corpus(args.database,args.limit)
    elif args.command=='audit':report=audit(args.database)
    elif args.command=='quality':report=quality_summary(args.review)
    else:
        if not 1<=args.repeats<=10:raise ValueError('Repeats must be 1–10')
        report=run_benchmark(args)
    write_new(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('entries','results','resources','replays','sessions')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
