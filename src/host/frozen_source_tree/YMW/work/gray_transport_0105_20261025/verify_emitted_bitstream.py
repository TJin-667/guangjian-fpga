"""Independently review existing emission bytes without rerunning Vivado."""
import argparse
from collections import Counter
import csv
import json
import re
import subprocess
from pathlib import Path

import emit_experimental_bitstream as emitter


def review(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'input_manifest.json').read_bytes())
    original = json.loads((folder / 'verification.json').read_bytes())
    artifact = folder / 'artifact'
    require = lambda condition, message: condition or fail(message)
    require(original['tool_returncode'] == 0, 'Vivado did not exit successfully')
    require((artifact / 'emission_complete.txt').is_file(), 'No completion marker')
    for key in ('hardware_contacted', 'implementation_rerun', 'constraints_changed', 'programming_performed'):
        require(manifest[key] is False and original[key] is False, 'Unexpected operation: ' + key)
    require(emitter.sha(folder / 'emission_script.tcl') == manifest['script_sha256'] ==
            emitter.sha(emitter.HERE / 'emit_experimental_bitstream.tcl'), 'Emission Tcl source changed')
    require(emitter.sha(folder / 'emission_runner.py') == manifest['runner_sha256'], 'Executing runner snapshot changed')
    require(emitter.sha(Path(manifest['checkpoint'])) == emitter.CHECKPOINT_SHA ==
            manifest['checkpoint_sha256'], 'Reviewed DCP changed')
    require(manifest['candidate_source_commit'] == emitter.SOURCE_COMMIT, 'Incorrect source commit')
    for relative, expected in manifest['source_sha256'].items():
        raw = subprocess.check_output(['git', 'show', f'{emitter.SOURCE_COMMIT}:{relative}'], cwd=emitter.REPO)
        require(emitter.hashlib.sha256(raw).hexdigest() == emitter.sha(emitter.REPO / relative) == expected,
                'Source pin changed: ' + relative)
    for name, digest in original['artifact_sha256'].items():
        require(emitter.sha(artifact / name) == digest, 'Original emission artifact changed: ' + name)
    gates = list(csv.DictReader((artifact / 'gate.csv').open(encoding='utf-8')))
    require(len(gates) == 1 and gates[0]['part'] == 'xc7a100tfgg484-2', 'Unexpected gate part or count')
    gate = gates[0]
    wns, whs = float(gate['wns_ns']), float(gate['whs_ns'])
    require(wns >= 0 and whs >= 0 and int(gate['blocking_drc']) == 0, 'Timing/DRC failed')
    usage = emitter.resources(artifact / 'utilization.rpt')
    expected = json.loads((emitter.HERE / 'STATUS.json').read_bytes())['resources']
    require(usage == expected and usage['BRAM_36K_equivalent'] <= 108, 'Resource mismatch/budget')
    timing = (artifact / 'timing.rpt').read_text(encoding='utf-8')
    require('All user specified timing constraints are met.' in timing, 'Timing report did not pass')
    route = (artifact / 'route_status.rpt').read_text(encoding='utf-8')
    match = re.search(r'# of nets with routing errors[.\s]*:\s*(\d+)', route)
    require(match is not None and int(match[1]) == 0, 'Route errors or unknown report')
    violations = list(csv.DictReader((artifact / 'violations.tsv').open(encoding='utf-8'), delimiter='\t'))
    counts = dict(Counter(row['severity'] for row in violations))
    require(not any(k in counts for k in ('Error', 'Critical Warning')), 'Blocking DRC')
    bit = artifact / emitter.BIT_NAME
    header = emitter.bit_header(bit)
    require(header['part'] == '7a100tfgg484' and 'Version=2018.3' in header['design'], 'Bit header mismatch')
    return dict(schema='guangjian-experimental-bit-review-v1', candidate_verified=True,
                bit_generated=True, experimental=True, hardware_tested=False, hardware_contacted=False,
                release_ready=False, external_IO_qualified=False, programming_performed=False,
                candidate_source_commit=emitter.SOURCE_COMMIT, checkpoint_sha256=emitter.CHECKPOINT_SHA,
                checkpoint_unchanged=True, original_emission_receipt_sha256=emitter.sha(folder / 'verification.json'),
                original_runner_postcheck_failure=original.get('failure'),
                review_reason='Independent existing-byte review; original receipt retained. '
                              'Initial runner did not accept dot-padded route report labels. No FPGA rebuild.',
                verifier_sha256=emitter.sha(Path(__file__)), parser_sha256=emitter.sha(Path(emitter.__file__)),
                bitstream=dict(name=bit.name, bytes=bit.stat().st_size, sha256=emitter.sha(bit), header=header),
                wns_ns=wns, whs_ns=whs, resources=usage, route_errors=0, prebit_DRC_severities=counts,
                artifact_sha256={p.name: emitter.sha(p) for p in sorted(artifact.iterdir()) if p.is_file()},
                limits=['Experimental bit only; existing IO/reset/CDC qualification gaps remain.',
                        'No hardware operation, optical capture or fusion/confidence quality result.'])


def fail(message):
    raise ValueError(message)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emission', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Use a new review receipt')
    result = review(args.emission)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
