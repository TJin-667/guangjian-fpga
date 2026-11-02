"""Real UDP software-peer integration and fail-closed evidence controls."""
import argparse
import copy
import csv
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import ctypes
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
from audit_closed_loop import audit
from closed_loop import ClosedLoop, save_json
from dependencies import ROOT, digest, json_read, load_dependencies, verify_dependencies
from software_peer import gray_word, make_peer_class

HERE = Path(__file__).resolve().parent


def uniform(level):
    return lambda e,n,w,h:np.full((h,w),gray_word(level),np.uint16)


def highlight(e,n,w,h):
    a=np.full((h,w),gray_word(100),np.uint16)
    if e==600:
        a[:, :w//5]=np.uint16((31<<11)|31)  # Pink highlight without near-white gray.
    return a


def mask_provider(kind):
    def provider(index,exposure):
        mask=np.ones((128,128),bool)
        mask[[0,-1],:]=False;mask[:,[0,-1]]=False
        if kind=="expanded" and index>1:
            mask[:]=True
        elif kind=="shrunk" and index>1:
            mask[60,:]=False
        elif kind=="small":
            mask[:]=False;mask[16:112,16:112]=True
        elif kind=="empty":
            mask[:]=False
        return mask
    return provider


class ResultProxy:
    """Deliver old/tampered return values while retaining new real SDK calls."""
    def __init__(self,executor,mode):
        self.executor,self.proxy_mode,self.first=executor,mode,None
    def __getattr__(self,name):
        return getattr(self.executor,name)
    def acquire(self,**kw):
        result=self.executor.acquire(**kw)
        if self.first is None:
            self.first=result
            return result
        if self.proxy_mode=="cached":
            return self.first
        data=copy.deepcopy(result.metadata)
        if self.proxy_mode=="parameters":
            data["actual_parameters"]["exposure_lines"]=500
        elif self.proxy_mode=="identity":
            data["identity"]=copy.deepcopy(self.first.metadata["identity"])
        elif self.proxy_mode=="partial":
            data["identity"].pop("publish_sequence")
        elif self.proxy_mode=="image":
            return replace(result,png_path=self.first.png_path)
        return replace(result,metadata=data)


def suite():
    cases=[
        dict(name="stable_normal_identical_pixels",status="LOCKED",exposures=[600,600]),
        dict(name="pink_highlight_decreases_exposure",image=highlight,status="LOCKED",exposures=[600,500,500]),
        dict(name="dark_increases_exposure",image=lambda e,n,w,h:uniform(0 if e==600 else 100)(e,n,w,h),
             status="LOCKED",exposures=[600,700,700]),
        dict(name="all_dark_search_stops",image=uniform(0),status="CAPTURE_FAILED",exposures=[600,700]),
        dict(name="unstable_confirmation_fresh_fallback",
             image=lambda e,n,w,h:uniform(150 if n==2 else 100)(e,n,w,h),
             status="LOCKED",exposures=[600,600,600,600]),
        dict(name="first_failure_retry_then_two_new_confirmations",
             faults={1:"missing_packet"},status="LOCKED",exposures=[600,600,600]),
        dict(name="confirmation_failure_resets_confirmation",
             faults={2:"missing_packet"},status="LOCKED",exposures=[600,600,600,600]),
        dict(name="missing_packets_retry_exhaustion",faults={1:"missing_packet",2:"missing_packet"},
             status="CAPTURE_FAILED",observations=0),
        dict(name="old_image_crc_rejected",faults={1:"old_image",2:"old_image"},
             status="CAPTURE_FAILED",observations=0),
        dict(name="wrong_parameter_sidecar_rejected",faults={1:"bad_parameters",2:"bad_parameters"},
             terminal=True,observations=0),
        dict(name="wrong_session_requires_recovery",faults={1:"wrong_session"},
             terminal=True,observations=0),
        dict(name="wrong_request_requires_recovery",faults={1:"wrong_request"},
             terminal=True,observations=0),
        dict(name="reset_old_response_rejected",faults={1:"reset"},
             terminal=True,observations=0),
        dict(name="drop_ack_retry_is_not_new_capture",faults={1:"drop_ack_once"},
             status="LOCKED",exposures=[600,600]),
        dict(name="late_execution_reply",faults={1:"slow_execution"},
             command_timeout=.1,status="LOCKED",exposures=[600,600]),
        dict(name="out_of_order_complete_image",faults={1:"out_of_order"},status="LOCKED"),
        dict(name="duplicate_packet_one_observation",faults={1:"duplicate"},status="LOCKED"),
        dict(name="stale_frame_packets_excluded",faults={1:"stale_image"},status="LOCKED"),
        dict(name="frame_id_wrap_full_identity",first_fid=65534,status="LOCKED"),
        dict(name="native_expansion_frozen_common",mask="expanded",status="LOCKED"),
        dict(name="native_shrink_geometry_review",mask="shrunk",status="NEEDS_REVIEW"),
        dict(name="insufficient_first_common_area",mask="small",status="NEEDS_REVIEW"),
        dict(name="empty_first_common_area",mask="empty",status="NEEDS_REVIEW"),
        dict(name="cached_return_is_not_confirmation",proxy="cached",status="CAPTURE_FAILED",observations=1),
        dict(name="returned_actual_parameters_changed",proxy="parameters",status="CAPTURE_FAILED",observations=1),
        dict(name="returned_full_identity_changed",proxy="identity",status="CAPTURE_FAILED",observations=1),
        dict(name="returned_partial_identity_rejected",proxy="partial",status="CAPTURE_FAILED",observations=1),
        dict(name="returned_old_png_rejected",proxy="image",image=lambda e,n,w,h:uniform(100+n)(e,n,w,h),
             status="CAPTURE_FAILED",observations=1),
        dict(name="cancel_late_image_no_confirmation",faults={1:"cancel_late_image"},cancel=True,
             terminal=True,observations=0),
        dict(name="actual_wait_drop_frame_budget",config={"max_frames":8},status="NEEDS_REVIEW",
             exposures=[600],reason="transport_frame_reservation_budget"),
        dict(name="zero_requests_when_wait_reservation_too_large",wait=40,status="NEEDS_REVIEW",
             exposures=[],reason="transport_frame_reservation_budget"),
        dict(name="windows_share_lock_publish_retry_same_capture",publish_lock="temporary",
             status="LOCKED",exposures=[600,600]),
        dict(name="windows_permanent_publish_failure_cost_retained",publish_lock="permanent",
             status="CAPTURE_FAILED",exposures=[600,600],observations=0),
        dict(name="cancel_during_publication_no_success",publish_lock="cancel",publish_cancel=True,
             status="NEEDS_REVIEW",observations=0),
    ]
    return cases


@contextmanager
def publication_lock(d,kind,cancel):
    """Actual Windows handle denies directory rename; no fake success syscall."""
    if not kind:
        yield
        return
    from ctypes import wintypes
    import publication
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                                ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    original=d.sdk.acquisition_executor.publish_directory
    def locked(source,destination,*,check,event):
        handle=kernel.CreateFileW(str(Path(source)/"image.rgb565"),
                                  0x80000000,3,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        guard=threading.Lock()
        closed=False
        def release():
            nonlocal closed
            with guard:
                if not closed:
                    kernel.CloseHandle(handle)
                    closed=True
        timer=None
        if kind=="temporary":
            timer=threading.Timer(.07,release);timer.start()
        elif kind=="cancel":
            timer=threading.Timer(.02,cancel.set);timer.start()
        try:
            return publication.atomic_publish(source,destination,check=check,event=event)
        finally:
            if timer:
                timer.cancel()
                timer.join()
            release()
    d.sdk.acquisition_executor.publish_directory=SimpleNamespace(atomic_publish=locked)
    try:
        yield
    finally:
        d.sdk.acquisition_executor.publish_directory=original


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dependencies",type=Path,required=True)
    p.add_argument("--work",type=Path,required=True)
    args=p.parse_args(argv)
    args.work=args.work.resolve();args.work.mkdir(parents=True,exist_ok=False)
    d=load_dependencies(args.dependencies,include_peer=True)
    source_hashes={str(f):digest(f) for f in sorted(HERE.glob("*.py"))}
    source_hashes.update(d.controller_hashes)
    receipts=[]
    tests=suite()
    names=[c["name"] for c in tests]
    if len(names)!=len(set(names)):
        raise ValueError("duplicate planned cases")
    Peer=make_peer_class(d)

    def record(name,passed,**details):
        row=dict(case_index=len(receipts)+1,case_name=name,status="PASS" if passed else "FAIL",**details)
        receipts.append(row)
        save_json(args.work/"cases.json",receipts)
        print(json.dumps(row,ensure_ascii=False),flush=True)

    for case in tests:
        case_root=args.work/"cases"/case["name"]
        case_root.mkdir(parents=True)
        cancel=threading.Event() if case.get("cancel") or case.get("publish_cancel") else None
        cancel_thread=None
        try:
            with Peer(image_plan=case.get("image"),fault_plan=case.get("faults"),
                      first_fid=case.get("first_fid",10)) as peer:
                if case.get("cancel"):
                    def trigger():
                        peer.capture_event.wait(3)
                        time.sleep(.015)
                        cancel.set()
                    cancel_thread=threading.Thread(target=trigger,daemon=True)
                    cancel_thread.start()
                with d.sdk.acquisition_executor.AcquisitionExecutor(
                        board=peer.endpoint[0],port=peer.endpoint[1],bind="127.0.0.1",
                        ymw_root=d.root/"ymw",output_root=case_root/"captures",mode="strict",
                        evidence_source="software_udp_peer",sensor_size=(160,160),
                        command_timeout=case.get("command_timeout",.05),retries=3,
                        initial_seq=65520 if case["name"]=="frame_id_wrap_full_identity" else None) as ex:
                    executor=ResultProxy(ex,case["proxy"]) if case.get("proxy") else ex
                    values=json_read(ROOT/"XDL/XDL_Software_Controller/config.json")
                    values.update(case.get("config",{}))
                    config=d.xdl.acquisition_control.ControllerConfig.from_dict(values)
                    with publication_lock(d,case.get("publish_lock"),cancel):
                        result=ClosedLoop(dependencies=d,executor=executor,config=config,
                            output=case_root/"loop",roi=(11,17,128,128),
                            mask_provider=mask_provider(case.get("mask")),
                            sample_id=case["name"],pose="synthetic_fixed_pose",
                            context_id=case["name"],settle_frames=case.get("wait",1),
                            timeout_s=.8,cancel=cancel).run()
                if cancel_thread:
                    cancel_thread.join(3)
                audit_result=audit(case_root/"loop",d)
                ledger=json_read(case_root/"loop/cost_ledger.json")
                exposures=[r["requested_exposure_lines"] for r in ledger]
                status=result["controller_status"]
                expected=(status==case["status"] if "status" in case else status in ("CAPTURE_FAILED","NEEDS_REVIEW"))
                if "exposures" in case:
                    expected &= exposures==case["exposures"]
                if "observations" in case:
                    expected &= result["accepted_observations"]==case["observations"]
                if "reason" in case:
                    expected &= result["execution_stop_reason"]==case["reason"]
                observations=json_read(case_root/"loop/observations.json")
                if case["name"]=="stable_normal_identical_pixels":
                    expected &= len(observations)==2 and observations[0]["geometry"]["rgb565_sha256"]==observations[1]["geometry"]["rgb565_sha256"]
                    expected &= observations[0]["complete_identity"]!=observations[1]["complete_identity"]
                    expected &= all(o["common_statistics"]["baseline_candidate_count"]==0 for o in observations)
                if case["name"]=="pink_highlight_decreases_exposure":
                    expected &= observations[0]["common_statistics"]["near_white_count"]==0
                    expected &= observations[0]["common_statistics"]["rgb_max_count"]>0
                if case["name"]=="native_expansion_frozen_common":
                    expected &= observations[1]["native_device_statistics"]["board_count"]>observations[1]["common_statistics"]["n"]
                if case["name"]=="frame_id_wrap_full_identity":
                    expected &= [o["complete_identity"]["frame_id"] for o in observations]==[65535,0]
                if case["name"] in ("drop_ack_retry_is_not_new_capture","late_execution_reply"):
                    expected &= any(r["transport_cost"]["command_retries"]>0 for r in ledger)
                if case.get("publish_lock"):
                    expected &= result["transport_cost"]["publication_retries"]>0
                    expected &= result["transport_cost"]["frame_cost_complete"]
                    expected &= result["transport_cost"]["known_frames"]==len(ledger)*5
                    expected &= len(peer.captured)==len(ledger)
                if "failure" in case["name"] or case.get("faults",{}).get(1)=="missing_packet":
                    expected &= result["transport_cost"]["retry_acquisitions"]>=1
                save_json(case_root/"peer_receipt.json",dict(captured=peer.captured,
                    command_count=peer.commands,camera_executions=peer.camera_executions,errors=peer.errors,
                    software_only=True))
                record(case["name"],bool(expected),controller_status=status,
                       exposures=exposures,observations=result["accepted_observations"],
                       audit=audit_result,receipt_sha256=digest(case_root/"loop/receipt.json"))
        except Exception as exc:
            record(case["name"],False,reason=repr(exc))

    # Run the delivered CLI and audit CLI as real subprocesses.
    cli=args.work/"cli_entry"
    command=[sys.executable,"-B",str(HERE/"run_closed_loop.py"),"--dependencies",str(args.dependencies),
             "--software-peer","--out",str(cli)]
    r=subprocess.run(command,capture_output=True,text=True)
    (args.work/"cli_stdout.txt").write_text(r.stdout+r.stderr,encoding="utf-8")
    record("actual_cli_entry_and_audit",r.returncode==0 and json_read(cli/"loop/summary.json")["controller_status"]=="LOCKED",
           command=command,returncode=r.returncode)
    overwrite=subprocess.run(command,capture_output=True,text=True)
    record("cli_refuses_existing_output",overwrite.returncode==2,returncode=overwrite.returncode)
    audit_cmd=[sys.executable,"-B",str(HERE/"audit_closed_loop.py"),"--dependencies",str(args.dependencies),
               "--out",str(cli/"loop")]
    r=subprocess.run(audit_cmd,capture_output=True,text=True)
    record("actual_audit_cli_positive",r.returncode==0,returncode=r.returncode)

    # Controls mutate only this task's disposable synthetic test result, then
    # restore the exact bytes in finally. Primary/source files are untouched.
    root=cli/"loop"
    controls=[
        ("truncated_trace","frame_trace.jsonl",lambda b:b.splitlines()[0]+b"\n",False),
        ("ledger_cost_omitted","cost_ledger.json",lambda b:json.dumps([{**r,"frame_reservation":1} for r in json.loads(b)]).encode(),True),
        ("wrong_common_identity","observations.json",lambda b:json.dumps([{**r,"complete_identity":{**r["complete_identity"],"request_id":0}} for r in json.loads(b)]).encode(),True),
        ("duplicate_observation","observations.json",lambda b:json.dumps([json.loads(b)[0]]*2).encode(),True),
        ("native_replaced_by_common","observations.json",lambda b:json.dumps([{**r,"native_device_statistics":r["common_statistics"]} for r in json.loads(b)]).encode(),True),
        ("controller_rule_result_tampered","transitions.json",lambda b:json.dumps([{**r,"decision":{**r["decision"],"next_exposure_lines":700}} for r in json.loads(b)]).encode(),True),
        ("common_mask_pixel_changed","common_mask.bin",lambda b:bytes([b[0]^1])+b[1:],True),
        ("fake_hardware_verified","summary.json",lambda b:json.dumps({**json.loads(b),"physical_freshness_verified":True}).encode(),True),
    ]
    for name,target,mutate,rehash in controls:
        path=root/target
        original,original_receipt=path.read_bytes(),(root/"receipt.json").read_bytes()
        try:
            path.write_bytes(mutate(original))
            if rehash:
                receipt=json_read(root/"receipt.json")
                receipt["result_sha256"][target]=digest(path)
                if target=="summary.json":
                    receipt.update(json_read(path))
                save_json(root/"receipt.json",receipt)
            r=subprocess.run(audit_cmd,capture_output=True,text=True)
            (args.work/(name+"_audit.txt")).write_text(r.stdout+r.stderr,encoding="utf-8")
            record("audit_reject_"+name,r.returncode==2,returncode=r.returncode)
        finally:
            path.write_bytes(original)
            (root/"receipt.json").write_bytes(original_receipt)
    restored=audit(root,d)
    record("audit_control_bytes_restored",restored["status"]=="PASS")
    verify_dependencies(d.root)
    source_ok=all(digest(path)==value for path,value in source_hashes.items())
    record("controller_sdk_algorithm_sources_unchanged",source_ok)
    with (args.work/"cases.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=["case_index","case_name","status","details"])
        writer.writeheader()
        for row in receipts:
            writer.writerow({**{k:row[k] for k in ("case_index","case_name","status")},
                             "details":json.dumps({k:v for k,v in row.items() if k not in ("case_index","case_name","status")},ensure_ascii=False)})
    extra_names=["actual_cli_entry_and_audit","cli_refuses_existing_output","actual_audit_cli_positive"]
    extra_names += ["audit_reject_"+row[0] for row in controls]
    extra_names += ["audit_control_bytes_restored","controller_sdk_algorithm_sources_unchanged"]
    complete=[r["case_name"] for r in receipts]==names+extra_names
    result=dict(status="PASS" if complete and all(r["status"]=="PASS" for r in receipts) else "FAIL",
        software_udp_peer=True,board_verified=False,physical_freshness_verified=False,
        complete_case_inventory=complete,planned_udp_cases=len(tests),cases=len(receipts),
        source_sha256=source_hashes,dependencies_manifest_sha256=digest(args.dependencies/"dependencies.json"),
        receipt_sha256=digest(args.work/"cases.csv"),
        failed_cases=[r["case_name"] for r in receipts if r["status"]!="PASS"])
    save_json(args.work/"verification.json",result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result["status"]=="PASS" else 2


if __name__=="__main__":
    raise SystemExit(main())
