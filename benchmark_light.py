"""Real warm-model timings, kept distinct from OCR/TV latency."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time
from light_translation import WarmNMTClient
from local_benchmark import ResourceSampler,percentiles


def benchmark(args):
    corpus=json.loads(Path(args.corpus).read_text(encoding='utf-8'))
    results=[];client=None;error=None;ready=None;cold=None
    with ResourceSampler() as sampler:
        try:
            began=time.perf_counter()
            client=WarmNMTClient(args.python,args.model_path,device=args.device,
                compute_type=args.compute_type,workers=args.workers,threads=args.threads,
                beam_size=args.beam_size,
                on_start=lambda pid:setattr(sampler,'pid',pid))
            cold=(time.perf_counter()-began)*1000;ready=client.ready
            def run(item):
                repeat,e=item;began=time.perf_counter()
                try:
                    result=client.translate(e['source'])
                    return dict(result,id=e['id'],repeat=repeat,source=e['source'],length_group=e['length_group'],
                                submitted_to_complete_ms=(time.perf_counter()-began)*1000)
                except Exception as exc:return dict(id=e['id'],repeat=repeat,complete=False,error=str(exc),length_group=e['length_group'])
            jobs=[(r,e) for r in range(args.repeats) for e in corpus['entries']]
            with ThreadPoolExecutor(max_workers=args.workers if args.parallel else 1) as pool:
                results=list(pool.map(run,jobs))
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'
        finally:
            if client:client.close()
    groups={}
    for group in ('all','short','long'):
        rows=[r for r in results if group=='all' or r['length_group']==group]
        good=[r for r in rows if r.get('complete')]
        groups[group]=dict(attempts=len(rows),completed=len(good),
            processing_ms=percentiles([r['processing_ms'] for r in good]),
            roundtrip_ms=percentiles([r['roundtrip_ms'] for r in good]),
            execution_failure_rate=(len(rows)-len(good))/len(rows) if rows else None)
    return dict(kind='real_local_model_only',device=args.device,compute_type=args.compute_type,
        workers=args.workers,threads=args.threads,beam_size=args.beam_size,parallel=args.parallel,workload=args.workload,
        workload_verified=False,cold_process_to_ready_ms=cold,ready=ready,error=error,groups=groups,
        results=results,resources=sampler.samples,quality_error_rate=None,paid_api_calls=0,
        observed_process_names=sampler.observed_processes,
        resource_summary={key:percentiles([s[key] for s in sampler.samples if key in s])
            for key in ('worker_rss_mib','worker_cpu_one_core_percent','system_cpu_percent','ram_used_mib',
                        'gpu_used_mib','gpu_free_mib','gpu_util_percent')},
        resource_note='Worker RSS/CPU includes Windows venv launcher descendants. GPU/RAM totals are device/system-wide; 250 ms plus query overhead may miss peaks.',
        corpus_sha256=hashlib.sha256(Path(args.corpus).read_bytes()).hexdigest(),
        limitation='No capture/OCR/render/physical TV timing included. No quality grade inferred from execution success.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--python',default=sys.executable)
    p.add_argument('--model-path',required=True);p.add_argument('--corpus',required=True)
    p.add_argument('--output',required=True);p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    p.add_argument('--compute-type',default='int8');p.add_argument('--workers',type=int,default=2)
    p.add_argument('--threads',type=int,default=2);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--beam-size',type=int,choices=[1,2,4],default=1)
    p.add_argument('--parallel',action='store_true');p.add_argument('--workload',choices=['idle','obs-ocr'],default='idle')
    a=p.parse_args()
    if Path(a.output).exists():raise FileExistsError('Choose a new report')
    r=benchmark(a);Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k not in ('results','resources')},ensure_ascii=True,indent=2))
