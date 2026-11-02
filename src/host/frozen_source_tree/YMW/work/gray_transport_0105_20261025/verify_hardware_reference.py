"""Read the local hardware handoff and compare vendor pins with exact DCP exports.

Requires openpyxl for read-only XLSX access. Does not open sockets, run Vivado,
change constraints, execute reference scripts or modify the reference directory.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import re
from openpyxl import load_workbook


def digest(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def save(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--pin-xdc', type=Path, required=True)
    parser.add_argument('--native-audit', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    root = args.reference_root
    inventories = []
    for name, rows_key, path_key in [('FILE_INDEX.json', 'files', 'relative_path'),
                                     ('MANIFEST.json', 'members', 'path')]:
        obj = json.loads((root / name).read_bytes())
        rows = []
        for row in obj[rows_key]:
            relative = Path(row[path_key])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe reference inventory path')
            actual = digest(root / relative)
            rows.append({'path': relative.as_posix(), **actual,
                         'matches': actual == {k: row[k] for k in ('bytes', 'sha256')}})
        inventories.append({'inventory': name, **digest(root / name), 'checks': rows,
                            'all_match': all(r['matches'] for r in rows)})
    if not all(r['all_match'] for r in inventories):
        save(args.out / 'FAILED_REFERENCE_VERIFICATION.json', inventories)
        raise ValueError('reference size/SHA256 mismatch')

    workbook = root / 'documents/BX72_pins_V2_1.xlsx'
    wb = load_workbook(workbook, read_only=True, data_only=False)
    sheet = wb['Sheet1']
    vendor = {}
    for row in sheet.iter_rows(min_row=26, max_row=56, min_col=2, max_col=3):
        name, pin = row
        if name.value is not None and pin.value is not None:
            vendor[name.value] = {'pin': pin.value, 'sheet': sheet.title,
                                  'net_cell': name.coordinate, 'pin_cell': pin.coordinate}
    wb.close()
    mappings = {**{f'cam_data[{i}]': f'CAMERA_D{i}' for i in range(8)},
                'cam_href': 'CAMERA_HREF', 'cam_vsync': 'CAMERA_VSYNC',
                'cam_pclk': 'CAMERA_PCLK', 'cam_xclk': 'CAMERA_XCLK',
                'cam_sda': 'CAMERA_SDA', 'cam_scl': 'CAMERA_SCLK',
                'eth_rstn': 'ENET0_RST', 'eth_mdc': 'ENET0_MDC', 'eth_mdio': 'ENET0_MDIO',
                'rgmii_rx_clk_i': 'ENET0_RX_CLK', 'rgmii_rxdv': 'ENET0_RX_DV',
                'rgmii_tx_clk': 'ENET0_GTX_CLK', 'rgmii_txen': 'ENET0_TX_EN',
                **{f'rgmii_rxd[{i}]': f'ENET0_RX_DATA{i}' for i in range(4)},
                **{f'rgmii_txd[{i}]': f'ENET0_TX_DATA{i}' for i in range(4)}}
    xdc = args.pin_xdc.read_text('utf-8')
    pin_defs = re.findall(r'set_property\s+PACKAGE_PIN\s+(\S+)\s+\[get_ports\s+(?:\{([^}]+)\}|([^\]\s]+))\]', xdc)
    pins = {(a or b): pin for pin, a, b in pin_defs}
    ports_file = args.native_audit / 'reports/ports.tsv'
    with ports_file.open(encoding='utf-8', newline='') as f:
        ports = {r['port']: r for r in csv.DictReader(f, delimiter='\t')}
    checks = []
    for port, net in mappings.items():
        rec = vendor[net]
        checks.append({'port': port, 'vendor_net': net, **rec,
                       'xdc_pin': pins.get(port), 'native_DCP_pin': ports[port]['package_pin'],
                       'native_DCP_IOSTANDARD': ports[port]['iostandard'],
                       'matches': rec['pin'] == pins.get(port) == ports[port]['package_pin']})
    if not all(r['matches'] for r in checks):
        save(args.out / 'FAILED_PIN_CROSSCHECK.json', checks)
        raise ValueError('vendor/XDC/native pin mismatch')
    native = json.loads((args.native_audit / 'verification.json').read_bytes())
    crosscheck = {'workbook': {'path': workbook.as_posix(), **digest(workbook)},
                  'pin_xdc': {'path': args.pin_xdc.as_posix(), **digest(args.pin_xdc)},
                  'native_ports': {'path': ports_file.as_posix(), **digest(ports_file)},
                  'matched': len(checks), 'mismatched': 0, 'checks': checks,
                  'unused_vendor_signal': {'name': 'ENET0_INT_N', **vendor['ENET0_INT_N'],
                                           'reason': 'Not exposed as a top-level candidate port'},
                  'scope': '14 camera + 15 Ethernet physical pin bindings only; not IO timing or voltage qualification'}
    save(args.out / 'PIN_CROSSCHECK.json', crosscheck)
    for source in ['START_HERE.md', 'TO_NEXT_CHAT.txt', 'FILE_INDEX.json', 'HARDWARE_FACTS.json',
                   'records/physical_photo_receipt_original.json']:
        dest = args.out / 'source_records' / source
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((root / source).read_bytes())
    receipt = {'revision': 'r3.7', 'date': '2026-10-25', 'all_reference_checks_passed': True,
               'index_files': 15, 'manifest_members': 22, 'inventories': inventories,
               'pin_matches': len(checks), 'pin_mismatches': 0,
               'native_audit_verification_sha256': digest(args.native_audit / 'verification.json')['sha256'],
               'native_checkpoint_evidence': native,
               'verifier_sha256': digest(Path(__file__))['sha256'],
               'reference_modified': False, 'hardware_contacted': False, 'network_changed': False,
               'IO_qualification_passed': False, 'bit_generated': False, 'release_ready': False}
    save(args.out / 'verification.json', receipt)
    print(json.dumps({k: receipt[k] for k in ['revision', 'all_reference_checks_passed', 'index_files',
                      'manifest_members', 'pin_matches', 'pin_mismatches', 'hardware_contacted',
                      'IO_qualification_passed']}, indent=2))


if __name__ == '__main__':
    main()
