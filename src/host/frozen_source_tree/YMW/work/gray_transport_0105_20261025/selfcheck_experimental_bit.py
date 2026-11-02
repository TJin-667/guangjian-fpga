"""Offline final self-check of the new bit, entry and preserved baseline."""
import argparse
import ast
import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import emit_experimental_bitstream as emitter
import probe_0106_capabilities as probe
import verify_emitted_bitstream as verifier

HERE = emitter.HERE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Use a new self-check receipt')
    checks = []
    folder = HERE / 'verification/experimental_bit_01'
    result = verifier.review(folder)
    original_review = json.loads((folder / 'INDEPENDENT_REVIEW.json').read_bytes())
    for key in ['candidate_verified', 'checkpoint_sha256', 'bitstream', 'resources', 'wns_ns', 'whs_ns', 'route_errors']:
        if result[key] != original_review[key]:
            raise ValueError('Independent review drift: ' + key)
    checks.append('Bit header/payload extent/SHA, original emission bytes, exact DCP and 7 committed RTL source pins')
    status = json.loads((HERE / 'STATUS.json').read_bytes())
    artifact = status['bit_artifact']
    if (status['bit_generated'] is not True or status['experimental_bit_candidate_verified'] is not True
            or emitter.sha(HERE / artifact['path']) != original_review['bitstream']['sha256']):
        raise ValueError('Bit status mismatch')
    if (emitter.sha(HERE / artifact['path']) != artifact['sha256']
            or emitter.sha(HERE / artifact['build_receipt_path']) != artifact['build_receipt_sha256']):
        raise ValueError('Bit binding or review receipt changed')
    for key in ['release_ready', 'hardware_tested', 'external_IO_qualified', 'SDK_0106_operator_entry_hardware_enabled']:
        if status[key] is not False:
            raise ValueError('Qualification boundary changed: ' + key)
    checks.append('STATUS bit binding matches; production/hardware/IO qualification remains false')
    with patch.object(socket, 'socket', side_effect=AssertionError('Offline check must not create a socket')):
        probe.preflight()
    checks.append('New entry preflight passed with all socket creation prohibited')
    loopback = json.loads((HERE / 'verification/experimental_probe_01/verification.json').read_bytes())
    if loopback['status'] != 'PASS' or loopback['hardware_contacted'] or loopback['captures_requested']:
        raise ValueError('Invalid loopback receipt')
    for name, digest in loopback['source_sha256'].items():
        if emitter.sha(HERE / name) != digest:
            raise ValueError('Loopback-tested source changed: ' + name)
    if [q['kind'] for q in loopback['queries']] != [3, 14] or not all(q['complete'] for q in loopback['queries']):
        raise ValueError('Unexpected loopback commands/results')
    checks.append('Protected-loopback source pins and raw command 3/14 responses retained')
    syntax = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile("
        "(Join-Path (Get-Location) 'RUN_NEW_0106_CHECK.ps1'),[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count) {$errors; exit 1}; 'PASS'"], cwd=HERE, capture_output=True, text=True)
    if syntax.returncode != 0 or syntax.stdout.strip() != 'PASS':
        raise ValueError('PowerShell syntax failed: ' + syntax.stdout + syntax.stderr)
    checks.append('PowerShell launcher parsed without execution')
    sources = ['emit_experimental_bitstream.py', 'emit_experimental_bitstream.tcl',
               'verify_emitted_bitstream.py', 'probe_0106_capabilities.py',
               'RUN_NEW_0106_CHECK.cmd', 'RUN_NEW_0106_CHECK.ps1', Path(__file__).name]
    for name in sources:
        if Path(name).suffix == '.py':
            ast.parse((HERE / name).read_bytes())
    manifest_path = emitter.REPO / 'YMW/backups/20261025_before_fixed_pair/BACKUP_MANIFEST.json'
    backup = json.loads(manifest_path.read_bytes())
    missing_or_changed = []
    for entry in backup['files']:
        path = Path(backup['source_root']) / entry['path']
        if not path.is_file() or path.stat().st_size != entry['bytes'] or emitter.sha(path) != entry['sha256']:
            missing_or_changed.append(entry['path'])
    if missing_or_changed:
        raise ValueError('Existing installed files changed/missing: ' + repr(missing_or_changed))
    if len(backup['files']) != 638:
        raise ValueError('Unexpected backup inventory count')
    zip_path = manifest_path.parent / 'BX72_0105_LAB_before_fixed_pair_20261025_145409.zip'
    if emitter.sha(zip_path) != '039293195c2c8dfe57604a0bce9e4fd834240fbd54f387fa62e847a431db1b41':
        raise ValueError('Existing backup ZIP changed')
    checks.append('All 638 installed baseline files and original backup ZIP SHA unchanged, including current/rollback bits')
    record = dict(schema='guangjian-experimental-bit-selfcheck-v1', status='PASS', checks=checks,
                  bit_sha256=artifact['sha256'], resources=result['resources'],
                  wns_ns=result['wns_ns'], whs_ns=result['whs_ns'], baseline_files_verified=638,
                  backup_manifest_sha256=emitter.sha(manifest_path),
                  source_sha256={name: emitter.sha(HERE / name) for name in sources},
                  hardware_contacted=False, physical_captures=0, release_ready=False,
                  unverified=['0106 board programming/handshake and gray payload transport',
                              'same-frozen-hardware-input RGB/GRAY per-pixel equivalence',
                              'external IO/reset/CDC physical qualification',
                              'fusion model quality and confidence calibration (XDL)'])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
