"""Explicit source-only tool dispatcher. No model downloads on startup."""
from pathlib import Path
import runpy
import sys

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'src'),str(root/'tests'),str(root/'tools/benchmarks')]
modules={'benchmark-light':'benchmark_light','benchmark-large':'local_benchmark','prepare-light':'prepare_light_model'}
if len(sys.argv)<2:raise SystemExit('Choose: benchmark-light, benchmark-large, prepare-light or a tools script name')
name=sys.argv.pop(1)
if name in modules:runpy.run_module('ediz_game_translator.benchmarks.'+modules[name],run_name='__main__')
else:
    paths=[p for folder in ('benchmarks','smoke') if (p:=root/'tools'/folder/(name+'.py')).is_file()]
    if len(paths)!=1:raise SystemExit('Unknown tool')
    runpy.run_path(str(paths[0]),run_name='__main__')
