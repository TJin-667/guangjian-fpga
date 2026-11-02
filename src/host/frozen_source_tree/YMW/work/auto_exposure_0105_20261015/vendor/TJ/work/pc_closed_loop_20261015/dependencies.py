"""Load unchanged flat modules in isolated namespaces, with SHA-bound inputs."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[3]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_read(path):
    def bad(value):
        raise ValueError("Nonfinite JSON: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=bad)


def verify_dependencies(root):
    root = Path(root).resolve()
    manifest = json_read(root / "dependencies.json")
    if len(manifest["files"]) != 72:
        raise ValueError("Incomplete dependency snapshot")
    for relative, row in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or digest(path) != row["sha256"]:
            raise ValueError("Dependency changed: " + relative)
    return manifest


@contextmanager
def flat_namespace(paths, prefix, transforms=None, injections=None):
    """Resolve existing flat imports without permanently replacing caller modules."""
    previous, modules = {}, {}
    try:
        for name, path in paths:
            qualified = prefix + "." + name
            spec = importlib.util.spec_from_file_location(qualified, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[qualified] = module
            previous[name] = sys.modules.get(name)
            sys.modules[name] = module
            source = Path(path).read_bytes()
            if transforms and name in transforms:
                source = transforms[name](source)
            if injections and name in injections:
                module.__dict__.update(injections[name])
            exec(compile(source, str(path), "exec"), module.__dict__)
            modules[name] = module
        yield SimpleNamespace(**modules)
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def load_dependencies(root, *, include_peer=False):
    import publication
    root = Path(root).resolve()
    manifest = verify_dependencies(root)
    xdl = ROOT / "XDL/XDL_Software_Controller"
    prefix = "_tj_pc_" + uuid.uuid4().hex
    with flat_namespace([(name, xdl / (name + ".py")) for name in
                         ("capture_metrics", "acquisition_control", "fpga_reference")],
                        prefix + ".xdl") as controller:
        pass
    names = ["identity_diag", "acquisition_support", "acquisition_executor"]
    if include_peer:
        names += ["reference", "run_xdl_revision2", "acquisition_test_peer"]
    with flat_namespace([(name, root / "sdk" / (name + ".py")) for name in names],
                        prefix + ".sdk",
                        transforms={"acquisition_executor":publication.executor_overlay},
                        injections={"acquisition_executor":{"publish_directory":publication}}) as sdk:
        pass
    algorithm = controller.capture_metrics.load_algorithm(root / "algorithm",
                                                         root / "history")
    hashes = {str(p): digest(p) for p in sorted(xdl.glob("*.py"))}
    return SimpleNamespace(root=root, manifest=manifest, xdl=controller, sdk=sdk,
        algorithm=algorithm,controller_hashes=hashes,
        sdk_publication_overlay=publication.VERSION,
        effective_executor_sha256=hashlib.sha256(publication.executor_overlay(
            (root/"sdk/acquisition_executor.py").read_bytes())).hexdigest(),
        publication_source_sha256=digest(Path(publication.__file__)))
