"""Seal isolated UI bytes only after regenerating and before qualification."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    runtime=HERE/'runtime'
    value=dict(schema='guangjian-0109-runtime-binding-v1',inherited_stable_binding_sha256=sha(HERE.parent/'final_system_20261029/SYSTEM_BINDING.json'),files_sha256={p.name:sha(p) for p in runtime.glob('*.py')},frozen_algorithm='f09eb5885e1d')
    (runtime/'RUNTIME_BINDING.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
