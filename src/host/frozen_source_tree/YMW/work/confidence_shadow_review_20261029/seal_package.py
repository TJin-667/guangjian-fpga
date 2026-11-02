"""Bind this experiment's source; frozen detector has its own independent binding."""
import hashlib,json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def main():
    files=sorted([*HERE.glob('*.py'),*HERE.glob('PLAN*.json')],key=lambda p:p.name)
    binding=dict(schema='confidence-shadow-package-v1',formal_config_id='4c0be2d44fdd',
        formal_package_sha256=hashlib.sha256((HERE.parent/'joint_threshold_tuning_20261029/PACKAGE_BINDING.json').read_bytes()).hexdigest(),
        files_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (HERE/'PACKAGE_BINDING.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('CONFIDENCE_SOURCE_BOUND',len(files),'files')

if __name__=='__main__':main()
