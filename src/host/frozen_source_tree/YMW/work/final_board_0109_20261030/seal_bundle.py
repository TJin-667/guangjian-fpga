"""Seal exact candidate files; outputs and qualification stay outside this tree."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    reset=dict(schema='guangjian-0109-reset-tool-binding-v1',files_sha256={'reset_window.py':sha(HERE/'reset_window.py')})
    (HERE/'RESET_TOOL_BINDING.json').write_text(json.dumps(reset,indent=2)+'\n',encoding='utf-8')
    files={p.relative_to(HERE).as_posix():sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='SOURCE_BINDING.json' and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.jou','.dcp','.bit')}
    (HERE/'SOURCE_BINDING.json').write_text(json.dumps(dict(schema='guangjian-0109-source-binding-v1',files_sha256=files),indent=2)+'\n',encoding='utf-8')
    print('SEALED0109_SOURCE_FILES',len(files),flush=True)
if __name__=='__main__':main()
