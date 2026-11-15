"""Real RapidOCR on a generated image; NO OBS, game, API, or screen capture.

Run manually; initialization and cadence measurements are machine-specific.
"""
from contextlib import closing
import json
import argparse
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from rapidocr import RapidOCR
from capture_pipeline import CaptureRunner, DiagnosticLog
from obs_capture import crop_frame
from subtitle_store import SubtitleStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--output", default="OCR_LOCAL_BENCHMARK.json")
    args = parser.parse_args()
    image = Image.new('RGB', (1920,1080), '#283038')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 42)
    draw.multiline_text((960,840), 'Stay close.\nWe are almost there.', font=font,
                        fill='white', stroke_width=2, stroke_fill='black', anchor='mm', align='center')
    began = time.monotonic()
    params = {"EngineConfig.onnxruntime.intra_op_num_threads": args.threads,
              "EngineConfig.onnxruntime.inter_op_num_threads": 1} if args.threads else None
    ocr = RapidOCR(params=params)
    init_seconds = time.monotonic()-began
    reports = []
    for interval in (.8,.28):
        with tempfile.TemporaryDirectory() as folder:
            store = SubtitleStore(Path(folder)/'synthetic.sqlite3')
            runner = CaptureRunner(lambda: image.copy(), lambda img: crop_frame(img,0,65,100,94),
                ocr, store, 'synthetic', DiagnosticLog(), lambda: None, lambda *args: None, interval)
            for _ in range(8):
                time.sleep(runner.step())
            reports.append(dict(target_interval=interval, **runner.metrics.summary()))
            with closing(__import__('sqlite3').connect(Path(folder)/'synthetic.sqlite3')) as db:
                reports[-1]['recognized'] = [r[0] for r in db.execute('SELECT text FROM subtitles')]
            store.close()
    report = dict(kind='synthetic_image_real_rapidocr_not_game', init_seconds=init_seconds, intra_op_threads=args.threads,
                  reports=reports)
    Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
