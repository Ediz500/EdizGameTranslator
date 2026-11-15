from pathlib import Path
import sys

def configure_paths():
    root=Path(__file__).resolve().parents[1]
    for folder in (root,root/'src',root/'tests',root/'tools/benchmarks'):
        if str(folder) not in sys.path:sys.path.insert(0,str(folder))
