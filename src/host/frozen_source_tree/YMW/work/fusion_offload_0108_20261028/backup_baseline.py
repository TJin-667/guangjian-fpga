"""Copy the existing working mode, verify bytes, and never alter its launchers."""
import argparse, hashlib, json, subprocess, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKIP = {'__pycache__', '.pytest_cache', 'verification', 'results', 'reviews', 'backups', '.git'}
CODE = {'.py','.v','.sv','.vh','.svh','.tcl','.xdc','.json','.md','.txt','.cmd','.ps1','.dll','.c','.h','.bit','.xci','.prj'}

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True,type=Path);a=ap.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    roots=[Path('C:/BX72_0105_LAB'),Path('C:/BX72_P0_PAIRS/20261026'),Path('C:/BX72_B1_DETECT/20261027'),
           Path('E:/GuangjianData/software/B1_Detection_20261027/vendor_8c697e8')]
    # Capture revisions import earlier workflow/SDK modules. Preserve all code
    # under YMW/work and pinned TJ sources, not just the visible GUI entry file.
    roots += [REPO/'YMW/work',REPO/'TJ/work/fpga_image_pipeline',
              REPO/'YMW/handoffs/fusion_final_400_800_20261028',
              Path('C:/bx72_ymw_0105_20261015/board_2018_r5/ymw')]
    items={}
    for root in roots:
        if not root.is_dir(): raise FileNotFoundError(root)
        for p in root.rglob('*'):
            rel=p.relative_to(root)
            if p.is_file() and not any(v in SKIP for v in rel.parts) and p.suffix.lower() in CODE:
                # Do not back up this evolving candidate as the old baseline.
                if 'fusion_offload_0108_20261028' in p.parts: continue
                name=p.as_posix().replace(':','',1)
                items[name]=(p,sha(p),p.stat().st_size)
    frozen=json.loads((REPO/'YMW/handoffs/fusion_final_400_800_20261028/FROZEN_CONFIG.json').read_text('utf-8'))
    for rel,digest in frozen['capture_bound_files_sha256'].items():
        assert sha(REPO/'YMW/work/p0_pair_console_0107_20261027_r56'/rel)==digest, rel
    for rel,digest in frozen['detection_app_files_sha256'].items():
        assert sha(REPO/'YMW/work/b1_detection_console_20261027'/rel)==digest, rel
    bit=REPO/'YMW/work/acceptance_0107_20261026/artifact/bx72_0107_acceptance_EXPERIMENTAL_NOT_RELEASED.bit'
    assert sha(bit)=='4d1545266f83a6eb52327e4863658fa465448c04572b595cbe6dbc482850a01b'
    archive=out/'working_mode_before_0108.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for name,(p,digest,size) in sorted(items.items()): z.write(p,name)
    with zipfile.ZipFile(archive) as z:
        for name,(p,digest,size) in items.items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest, name
            assert sha(p)==digest, 'Changed while copying: '+str(p)
    report=dict(status='BACKUP_BYTE_VERIFIED',baseline_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        archive=str(archive),archive_sha256=sha(archive),files=len(items),uncompressed_bytes=sum(v[2] for v in items.values()),
        files_sha256={str(p):dict(sha256=digest,bytes=size,archive_member=name) for name,(p,digest,size) in items.items()},
        raw_data='Existing E:/GuangjianData/P0Pairs and B1Detection remain in place; not duplicated',
        runtime='Existing Python virtual environment preserved in place; package versions recorded separately',
        board_commands=0,launchers_changed=False)
    (out/'BACKUP_MANIFEST.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    (out/'RESTORE.md').write_text('Backup of the existing working mode before 0108.\n'
        'Do not extract over an active installation. Inspect BACKUP_MANIFEST.json, extract to a separate directory, and verify SHA256 first.\n'
        'ZIP member C/... maps to original C:/...; E/... maps to original E:/....\n'
        'Original programs and launchers are unchanged and remain the default.\n'
        'Current 0107 capture uses the backed-up 0107 bit; old 09 uses its own 0105 LAB bit. Do not mix their protocols.\n'
        'Raw captures/results and the Python virtual environment remain at their existing paths.\n','utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='files_sha256'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
