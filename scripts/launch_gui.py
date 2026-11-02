"""Entry for the portable0109/v1.8 host. Import and check-only are hardware-free."""
import argparse,json,os,runpy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['PYTHONPATH']=str(ROOT/'scripts')+os.pathsep+os.environ.get('PYTHONPATH','')
from export_paths import repo_path
from export_guard import verify
def main():
    verify()
    target=repo_path('YMW/work/host_speed_step3_0109_20261031/launch.py')
    sys.path.insert(0,str(target.parent))
    runpy.run_path(str(target),run_name='__main__')
if __name__=='__main__':main()
