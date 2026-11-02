"""Install only the new 09 console. Existing bit and entries 01--08 are read-only."""
import argparse
import shutil
import sys
from pathlib import Path
from common import ROOT, digest, read_json, write_json, require, verify_vendor
import capture_adapter as capture


def install(lab, python, apply=False):
    lab, python = Path(lab).resolve(), Path(python).resolve()
    require(lab.is_dir() and python.is_file(), 'LAB/Python path missing')
    require('"' not in str(python) and '%' not in str(python), 'Unsupported launcher path')
    verify_vendor()
    old = capture.legacy(lab)
    core = old.load_core(lab)
    core.verify_vendor()
    require(digest(lab/'bx72_0105_lab.bit') == core.BIT_SHA, 'LAB bit identity differs')
    target, command = lab/'inspection_console_v1', lab/'09_inspection_console.cmd'
    require(not target.exists() and not command.exists(), '09 already installed; preserve it and review before replacement')
    protected = {str(p):digest(p) for p in lab.glob('*.cmd')}
    for rel in ['bx72_0105_lab.bit','bx72_0104_rollback.bit','auto_exposure_r3/app_core.py','fourlight_fixed_v1/fourlight_capture.py']:
        protected[str(lab/rel)] = digest(lab/rel)
    report = dict(install_requested=apply, target=str(target), command=str(command), physical_board_contacted=False)
    if not apply:
        return report
    names = ['common.py','analysis_worker.py','capture_adapter.py','workflow.py','inspection_app.py',
             'vendor_manifest.json','README.md','OPERATOR_STEPS.txt','requirements.txt']
    target.mkdir(exist_ok=False)
    for name in names:
        shutil.copyfile(ROOT/name, target/name)
    shutil.copytree(ROOT/'vendor', target/'vendor')
    installed = {p.relative_to(target).as_posix():digest(p) for p in target.rglob('*') if p.is_file()}
    for name, sha in installed.items():
        require(digest(ROOT/name) == sha, 'Installed byte comparison failed: '+name)
    launcher = '@echo off\r\ncd /d "%~dp0"\r\n"'+str(python)+'" -B "%~dp0inspection_console_v1\\inspection_app.py" --lab-root "%~dp0."\r\nif errorlevel 1 pause\r\n'
    with command.open('xb') as stream:
        stream.write(launcher.encode('ascii'))
    require({p:digest(p) for p in protected} == protected, 'An original file changed unexpectedly')
    report.update(installed_files=installed, launcher_sha256=digest(command), original_files_unchanged=True,
                  rollback='Close 09 and use the unchanged 06/07/08 entries. No firmware change needed.')
    write_json(target/'installation.json', report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root',type=Path,default=Path('C:/BX72_0105_LAB'))
    p.add_argument('--python',type=Path,default=Path(sys.executable))
    p.add_argument('--install',action='store_true')
    a=p.parse_args()
    print(__import__('json').dumps(install(a.lab_root,a.python,a.install),ensure_ascii=False,indent=2))
