"""Export immutable, existing software dependencies; never build or edit RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

SDK_COMMIT = "2d69deeb169773c9cf54d4499b0c060a933af78e"
XDL_COMMIT = "8e7dec0daaedb0f08ef80b707c83ba37de7e7002"
YMW_COMMIT = "de18e3b604158c1b53b87b08f22ddc59ed52cfe2"
SDK_PREFIX = "TJ/work/fpga_image_pipeline/software/"
YMW_PREFIX = "YMW/work/fourlight_roi_20261013/"


def prepare(repository, output):
    repository, output = Path(repository).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {}

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repository), *args])

    def export(commit, source, target):
        data = git("show", f"{commit}:{source}")
        path = output / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        manifest[target] = {"commit": commit, "repository_path": source, "sha256": digest}
        return data

    # Exact original AcquisitionExecutor and codec. Peer helpers are test-only.
    for name in ("identity_diag.py", "acquisition_support.py", "acquisition_executor.py",
                 "reference.py", "run_xdl_revision2.py", "acquisition_test_peer.py"):
        export(SDK_COMMIT, SDK_PREFIX + name, "sdk/" + name)
    for name in ("__init__.py", "cli.py", "core.py", "image_io.py", "metadata.py",
                 "real_baseline.py", "reports.py"):
        export(XDL_COMMIT, "XDL/light-inspection/light_inspection/" + name,
               "algorithm/light_inspection/" + name)
    export(XDL_COMMIT, "XDL/light-inspection/ymw_integer_reference.py",
           "algorithm/ymw_integer_reference.py")
    export(XDL_COMMIT, "XDL/reference_20261013/analysis/integrity.json",
           "history/integrity.json")

    rows = []
    # The original loader requires its complete 56-file pinned manifest.
    # These read-only dependency copies live outside the checkout. No bit is exported.
    for entry in git("ls-tree", "-rz", YMW_COMMIT, "--", YMW_PREFIX).split(b"\0"):
        if not entry:
            continue
        header, path = entry.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        path = path.decode()
        rel = path[len(YMW_PREFIX):]
        if kind != "blob":
            continue
        selected = ((rel.startswith(("src/", "sim/", "ip2018/", "host/")) and
                     Path(rel).suffix in (".v", ".sv", ".xci", ".py", ".prj")) or
                    rel in ("bx72_1080p_udp.xdc", "mig_b.prj", "mig_a.prj",
                            "build_vivado_2018_3.tcl"))
        if selected:
            data = export(YMW_COMMIT, path, "ymw/" + rel)
            rows.append(dict(path=rel, git_blob=blob, bytes=len(data),
                             sha256=hashlib.sha256(data).hexdigest()))
    if len(rows) != 56:
        raise ValueError(f"Expected 56 pinned dependency files, got {len(rows)}")
    pinned = dict(commit=YMW_COMMIT, files=rows)
    path = output / "ymw/pinned_manifest.json"
    path.write_text(json.dumps(pinned, indent=2) + "\n", encoding="utf-8")
    manifest["ymw/pinned_manifest.json"] = dict(commit=YMW_COMMIT,
        repository_path="generated_manifest_from_fixed_git_objects",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    result = dict(schema=1, files=manifest, sdk_commit=SDK_COMMIT,
                  xdl_commit=XDL_COMMIT, ymw_commit=YMW_COMMIT)
    (output / "dependencies.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.repository, args.out)
        print(json.dumps({"status": "PASS", "files": len(result["files"]),
                          "output": str(args.out.resolve())}))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        raise SystemExit(2)
