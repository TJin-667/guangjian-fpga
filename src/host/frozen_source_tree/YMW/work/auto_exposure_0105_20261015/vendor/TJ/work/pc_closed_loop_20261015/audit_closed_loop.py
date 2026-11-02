"""Independent artifact, identity, cost and unchanged-XDL transition audit."""
import argparse
from pathlib import Path
import json
import sys
import numpy as np

from closed_loop import canonical, decode_rgb565, plain, IDENTITY_BOUNDS
from dependencies import digest, json_read, load_dependencies, verify_dependencies
from transaction_cost import proven_frames


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(output, dependencies):
    output = Path(output).resolve()
    receipt, summary = json_read(output/"receipt.json"), json_read(output/"summary.json")
    require(receipt.get("fatal_error") is None, "Adapter failed; no acceptance")
    require(all(summary[k] is False for k in (
        "board_verified", "physical_freshness_verified", "release_ready", "controller_rules_modified")),
        "Software evidence mislabelled hardware/rule verification")
    require(canonical({k:v for k,v in receipt.items() if k!="result_sha256"}) == canonical(summary),
            "Summary and receipt disagree")
    require(set(receipt["result_sha256"]) == {p.name for p in output.iterdir()
                                            if p.is_file() and p.name!="receipt.json"},
            "Incomplete/extra artifact inventory")
    for name, expected in receipt["result_sha256"].items():
        path = (output/name).resolve()
        require(path.is_relative_to(output) and digest(path)==expected, "Artifact SHA mismatch: "+name)
    verify_dependencies(dependencies.root)
    require(summary["dependencies"] == dependencies.manifest, "Dependency receipt mismatch")
    require(summary["sdk_publication_overlay"] == dependencies.sdk_publication_overlay and
            summary["effective_executor_sha256"] == dependencies.effective_executor_sha256 and
            summary["publication_source_sha256"] == dependencies.publication_source_sha256,
            "Publication overlay/effective source mismatch")
    require(summary["controller_source_sha256"] == dependencies.controller_hashes,
            "Controller sources differ from the executed snapshot")
    config = summary["controller_config"]
    require(config["rule_version"] == "controller-0.1", "Wrong rule version")
    ledger = json_read(output/"cost_ledger.json")
    observations = json_read(output/"observations.json")
    transitions = json_read(output/"transitions.json")
    require([r["attempt"] for r in ledger] == list(range(1,len(ledger)+1)), "Attempt inventory")
    require(len(ledger) == summary["attempts"], "Attempt count")
    sdk_root = Path(summary["sdk_output_root"]).resolve()
    accepted = {row["call_id"]:row for row in ledger if row["accepted_observation"]}
    require(len(accepted)==summary["accepted_observations"]==len(observations), "Observation inventory")
    require(len({o["call_id"] for o in observations})==len(observations), "Reused call observation")
    known, reserved, unknown = 0, 0, []
    for row in ledger:
        reserve = row["requested_wait_frames"]+row["requested_discard_frames"]+1
        require(row["frame_reservation"]==reserve, "Wait/drop omitted from reservation")
        reserved += reserve
        require(type(row["accepted_observation"]) is bool, "Malformed observation acceptance")
        require(isinstance(row["elapsed_ms"],(int,float)) and np.isfinite(row["elapsed_ms"]) and row["elapsed_ms"]>=0,
                "Missing measured host call duration")
        mask_path = Path(row["native_mask_path"]).resolve()
        require(mask_path.is_relative_to(output) and digest(mask_path)==row["native_mask_sha256"], "Native mask SHA")
        if row["call_id"]:
            path = Path(row["call_record"]).resolve()
            require(path == sdk_root/row["call_id"]/"outcome.json", "Call path escapes SDK output")
            require(digest(path)==row["call_record_sha256"], "Call record SHA")
            require(digest(path.parent/"frame_trace.jsonl")==row["sdk_trace_sha256"], "SDK trace SHA")
            call = json_read(path)
            require(call["call_id"]==row["call_id"] and call["status"]==row["executor_status"], "Call identity/status")
            require(call.get("cost")==row["transport_cost"], "Failure/retry transport cost lost")
            require(call.get("identity")==row["actual_identity"] and call.get("actual_parameters")==row["actual_parameters"],
                    "Cost linked to wrong frame/parameters")
            requested = call["requested"]
            require(requested["exposure_lines"]==row["requested_exposure_lines"] and
                    requested["settle_frames"]==row["requested_wait_frames"] and
                    requested["discard_frames"]==row["requested_discard_frames"], "Request/cost mismatch")
            require(call["mask_sha256"]==row["native_mask_sha256"], "Uploaded native mask mismatch")
            if row["accepted_observation"]:
                require(call["status"]=="COMMITTED" and call["strict_verified"] is True, "Failed/provisional image accepted")
            count = row["known_device_complete_frames"]
            proof = proven_frames(call,path.parent,dependencies)
            if row["frame_cost_complete"]:
                require(proof is not None and count==proof, "Unproven frame cost")
                require(count==call["device_reported_settle_frames"]+call["device_reported_discard_frames"]+1,
                        "Device wait/drop/capture omitted or double counted")
                require(count==reserve and row["frame_cost_lower_bound"]==count, "Reported/reserved frame mismatch")
            else:
                require(count is None and proof is None, "Unknown frame counts fabricated/hidden")
                require(row["frame_cost_lower_bound"]==call["cost"]["complete_images_received"], "Failed image lower bound")
                unknown.append(row["attempt"])
        else:
            require(not row["accepted_observation"] and row["transport_cost"] is None and
                    not row["frame_cost_complete"], "Unrecorded API call treated as successful/free")
            unknown.append(row["attempt"])
        known += row["frame_cost_lower_bound"]
    cost = summary["transport_cost"]
    require(cost["publication_retries"]==sum(r["publication_retries"] for r in ledger),
            "Publication retries omitted")
    require(cost["api_attempts"]==len(ledger) and cost["retry_acquisitions"]==sum(r["action"]=="retry_current" for r in ledger),
            "Retry acquisitions excluded")
    require(cost["reserved_frame_upper_bound"]==reserved and cost["known_frames"]==known, "Total frame ledger mismatch")
    require(cost["unknown_frame_cost_attempts"]==unknown and cost["frame_cost_complete"]==(not unknown), "Unknown costs hidden")
    require(cost["measured_host_elapsed_ms"]+1 >= sum(row["elapsed_ms"] for row in ledger), "Call waits omitted from time")
    require(cost["measured_physical_control_cost"] is None, "Peer timing claimed physical cost")
    identities, requests, publications = set(), set(), set()
    common = None
    if observations:
        shape = tuple(summary["common_sensor_shape"])
        common = np.frombuffer((output/"common_mask.bin").read_bytes(),np.bool_).reshape(shape)
        require(digest(output/"common_mask.bin")==summary["common_mask_sha256"], "Common mask changed")
        require(summary["future_frames_used_to_establish_area"]==0, "Future observations used for first common area")
    events = {t["event"].get("observation_id"):t["event"]
              for t in transitions if t["event"]["kind"]=="observation"}
    for index, observation in enumerate(observations):
        row = accepted[observation["call_id"]]
        tag = observation["complete_identity"]
        require(set(tag)==set(IDENTITY_BOUNDS), "Incomplete full identity")
        identity, request, publication = (canonical(tag), (tag["session"],tag["request_id"]),
            (tag["session"],tag["dvp_sequence"],tag["publish_sequence"]))
        require(identity not in identities and request not in requests and publication not in publications,
                "Confirmation reused frame/request/publication")
        identities.add(identity);requests.add(request);publications.add(publication)
        call = json_read(row["call_record"])
        require(tag==dict(call["identity"],bank=call["bank"]), "Image/statistics identity mismatch")
        require(observation["actual_parameters"]==call["actual_parameters"], "Actual parameters mismatch")
        record = Path(observation["image_record"])
        require(record==sdk_root/row["call_id"]/"committed/result.json" and
                digest(record)==observation["image_record_sha256"], "Accepted image record mismatch")
        require(json_read(record)==call, "Outcome/result mismatch")
        raw = (record.parent/"image.rgb565").read_bytes()
        require(digest(record.parent/"image.rgb565")==call["raw_rgb565_sha256"] and
                digest(record.parent/"image.png")==call["png_sha256"], "Image SHA")
        native = np.frombuffer(Path(row["native_mask_path"]).read_bytes(),np.bool_).reshape(summary["roi"][3],summary["roi"][2])
        roi = summary["roi"]
        if index==0:
            first = np.zeros(common.shape,bool)
            first[roi[1]:roi[1]+roi[3],roi[0]:roi[0]+roi[2]]=native
            require(np.array_equal(common,first), "Common area was not established from only the first frame")
        meta = call["diagnostic"]
        dependencies.sdk.identity_diag.require_association(meta,tag["session"],tag["request_id"],tag["frame_id"],
                                                            raw,expected_context=call["identity"])
        require(meta["parameters"]==observation["actual_parameters"], "Sidecar params")
        require(observation["native_device_statistics"]==call["statistics"] and
                observation["native_device_features"]==call["features"], "Native statistics replaced by common statistics")
        event = events[observation["observation_id"]]
        metric = event["metrics"]
        require(metric["geometry"]==observation["geometry"] and
                metric["native_reference_statistics"]==observation["native_reference_statistics"], "Metric geometry/native mapping")
        require(metric["geometry"]["source_metadata"]["complete_identity"]==tag and
                metric["geometry"]["source_metadata"]["frame_id"]==canonical(tag), "XDL source identity uses partial frame ID")
        image = decode_rgb565(raw,*roi[2:])
        gray = dependencies.algorithm["integer_gray"](image)
        h2 = dependencies.algorithm["integer_h2"](gray)
        local = common[roi[1]:roi[1]+roi[3],roi[0]:roi[0]+roi[2]]
        require(not np.any(local & ~native), "Frozen common area escaped native mask")
        scalar = dependencies.xdl.fpga_reference.scalar_metric_reference(
            gray,h2["residual_n"],np.any(image==255,axis=2),local)
        for key, value in scalar.items():
            if key in metric:
                require(metric[key]==value, "Independent common scalar mismatch: "+key)
        native_h1, native_h2 = dependencies.sdk.acquisition_support.image_metrics(
            raw,*roi[2:],native.tobytes())
        require(list(call["statistics"].values())==native_h1 and call["features"]==native_h2, "Native image statistics mismatch")
        require(metric["n"]==int(common.sum()) and metric["geometry"]["common_mask_sha256"]==summary["common_mask_sha256"],
                "Common denominator changed")
        reconstructed = dependencies.xdl.capture_metrics.FrameMetrics(**metric)
        require(plain(reconstructed.controller_statistics)==observation["common_statistics"], "Common statistics record")
    previous = None
    for transition in transitions:
        if previous is not None:
            require(transition["state_before"]==previous, "State chain broken")
        state, decision = dependencies.xdl.fpga_reference.reference_transition(
            transition["state_before"],transition["event"],config)
        require(state==transition["state_after"] and decision==transition["decision"], "Independent XDL rule mismatch")
        previous = state
        budget = decision["budget"]
        for axis in ("attempts","frames","time_ms"):
            require(budget["requested_cost"][axis] == sum(budget[key][axis] for key in
                    ("consumed_cost","reserved_cost","unfulfilled_cost")), "XDL model cost not conserved")
    require(previous==summary["controller_snapshot"] and previous["status"]==summary["controller_status"], "Final state mismatch")
    if previous["status"]=="LOCKED":
        require(previous["confirmation_count"]>=config["confirmations"] and len(observations)>=config["confirmations"],
                "No independent new confirmation")
    trace = [json.loads(line) for line in (output/"frame_trace.jsonl").read_text(encoding="utf-8").splitlines()]
    require(len([t for t in trace if t["event"]=="controller_transition"])==len(transitions), "Trace transition inventory")
    require(len([t for t in trace if t["event"]=="observation_metrics"])==len(observations), "Trace observation inventory")
    return dict(status="PASS",attempts=len(ledger),independent_observations=len(observations),
                rule_transitions=len(transitions),software_only=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--dependencies",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.out,load_dependencies(args.dependencies)),ensure_ascii=False))
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,IndexError) as exc:
        print(json.dumps({"status":"FAIL","reason":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
