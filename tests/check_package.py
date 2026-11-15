"""Inspect explicit build artifacts, never open APPDATA or the keyring."""
import hashlib
import json
from pathlib import Path


def check():
    root=Path(__file__).resolve().parents[1];folder=root/'dist'/'EdizGameTranslator'
    files=[p for p in folder.rglob('*') if p.is_file()]
    forbidden=[str(p.relative_to(folder)) for p in files if p.name in ('settings.json','ledger.json','.env') or p.name.endswith(('.sqlite3','.sqlite3-wal','.sqlite3-shm','.jsonl','.srt','.key'))]
    models=sorted(p.name for p in files if p.suffix=='.onnx')
    exe=folder/'EdizGameTranslator.exe'
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))}
    report=dict(exe=str(exe),exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        files=len(files),total_mib=round(sum(p.stat().st_size for p in files)/1024**2,2),
        onnx_models=models,forbidden_user_files=forbidden,source_sha256=sources)
    report['ok']=not forbidden and all(name in models for name in ('PP-OCRv6_det_small.onnx','PP-OCRv6_rec_small.onnx'))
    (root/'PACKAGE_CONTENT_CHECK.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))
    if not report['ok']:raise RuntimeError('Package contents failed validation')


if __name__=='__main__':check()
