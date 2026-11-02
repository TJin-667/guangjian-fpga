"""Single executable entry: unchanged controller -> real UDP executor -> metrics."""
import argparse
from pathlib import Path
import json
import sys
import numpy as np

from closed_loop import ClosedLoop
from dependencies import ROOT, load_dependencies, json_read
from software_peer import make_peer_class


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT/"XDL/XDL_Software_Controller/config.json")
    parser.add_argument("--software-peer", action="store_true")
    parser.add_argument("--board")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--mask", type=Path)
    parser.add_argument("--mask-sha256")
    parser.add_argument("--roi", type=int, nargs=4)
    parser.add_argument("--sample-id", default="software_peer_sample")
    parser.add_argument("--pose", default="fixed_pose")
    parser.add_argument("--settle-frames", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=3)
    args = parser.parse_args(argv)
    from dependencies import digest
    try:
        d = load_dependencies(args.dependencies, include_peer=args.software_peer)
        config = d.xdl.acquisition_control.ControllerConfig.from_dict(json_read(args.config))
        if args.software_peer:
            if args.board or args.mask or args.roi:
                raise ValueError("Software peer owns its synthetic endpoint, mask and ROI")
            peer = make_peer_class(d)()
            roi = (11,17,128,128)
            mask = np.ones((128,128), bool)
            mask[[0,-1],:] = False
            mask[:,[0,-1]] = False
            source, board, port, size = "software_udp_peer", *peer.endpoint, (160,160)
        else:
            peer = None
            if not all((args.board, args.mask, args.mask_sha256, args.roi)):
                raise ValueError("Real-board mode requires endpoint, ROI and SHA-bound native mask")
            if args.bind == "127.0.0.1" or digest(args.mask) != args.mask_sha256:
                raise ValueError("Real-board bind/mask SHA must be explicitly confirmed")
            roi = tuple(args.roi)
            raw = args.mask.read_bytes()
            if len(raw) != roi[2]*roi[3] or any(x not in (0,1) for x in raw):
                raise ValueError("Native mask shape/0-1 coding")
            mask = np.frombuffer(raw,np.uint8).astype(bool).reshape(roi[3],roi[2])
            source, board, port, size = "real_board", args.board, args.port, (1920,1080)
        output = args.out.resolve()
        output.mkdir(parents=True,exist_ok=False)
        try:
            with d.sdk.acquisition_executor.AcquisitionExecutor(
                    board=board,port=port,bind=args.bind,ymw_root=d.root/"ymw",
                    output_root=output/"captures",mode="strict", evidence_source=source,
                    sensor_size=size,command_timeout=.15 if peer else 1.5) as executor:
                result = ClosedLoop(dependencies=d,executor=executor,config=config,
                    output=output/"loop",roi=roi,mask_provider=lambda i,e:mask,
                    sample_id=args.sample_id,pose=args.pose,settle_frames=args.settle_frames,
                    timeout_s=args.timeout_s).run()
        finally:
            if peer:
                peer.__exit__(None,None,None)
        from audit_closed_loop import audit
        audit(output/"loop",d)
        print(json.dumps(dict(controller_status=result["controller_status"], attempts=result["attempts"],
            observations=result["accepted_observations"], evidence_source=source,
            physical_freshness_verified=False, output=str(output)), ensure_ascii=False))
        if result["fatal_error"]:
            return 2
        return {"LOCKED":0,"NEEDS_REVIEW":3,"CAPTURE_FAILED":4}.get(result["controller_status"],2)
    except (OSError,ValueError,RuntimeError,KeyError) as exc:
        print(json.dumps({"status":"FAILED","reason":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
