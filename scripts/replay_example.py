"""Run the byte-preserved, offline frozen numerical example."""
from pathlib import Path
import runpy
ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'data/examples/portable004/replay_case.py'),run_name='__main__')
