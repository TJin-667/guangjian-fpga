"""Archive small, SHA-bound peer evidence; full synthetic images stay local."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from dependencies import digest, json_read, ROOT


def inventory(root):
    return {p.relative_to(root).as_posix():digest(p)
            for p in sorted(root.rglob("*")) if p.is_file() and p.name!="archive_manifest.json"}


def audit_archive(root):
    manifest=json_read(root/"archive_manifest.json")
    if manifest["files"]!=inventory(root):
        raise ValueError("Archived file inventory/SHA mismatch")
    verification=json_read(root/"verification.json")
    rows=list(csv.DictReader((root/"cases.csv").open(encoding="utf-8",newline="")))
    if (verification["status"]!="PASS" or not verification["complete_case_inventory"] or
            len(rows)!=verification["cases"] or any(r["status"]!="PASS" for r in rows) or
            [int(r["case_index"]) for r in rows]!=list(range(1,len(rows)+1))):
        raise ValueError("Incomplete/failed case receipts")
    for file, expected in verification["source_sha256"].items():
        # Match only these two repository namespaces, without requiring the
        # original machine's absolute checkout path on a new machine.
        normalized=file.replace("\\","/")
        prefixes=("TJ/work/pc_closed_loop_20261015/","XDL/XDL_Software_Controller/")
        relative=next((prefix+normalized.split("/"+prefix,1)[1] for prefix in prefixes
                       if "/"+prefix in normalized),None)
        if relative is None:
            raise ValueError("Unrecognized executed-source path: "+file)
        source=(ROOT/relative).resolve()
        if not source.is_relative_to(ROOT):
            raise ValueError("Executed-source path escapes checkout")
        if digest(source)!=expected:
            raise ValueError("Executed source no longer matches: "+file)
    if manifest["board_verified"] or manifest["physical_freshness_verified"]:
        raise ValueError("Peer archive claimed board evidence")
    return {"status":"PASS","files":len(manifest["files"]),"cases":len(rows)}


def export(work,out):
    verification=json_read(work/"verification.json")
    if verification["status"]!="PASS" or not verification["complete_case_inventory"]:
        raise ValueError("Only a complete passing run can be archived as final evidence")
    out.mkdir(parents=True,exist_ok=False)
    def copy(source,target):
        target=out/target
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    for name in ("verification.json","cases.csv","cases.json","cli_stdout.txt"):
        copy(work/name,name)
    for file in sorted(work.glob("*_audit.txt")):
        copy(file,"negative_audits/"+file.name)
    aggregate=dict(attempts=0,independent_observations=0,rule_transitions=0,
                   known_frame_lower_bound=0,reserved_requested_frames=0,
                   publication_retries=0)
    for case in sorted((work/"cases").iterdir()):
        loop=case/"loop"
        if not loop.is_dir():
            raise ValueError("Missing loop evidence: "+case.name)
        summary=json_read(loop/"summary.json")
        aggregate["attempts"]+=summary["attempts"]
        aggregate["independent_observations"]+=summary["accepted_observations"]
        aggregate["rule_transitions"]+=len(json_read(loop/"transitions.json"))
        aggregate["known_frame_lower_bound"]+=summary["transport_cost"]["known_frames"]
        aggregate["reserved_requested_frames"]+=summary["transport_cost"]["reserved_frame_upper_bound"]
        aggregate["publication_retries"]+=summary["transport_cost"]["publication_retries"]
        for name in ("summary.json","receipt.json","cost_ledger.json","observations.json","transitions.json"):
            copy(loop/name,"cases/"+case.name+"/"+name)
        copy(case/"peer_receipt.json","cases/"+case.name+"/peer_receipt.json")
        # Compress verbatim trace bytes; receipt preserves their original SHA.
        target=out/"cases"/case.name/"frame_trace.jsonl.gz"
        with (loop/"frame_trace.jsonl").open("rb") as source,target.open("wb") as dest:
            with gzip.GzipFile(fileobj=dest,mode="wb",mtime=0) as compressed:
                shutil.copyfileobj(source,compressed)
        with gzip.open(target,"rb") as source:
            if hashlib.sha256(source.read()).hexdigest()!=digest(loop/"frame_trace.jsonl"):
                raise ValueError("Trace compression changed bytes")
    (out/"aggregate.json").write_text(json.dumps(aggregate,indent=2)+"\n",encoding="utf-8")
    manifest=dict(schema=1,software_only=True,board_verified=False,
                  physical_freshness_verified=False,
                  validation_scope="Archive SHA/case inventory and executed source; not a re-run of UDP or pixels",
                  full_local_run=str(work),images_and_masks_omitted=True,files=inventory(out))
    (out/"archive_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return audit_archive(out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work",type=Path)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--audit-only",action="store_true")
    args=p.parse_args()
    try:
        result=audit_archive(args.out.resolve()) if args.audit_only else export(args.work.resolve(),args.out.resolve())
        print(json.dumps(result))
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps({"status":"FAIL","reason":str(exc)}))
        raise SystemExit(2)
