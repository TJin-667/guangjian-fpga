"""Pinned dependencies and durable records for the TJ PC acquisition executor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np

YMW_COMMIT = "de18e3b604158c1b53b87b08f22ddc59ed52cfe2"
BASE_COMMIT = "cfce1cb3d9a16d6609afa5e8954250eb79a275df"
PIPELINE = Path(__file__).resolve().parents[1]


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_protocol(root):
    """Load the unchanged YMW codec after verifying the complete pinned manifest."""
    root = Path(root).resolve()
    manifest = json.loads((root / "pinned_manifest.json").read_text(encoding="utf-8"))
    if manifest["commit"] != YMW_COMMIT:
        raise ValueError("YMW dependency commit mismatch")
    entries = manifest["files"]
    if len(entries) != 56 or len({r["path"] for r in entries}) != 56:
        raise ValueError("incomplete/duplicate pinned YMW dependencies")
    for row in entries:
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("dependency path escapes pinned root")
        data = path.read_bytes()
        if (len(data) != row["bytes"] or sha_bytes(data) != row["sha256"] or
                hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() != row["git_blob"]):
            raise ValueError("modified pinned dependency: " + row["path"])
    name = "tj_pinned_wire_v1_" + sha_file(root / "host/protocol.py")[:16]
    spec = importlib.util.spec_from_file_location(name, root / "host/protocol.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_hashes(root):
    """Executable sources, not mutable reports, are frozen for each verification."""
    root = Path(root).resolve()
    paths = set(PIPELINE.joinpath("software").glob("*.py"))
    paths.update(PIPELINE.joinpath("rtl").glob("*.v"))
    paths.update(PIPELINE.joinpath("integration").glob("*.v"))
    paths.update(PIPELINE.joinpath("sim").glob("*.sv"))
    manifest = json.loads((root / "pinned_manifest.json").read_text(encoding="utf-8"))
    paths.update(root / entry["path"] for entry in manifest["files"])
    paths.add(root / "pinned_manifest.json")
    return {str(p.resolve()): sha_file(p) for p in sorted(paths)}


def check_hashes(hashes):
    for name, expected in hashes.items():
        if sha_file(name) != expected:
            raise ValueError("source/input changed: " + name)


def image_metrics(raw, width, height, mask):
    """Integer contract check using integral sums, independent of peer OpenCV."""
    if len(raw) != width*height*2 or len(mask) != width*height:
        raise ValueError("metrics shape")
    pixels = np.frombuffer(raw, dtype=">u2").reshape(height,width).astype(np.uint32)
    r5,g6,b5 = pixels>>11,(pixels>>5)&63,pixels&31
    r,g,b = (r5<<3)|(r5>>2),(g6<<2)|(g6>>4),(b5<<3)|(b5>>2)
    gray = ((r*9798+g*19235+b*3735+16384)>>15).astype(np.uint8)
    rgbmax = (r5==31)|(g6==63)|(b5==31)
    board = np.frombuffer(mask,dtype=np.uint8).reshape(height,width).astype(bool)
    h1 = [width*height,int(gray.sum(dtype=np.uint64)),int((gray<=5).sum()),int((gray>=250).sum()),int(rgbmax.sum()),
          int(board.sum()),int(gray[board].sum(dtype=np.uint64)),int((gray[board]<=10).sum()),int((gray[board]>=250).sum()),int(rgbmax[board].sum())]
    reflected = np.pad(gray,4,mode="reflect")
    integral = np.pad(reflected,((1,0),(1,0))).cumsum(axis=0,dtype=np.int64).cumsum(axis=1,dtype=np.int64)
    sum9 = integral[9:,9:]-integral[:-9,9:]-integral[9:,:-9]+integral[:-9,:-9]
    residual = 81*gray.astype(np.int32)-sum9
    h2 = dict(strong_count=int((np.abs(residual)>1620).sum()),weak_count=int((np.abs(residual)>648).sum()),
              sum9_total=int(sum9.sum(dtype=np.int64)),residual_n_total=int(residual.sum(dtype=np.int64)))
    return h1,h2
