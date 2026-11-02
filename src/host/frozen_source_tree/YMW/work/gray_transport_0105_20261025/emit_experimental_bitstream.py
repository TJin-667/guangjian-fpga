"""Emit an experimental bit from the exact reviewed DCP; never contact hardware."""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from report_implementation import resources

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SOURCE_COMMIT = '46f9d50cf2d854f2e9f31bf8b0dddfe9b2025c07'
CHECKPOINT_SHA = '175d82b777469cc1e94d4123ace9935ea25f8d47902476ee6f926ca47c30c947'
INPUT_MANIFEST_SHA = '579069b9157e53034fc1db7c2a7c988ceab54ad63b852a656da3b4393582765a'
BIT_NAME = 'bx72_0106_gray_EXPERIMENTAL_NOT_RELEASED.bit'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def bit_header(path):
    """Parse the standard Xilinx .bit container and its exact payload extent."""
    data = path.read_bytes()
    at = 0

    def take(size):
        nonlocal at
        value = data[at:at + size]
        if len(value) != size:
            raise ValueError('Truncated bitstream container')
        at += size
        return value

    def integer(size):
        return int.from_bytes(take(size), 'big')

    magic = take(integer(2))
    if magic != bytes.fromhex('0ff00ff00ff00ff000') or integer(2) != 1:
        raise ValueError('Invalid bitstream container signature')
    fields = {}
    for key, name in [(b'a', 'design'), (b'b', 'part'), (b'c', 'date'), (b'd', 'time')]:
        if take(1) != key:
            raise ValueError('Unexpected bitstream field order')
        value = take(integer(2))
        if not value.endswith(b'\0'):
            raise ValueError('Unterminated bitstream text field')
        fields[name] = value[:-1].decode('ascii')
    if take(1) != b'e':
        raise ValueError('Missing bitstream payload')
    fields['payload_bytes'] = integer(4)
    payload = take(fields['payload_bytes'])
    if at != len(data) or fields['payload_bytes'] <= 0:
        raise ValueError('Invalid bitstream payload extent')
    if bytes.fromhex('aa995566') not in payload[:1024]:
        raise ValueError('Missing FPGA configuration sync word')
    return fields


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--vivado', type=Path, default=Path('F:/Xilinx/Vivado/2018.3/bin/vivado.bat'))
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    source_manifest = args.source_manifest.resolve()
    if sha(checkpoint) != CHECKPOINT_SHA or sha(source_manifest) != INPUT_MANIFEST_SHA:
        raise ValueError('Not the exact reviewed DCP/source manifest')
    chain = json.loads((HERE / 'verification/postroute_03/SOURCE_CHAIN.json').read_bytes())
    pinned = json.loads((HERE / 'verification/board_build_02/COMMITTED_SOURCE.json').read_bytes())
    audit = json.loads((HERE / 'verification/postroute_03/READONLY_AUDIT.json').read_bytes())
    status = json.loads((HERE / 'STATUS.json').read_bytes())
    if (chain['optimized_checkpoint_sha256'] != CHECKPOINT_SHA
            or pinned['candidate_source_commit'] != SOURCE_COMMIT
            or chain['candidate_source_commit'] != SOURCE_COMMIT
            or not audit['completed'] or not status['resource_and_timing_gate_passed']):
        raise ValueError('Reviewed implementation evidence does not match')
    source_pins = {}
    for item in pinned['files'].values():
        relative, expected = item['repository_path'], item['sha256']
        committed = subprocess.check_output(['git', 'show', f'{SOURCE_COMMIT}:{relative}'], cwd=REPO)
        if sha(REPO / relative) != expected or hashlib.sha256(committed).hexdigest() != expected:
            raise ValueError('Modified candidate source: ' + relative)
        source_pins[relative] = expected
    script = HERE / 'emit_experimental_bitstream.tcl'
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'emission_script.tcl').write_bytes(script.read_bytes())
    (out / 'emission_runner.py').write_bytes(Path(__file__).read_bytes())
    command = [str(args.vivado), '-mode', 'batch', '-source', str(out / 'emission_script.tcl'),
               '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou'),
               '-tclargs', str(checkpoint), str(out / 'artifact')]
    record = dict(candidate_source_commit=SOURCE_COMMIT, checkpoint=str(checkpoint),
                  checkpoint_sha256=CHECKPOINT_SHA, input_manifest_sha256=INPUT_MANIFEST_SHA,
                  source_sha256=source_pins, runner_sha256=sha(Path(__file__)), script_sha256=sha(script),
                  command=command, experimental=True, release_ready=False, hardware_tested=False,
                  hardware_contacted=False, external_IO_qualified=False, implementation_rerun=False,
                  constraints_changed=False, programming_performed=False, bit_generated=False,
                  candidate_verified=False)
    dump(out / 'input_manifest.json', record)
    started = time.monotonic()
    print('EMIT_REVIEWED_EXPERIMENTAL_BIT ' + str(out), flush=True)
    try:
        with (out / 'console.txt').open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=1200, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        record['tool_returncode'] = result.returncode
        bit = out / 'artifact' / BIT_NAME
        record['bit_generated'] = bit.is_file()
        if result.returncode or not (out / 'artifact/emission_complete.txt').is_file():
            raise ValueError('Vivado bit emission did not complete successfully')
        header = bit_header(bit)
        if header['part'] != '7a100tfgg484':
            raise ValueError('Unexpected bitstream part: ' + header['part'])
        gates = list(csv.DictReader((out / 'artifact/gate.csv').open(encoding='utf-8')))
        if len(gates) != 1 or gates[0]['part'] != 'xc7a100tfgg484-2':
            raise ValueError('Incorrect part or gate row count')
        wns, whs = float(gates[0]['wns_ns']), float(gates[0]['whs_ns'])
        usage = resources(out / 'artifact/utilization.rpt')
        route = (out / 'artifact/route_status.rpt').read_text(encoding='utf-8')
        errors = re.search(r'# of nets with routing errors[.\s]*:\s*(\d+)', route)
        if errors is None or int(errors.group(1)) != 0:
            raise ValueError('Route error gate failed or unavailable')
        if (wns < 0 or whs < 0 or int(gates[0]['blocking_drc']) != 0
                or usage['BRAM_36K_equivalent'] > 108 or usage != status['resources']):
            raise ValueError('Resource/timing/DRC gate failed or unexpected implementation change')
        if sha(checkpoint) != CHECKPOINT_SHA or sha(script) != record['script_sha256']:
            raise ValueError('Emission input changed during operation')
        for relative, digest in source_pins.items():
            if sha(REPO / relative) != digest:
                raise ValueError('Candidate source changed during operation: ' + relative)
        record.update(candidate_verified=True, bitstream=dict(name=BIT_NAME, bytes=bit.stat().st_size,
                      sha256=sha(bit), header=header), wns_ns=wns, whs_ns=whs, resources=usage,
                      checkpoint_unchanged=True, route_errors=0)
    except Exception as exc:
        record['failure'] = f'{type(exc).__name__}: {exc}'
    record['wall_seconds'] = round(time.monotonic() - started, 3)
    record['artifact_sha256'] = {p.name: sha(p) for p in sorted((out / 'artifact').glob('*')) if p.is_file()}
    record['limits'] = ['Engineering candidate only; no hardware operation or release acceptance.',
                        'Existing external IO/reset/CDC qualification gaps and narrow timing margin remain.',
                        'Original 0105 bit, installed capture software and rollback are not modified.']
    dump(out / 'verification.json', record)
    print(json.dumps(record, ensure_ascii=False, indent=2), flush=True)
    if not record['candidate_verified']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
