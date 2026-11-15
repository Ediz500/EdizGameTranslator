"""Explicit, optional OPUS-MT download/conversion; never imported at app startup."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import os

MODEL='Helsinki-NLP/opus-mt-tc-big-en-tr'
REVISION='e539fc16a8a1a0ea5950eb339b595bfcce990e90'


def prepare(folder,download=True):
    from huggingface_hub import snapshot_download
    from ctranslate2.converters import TransformersConverter
    folder=Path(folder).resolve();source=folder/'source';target=folder/'ct2-int8'
    if target.exists():raise FileExistsError('Choose a new conversion target')
    if download:
        snapshot_download(MODEL,revision=REVISION,local_dir=source,
            allow_patterns=['pytorch_model.bin','*.json','*.spm','README.md'])
    # SentencePiece's Windows file API may reject Unicode absolute paths.
    # Conversion is a standalone process; ASCII relative paths avoid that bug.
    previous=Path.cwd()
    try:
        os.chdir(folder)
        converter=TransformersConverter('source',trust_remote_code=False)
        converter.convert('ct2-int8',quantization='int8')
    finally:os.chdir(previous)
    for name in ('source.spm','target.spm'):shutil.copy2(source/name,target/name)
    manifest=dict(schema=1,engine='ct2-marian',model_id=MODEL,revision=REVISION,
        source_lang='en',target_lang='tr',license='CC-BY-4.0',quantization='int8',
        files={n:hashlib.sha256((target/n).read_bytes()).hexdigest() for n in ('model.bin','source.spm','target.spm')})
    (target/'ediz_nmt.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(dict(model=MODEL,revision=REVISION,converted_mib=(target/'model.bin').stat().st_size/2**20)))


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--allow-download',action='store_true');g.add_argument('--offline-convert',action='store_true')
    p.add_argument('--output',required=True);a=p.parse_args();prepare(a.output,a.allow_download)
