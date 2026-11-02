"""Strict loopback acquisition -> combined handoff -> real child worker -> GUI."""
import argparse
import copy
import contextlib
from pathlib import Path
import shutil
import socket
import sys
import threading
import time
from unittest.mock import patch
import bootstrap as b
import numpy as np


def run(out):
    b.verify();out.mkdir(parents=True,exist_ok=False)
    benchmark=b.HERE.parent/'system_benchmark_0109_20261031';sys.path.insert(0,str(benchmark))
    from core import Tools
    from test_benchmark import peer_class
    from session_batch import Plan,SessionBatch
    from speed_pipeline import run as pipeline
    import combined_evidence as combined
    tools=Tools(False);Peer,engine=peer_class();rows=[];checks=[]
    real_socket=socket.socket
    class LoopbackSocket(real_socket):
        def bind(self,address):
            if address[0]!='127.0.0.1':raise AssertionError('Non-loopback bind prohibited')
            return super().bind(address)
        def sendto(self,data,*args):
            if args[-1][0]!='127.0.0.1':raise AssertionError('Non-loopback send prohibited')
            return super().sendto(data,*args)
    cache_base=out/'combined_cache';last_source=None
    with patch.object(socket,'socket',LoopbackSocket):
        with Peer(engine.root/'ymw',sensor_size=(96,32)) as peer:
            batch=SessionBatch(tools.impl,base=out,board='127.0.0.1',port=peer.endpoint[1],bind='127.0.0.1',ymw_root=engine.root/'ymw',physical=False,
                               sensor_size=(96,32),extra_source_hashes=b.candidate_sources())
            try:
                for index,(fmt,low,high) in enumerate(((49,400,800),(49,300,700),(50,400,800),(50,400,800)),1):
                    group=time.time_ns();plan=Plan(group,group.to_bytes(16,'big'),(3,5,19,13),bytes([1])*247,'SW_SPEED_NOT_TRAINING','A_v1',fmt,low,high)
                    target,receipt=batch.capture(plan)
                    cache=combined.seal_live(batch.client,qualification=None,base=cache_base)
                    (target/'EVIDENCE_CACHE.json').write_text('{}','utf-8');batch.finalize_metadata(target)
                    x,mode=combined.load(target/'fusion',base=cache_base,allow_fixture=True)
                    assert mode=='COMBINED_VERIFIED_HASH_REUSE' and x['residual_n'].shape==(8,13,19)
                    result,status=pipeline(target/'fusion','0109',out/'analysis',allow_fixture=True,cache_base=cache_base)
                    assert status['status']=='COMPLETE',status
                    final=b.read(result/'RESULT.json')
                    assert final['validation_scope']==mode and final['host_residual_access']=='reused_engineering_H2_quality'
                    proof=tools.prove(x['gray'],x['sat1'],x['board'],x['words'],final['final_root'])
                    assert not any(proof['formal_differences'].values())
                    assert receipt['mask_commands']==0 if index in (2,4) else receipt['mask_commands']>0
                    rows.append(dict(format=fmt,low=low,high=high,session=receipt['session'],mask_commands=receipt['mask_commands'],group=group,
                                     cache=str(cache),analysis=str(result),formal_arrays_full_review_scores_equal=True))
                    last_source=target/'fusion'
                assert len(peer.captured)==36 and not peer.off_live
                cancel=threading.Event();cancel.set()
                before=len(peer.captured)
                _,status=pipeline(last_source,'0109',out/'cancelled',cancel=cancel,allow_fixture=True,cache_base=cache_base)
                assert status['status']=='CANCELLED' and len(peer.captured)==before
                checks.append('prelaunch_cancel_no_CAP')
            finally:batch.close()
    # No network is permitted in archive replay, corruption checks or the UI.
    def denied(*a,**k):raise AssertionError('Unexpected hardware/network access')
    with patch.object(socket,'socket',denied):
        source=Path(rows[0]['analysis']);raw_root=Path(b.read(source/'RESULT.json')['input_source'])
        x,label=combined.load(raw_root,mode='audit',base=cache_base,allow_fixture=True)
        assert label=='FULL_STRICT_AUDIT' and 'residual_n' not in x
        checks.append('explicit_full_audit_preserved')
        x,label=combined.load(raw_root,base=out/'missing_cache',allow_fixture=True)
        assert label.startswith('LEGACY_NATIVE_REUSE_NO_DERIVATIVES')
        checks.append('missing_combined_cache_uses_strict_legacy')
        corrupted=out/'corrupted_cache';dest=combined.cache_path(raw_root,corrupted);dest.parent.mkdir();shutil.copytree(rows[0]['cache'],dest)
        p=dest/'native.npz';raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        try:combined.load(raw_root,base=corrupted,allow_fixture=True)
        except ValueError:checks.append('corrupt_combined_cache_refused_no_silent_fallback')
        else:raise AssertionError('Corrupted cache accepted')
        # Construct the actual derived Tk window and load a child-worker result.
        import tkinter as tk
        from speed_app import ContinuousApp
        root=tk.Tk();root.withdraw();app=ContinuousApp(root,preflight=False,result_root=out/'ui_capture')
        root.update();assert 'v1.8' in root.title()
        assert type(app.continuous).__module__=='speed_capture'
        app.load_final(rows[-1]['analysis']);root.update()
        assert app.final_result['parameter_freeze_id']=='f09eb5885e1d' and app.final_images.size()>=10
        app.final_view.set_zoom(2);root.update();app.final_view.fit();root.update()
        app.destroy_ui()
        checks.append('real_hidden_Tk_new_controller_worker_gallery_zoom_and_close')
    b.verify()
    b.write(out/'SELFTEST.json',dict(status='PASS',groups=rows,checks=checks,software_loopback_CAP=36,actual_board_commands=0,
              physical_hardware=False,formats=[49,50],warm_groups_mask_zero=True,child_process_frozen_proof=True,candidate_binding_sha256=b.sha(b.HERE/'CANDIDATE_BINDING.json')))
    print('PASS 4 groups / 36 loopback captures; both formats, exposure change, child worker and Tk',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);run(p.parse_args().out)
