"""Regression checks using synthetic bytes, without distributing upstream originals."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent


def main():
    cases=[]
    with tempfile.TemporaryDirectory(prefix='guangjian_policy_') as directory:
        root=Path(directory)
        (root/'scripts').mkdir()
        for name in ('verify_public_release.py','publication_policy.py'):
            shutil.copy2(HERE/name,root/'scripts'/name)
        raw=b'Guangjian synthetic external-content policy fixture, not vendor material.\n'
        digest=hashlib.sha256(raw).hexdigest()
        (root/'external_dependencies.json').write_text(json.dumps(dict(files=[dict(
            path='licensed/reference.prj',bytes=len(raw),sha256=digest)])),encoding='utf-8')
        def seal():
            files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='file_manifest.sha256' and '__pycache__' not in p.parts)
            (root/'file_manifest.sha256').write_text(''.join(
                hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix()+'\n'
                for p in files if not p.relative_to(root).as_posix().startswith('licensed/')),encoding='utf-8')
        def check(name,publication,success,match=False):
            command=[sys.executable,'-B',str(root/'scripts/verify_public_release.py')]
            if publication:command.append('--for-publication')
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
            value=json.loads(result.stdout)
            if (result.returncode==0)!=success or bool(value['restricted_content_matches'])!=match:
                raise RuntimeError('Policy regression failed: '+name+' '+result.stdout)
            cases.append(dict(name=name,passed=True))
        (root/'innocent_name.xml').write_bytes(raw)
        seal()
        check('renamed_duplicate_in_valid_public_manifest_is_rejected',True,False,True)
        (root/'innocent_name.xml').unlink()
        (root/'licensed').mkdir()
        (root/'licensed/reference.prj').write_bytes(raw)
        seal()
        check('registered_restored_original_allowed_for_local_check',False,True)
        check('registered_restored_original_rejected_for_publication',True,False,True)
        (root/'licensed/reference.prj').unlink()
        seal()
        check('clean_public_snapshot_allowed',True,True)
    print(json.dumps(dict(status='PUBLICATION_POLICY_REGRESSIONS_PASSED',cases=cases,
        fixture_source='Self-authored synthetic bytes; no vendor originals',hardware_operated=False)))


if __name__=='__main__':main()
