"""API-free comparisons. Synthetic CER is not real-game OCR accuracy."""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from PIL import Image,ImageDraw,ImageFont
from ediz_game_translator.core import clean_ocr
from ediz_game_translator.capture.ocr_profiles import create_ocr


def distance(a,b):
    previous = list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        current=[i]
        for j,cb in enumerate(b,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(ca!=cb)))
        previous=current
    return previous[-1]


def stats(values):
    return dict(p50=statistics.median(values),p95=sorted(values)[math.ceil(.95*len(values))-1])


def synthetic():
    cases=[]
    for size in (42,30,22):
        img=Image.new('RGB',(1920,313),'#283038')
        d=ImageDraw.Draw(img)
        text='Spider-Man: Stay close. We are almost there.'
        d.text((960,155),text,font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',size),
               fill='white',stroke_width=1,stroke_fill='black',anchor='mm')
        cases.append((f'synthetic_font{size}',img,text))
    return cases


def offline(args):
    cases=synthetic()
    if args.manifest:
        manifest=Path(args.manifest)
        cases=[(str(i),Image.open(manifest.parent/row['image']).convert('RGB'),row['text'])
               for i,row in enumerate(json.loads(manifest.read_text(encoding='utf-8')))]
    if args.calibration:
        cases.append(('unlabelled_calibration',Image.open(args.calibration).convert('RGB'),None))
    reports=[]
    references={}
    for profile in args.profiles.split(','):
        ocr=create_ocr(profile)
        for width in (1920,1280,960):
            for name,image,truth in cases:
                crop=image.resize((width,round(image.height*width/image.width)),Image.Resampling.LANCZOS)
                durations=[]
                cpu=time.process_time(); wall=time.perf_counter()
                # First call loads weights lazily; keep it separate from warm measurements.
                cold=time.perf_counter(); ocr(crop); cold=(time.perf_counter()-cold)*1000
                observed=''
                for _ in range(args.samples):
                    began=time.perf_counter(); result=ocr(crop)
                    durations.append((time.perf_counter()-began)*1000)
                    observed=clean_ocr(' '.join(getattr(result,'txts',None) or []))
                if profile=='baseline' and width==1920:
                    references[name]=observed
                reference=clean_ocr(truth) if truth else references.get(name,'')
                reports.append(dict(profile=profile,width=width,case=name,ocr_ms=stats(durations),
                    setup_call_ms=cold,samples=args.samples,
                    cpu_one_core_percent=100*(time.process_time()-cpu)/(time.perf_counter()-wall),
                    character_error_rate=distance(reference,observed)/max(1,len(reference)) if truth else None,
                    reference_characters=len(reference),observed_characters=len(observed),
                    disagreement_with_baseline=distance(reference,observed)/len(reference) if not truth and reference else None))
        print('completed',profile,flush=True)
    return dict(kind='local_images_no_obs_no_api',reports=reports)


def live(args):
    # Runtime secrets are fetched from Credential Manager, never printed or written.
    from ediz_game_translator.app import secret_get
    from ediz_game_translator.core import load_settings
    from ediz_game_translator.capture.obs_capture import crop_frame
    from legacy_capture import LegacyObsSource as ObsSource
    settings=load_settings()
    source=settings['obs_source']
    reports=[]
    for width in (1920,1280,960):
        obs=ObsSource(secret_get('obs_password'),settings['obs_port'],width=width)
        try:
            ocr=create_ocr(args.profiles.split(',')[-1])
            shot_times=[]; ocr_times=[]; cycles=[]
            for _ in range(args.samples):
                start=time.perf_counter(); image=obs.frame(source)
                shot_end=time.perf_counter()
                crop=crop_frame(image,*[settings[k] for k in ('crop_left','crop_top','crop_right','crop_bottom')])
                begin=time.perf_counter(); ocr(crop); end=time.perf_counter()
                shot_times.append((shot_end-start)*1000); ocr_times.append((end-begin)*1000)
                cycles.append((end-start)*1000)
            reports.append(dict(width=width,samples=args.samples,screenshot_ms=stats(shot_times),
                                ocr_ms=stats(ocr_times),cycle_ms=stats(cycles),accuracy=None))
        finally: obs.close()
    return dict(kind='live_obs_no_api_no_scene_changes',reports=reports,
                accuracy_note='Unlabelled moving video; accuracy cannot be inferred from text agreement.')


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--samples',type=int,default=3)
    parser.add_argument('--profiles',default='baseline,bounded960,bounded1280')
    parser.add_argument('--calibration')
    parser.add_argument('--manifest',help='JSON list of {image: relative cropped-image path, text: ground truth}')
    parser.add_argument('--output',default='PERF_COMPARISON.json')
    args=parser.parse_args()
    if not 1<=args.samples<=300: parser.error('samples must be 1..300')
    report=live(args) if args.live else offline(args)
    Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('report:',args.output)
