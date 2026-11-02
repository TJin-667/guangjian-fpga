"""Hardware-free import/UI probe, intended for the packaged release tests."""
from pathlib import Path
import argparse,ctypes,json,os,sys
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--gui',action='store_true');args=parser.parse_args()
    allowed=[ROOT,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve()]
    opens=set();denied=[]
    def audit(event,values):
        if event.startswith('socket.') or event=='subprocess.Popen':
            denied.append(event);raise RuntimeError('No device/network/process operations in offline probe: '+event)
        if event in ('open','os.listdir','os.scandir') and values:
            value=values[0]
            if isinstance(value,(str,bytes,os.PathLike)):
                p=Path(os.fsdecode(value)).resolve()
                if not any(p.is_relative_to(root) for root in allowed):
                    denied.append(str(p));raise RuntimeError('External file access blocked: '+str(p))
                opens.add(str(p))
    sys.addaudithook(audit)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT/'scripts'))
    from export_guard import verify
    verify()
    from export_paths import repo_path,qualification_path,lab_root,network,data_root
    allowed.append(data_root())
    sys.path.insert(0,str(repo_path('YMW/work/host_speed_step3_0109_20261031')))
    import bootstrap
    import speed_app
    speed_app.verify_candidate()
    from sdk_loader import load_sdk
    sdk=load_sdk(qualification=qualification_path())
    assert sdk.ALLOW_REAL_0109 is True
    import focus0109
    bridge=focus0109.load_bridge(sdk=sdk)
    assert bridge.NativeCRC()(b'123456789')==0x6c40df5f0b497347
    import threading
    runtime=focus0109.Runtime('sample004','A_v1','offline_probe',threading.Event(),lambda *a,**k:None)
    plan,context,sources=runtime.focus_plan()
    assert plan['source_contract']==dict(board=network('board'),bind=network('bind'),port=network('port'))
    assert context.roi==[0,0,1920,1080]
    import engineering0109
    core=sdk.wire.pinned_module('_export_probe_engine',engineering0109.HOST.parents[1]/'auto_exposure_0105_20261015/app_core.py','448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857')
    engine=core.load_engine()
    assert engine.root.is_relative_to(ROOT)
    with core.operator_lock(lab_root()):pass
    import uuid
    from export_paths import data_path
    scratch=data_path('offline_probe_'+uuid.uuid4().hex[:8]);scratch.mkdir(parents=True)
    mask=scratch/'mask.bin';mask.write_bytes(bytes([1])*81)
    prepared=engineering0109.prepare_native([0,0,9,9],mask,'sample004','A_v1',scratch/'plan',pixel_format=49)
    approved=json.loads(prepared.read_bytes())
    assert approved['board']==network('board') and approved['bind']==network('bind') and approved['port']==network('port')
    assert (approved['low_lines'],approved['high_lines'])==(400,800)
    assert approved['roi']==[0,0,9,9] and approved['lab_root']==str(lab_root())
    gui=False
    if args.gui:
        # Withdraw before constructing widgets: no visible operator window and
        # no acquisition preflight, worker, socket or camera command is started.
        import tkinter as tk
        root=tk.Tk();root.withdraw()
        application=speed_app.ContinuousApp(root,preflight=False)
        root.update_idletasks();root.update()
        assert application.continuous.batch is None
        assert int(application.low_lines.get())==400 and int(application.high_lines.get())==800
        application.destroy_ui();gui=True
    assert not denied
    print(json.dumps(dict(status='PORTABLE_HOST_OFFLINE_PROBE_PASSED',GUI_widgets_created=gui,
          SDK_loaded=True,focus_bridge_loaded=True,native_CRC_self_test_passed=True,engine_loaded=True,
          qualification_passed=True,operator_lock_passed=True,offline_ROI_plan_passed=True,network_or_hardware_operations=0,external_project_reads=0,
          audit_scope='Python file open/list/scandir, socket and subprocess events; native DLL internal file reads are not traced',
          Python_file_paths_accessed=len(opens)),ensure_ascii=False))
if __name__=='__main__':main()
