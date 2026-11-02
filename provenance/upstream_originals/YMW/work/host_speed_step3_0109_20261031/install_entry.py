"""Back up current mode and install only a new, separately named launcher."""
import argparse
from pathlib import Path
import shutil
import time
import uuid
import zipfile
import bootstrap as b


def install(out, desktop):
    b.verify()
    from qualification import validate
    qualification=Path('E:/GuangjianData/final_board_0109_20261030/engineering_bit_01/QUALIFICATION.json')
    q,_=validate(qualification)
    preserved={}
    for folder in (Path('E:/GuangjianData/software/FinalSystem0109_20261030'),Path('E:/GuangjianData/software/FinalSystem_20261029')):
        if folder.exists():
            preserved.update({str(p):b.sha(p) for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    for name in ('光鉴0109独立候选入口.cmd','光鉴0108新入口.cmd'):
        p=desktop/name
        if p.is_file():preserved[str(p)]=b.sha(p)
    out=out.resolve()
    b.need(out.is_relative_to(Path('E:/GuangjianData/software').resolve()),'Separate software directory on E required')
    b.need(shutil.disk_usage('E:/').free>200*1024**2,'Insufficient backup space')
    backup=Path('E:/GuangjianData/software/backups')/('Before_speed0109_combined_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);backup.mkdir(parents=True)
    members={}; archive=backup/'current_mode.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for i,(name,digest) in enumerate(preserved.items()):
            member='installed/'+str(i)+'_'+Path(name).name;z.write(name,member);members[member]=dict(original=name,sha256=digest)
        for name,digest in b.read(b.ORIGINAL/'SOURCE_BINDING.json')['files_sha256'].items():
            member='qualified_source/'+name;z.write(b.ORIGINAL/name,member);members[member]=dict(original=str(b.ORIGINAL/name),sha256=digest)
        member='current_bit/bx72_0109.bit';z.write(q['bit_path'],member);members[member]=dict(original=q['bit_path'],sha256=q['bit_sha256'])
    import hashlib
    with zipfile.ZipFile(archive) as z:
        b.need(set(z.namelist())==set(members),'Backup member mismatch')
        b.need(all(hashlib.sha256(z.read(name)).hexdigest()==r['sha256'] for name,r in members.items()),'Backup verification failed')
    b.write(backup/'BACKUP_MANIFEST.json',dict(files=members,archive_sha256=b.sha(archive)))
    out.mkdir(parents=True,exist_ok=True)
    def exact(path, data):
        if path.exists():b.need(path.read_bytes()==data,'Different existing launcher retained: '+str(path))
        else:path.write_bytes(data)
    entry=out/'RUN_SPEED_0109.cmd'
    exact(entry,('@echo off\r\ncall "'+str(b.HERE/'RUN_SPEED_0109.cmd')+'" %*\r\n').encode('utf-8'))
    desktop_entry=desktop/'光鉴0109提速候选入口.cmd'
    exact(desktop_entry,('@echo off\r\ncall "'+str(entry)+'" %*\r\n').encode('utf-8'))
    b.need(all(b.sha(p)==digest for p,digest in preserved.items()),'Previous installation changed')
    result=dict(status='SEPARATE_SPEED_HOST_INSTALLED_PENDING_PHYSICAL_ACCEPTANCE',entry=str(entry),desktop_entry=str(desktop_entry),
                backup=str(backup),backup_members=len(members),backup_verified=True,old_files_sha256=preserved,old_files_unchanged=True,
                candidate_binding_sha256=b.sha(b.HERE/'CANDIDATE_BINDING.json'),bit_sha256=q['bit_sha256'],new_bit=False,
                default_entry_changed=False,board_contacted=False)
    b.write(out/'INSTALLATION.json',result)
    print(result['status'],str(entry),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--desktop',type=Path,required=True)
    a=p.parse_args();install(a.out,a.desktop)
