"""New-bit engineering check: read STATUS and transport capabilities only."""
import argparse
import datetime
import json
import secrets
import socket
import time
from pathlib import Path

from board_probe import core_module
import host_transport as wire

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / 'verification/experimental_bit_01'
BIT_SHA = '9d3b8566fa1909969c711b0bcb3122fd9d8e059344adcdb6e080b5240e18e1b0'


def preflight():
    core = core_module()
    engine = core.load_engine()
    protocol_path = engine.root / 'ymw/host/protocol.py'
    protocol = wire.pinned_module('_experimental_0106_probe_protocol', protocol_path, core.digest(protocol_path))
    receipt = json.loads((EVIDENCE / 'INDEPENDENT_REVIEW.json').read_bytes())
    bit = EVIDENCE / 'artifact' / receipt['bitstream']['name']
    if (receipt['schema'] != 'guangjian-experimental-bit-review-v1'
            or receipt['candidate_verified'] is not True
            or receipt['candidate_source_commit'] != '46f9d50cf2d854f2e9f31bf8b0dddfe9b2025c07'
            or core.digest(bit) != receipt['bitstream']['sha256'] or core.digest(bit) != BIT_SHA):
        raise ValueError('Experimental bit provenance/hash mismatch')
    return core, protocol, bit, protocol_path


def query(sock, protocol, kind, seq, board, port, timeout):
    packet = protocol.command(kind, seq) if kind == 3 else wire.legacy.command(kind, seq, 0)
    row = dict(kind=kind, seq=seq, request_hex=packet.hex(), responses=[], ignored_packets=0)
    sock.sendto(packet, (board, port))
    deadline = time.monotonic() + timeout
    ack = status = capability = None
    while time.monotonic() < deadline:
        sock.settimeout(max(.001, deadline - time.monotonic()))
        try:
            data, peer = sock.recvfrom(65535)
        except socket.timeout:
            break
        if peer != (board, port) or len(data) < 10 or data[:4] != b'LGHT' or int.from_bytes(data[6:8], 'big') != seq:
            row['ignored_packets'] += 1
            continue
        raw = dict(packet_hex=data.hex(), peer=list(peer))
        row['responses'].append(raw)
        try:
            if kind == 14 and data[5] == 0x86:
                capability = wire.decode_capabilities(data, seq)
                raw['decoded'] = capability
                break
            item = protocol.control(data)
            raw['decoded'] = item
            if item['type'] == protocol.ACK and item['original'] == kind:
                if item['result']:
                    row['failure'] = 'Command rejected: ' + str(item['result'])
                    break
                if ack is not None and ack != item:
                    raise ValueError('Conflicting ACK')
                ack = item
            elif kind == 3 and item['type'] == protocol.STATUS:
                if status is not None and status != item:
                    raise ValueError('Conflicting STATUS')
                status = item
        except ValueError as exc:
            row['failure'] = str(exc)
            break
        if kind == 3 and ack is not None and status is not None:
            break
    row.update(ack=ack, status=status, capabilities=capability)
    row['complete'] = 'failure' not in row and (capability is not None if kind == 14 else ack is not None and status is not None)
    return row


def probe():
    core, protocol, bit, protocol_path = preflight()
    board, bind, port = '192.168.0.2', '192.168.0.3', 5000
    record = dict(schema='guangjian-experimental-0106-readonly-v1',
                  utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), status='FAILED',
                  allowed_commands=[3, 14], queries=[], captures_requested=0,
                  configuration_commands_sent=0, bit_programmed=False, board_bit_sha_readback_verified=False,
                  local_candidate_bit_sha256=core.digest(bit), board=board, bind=bind, port=port,
                  source_sha256={str(Path(__file__).resolve()): core.digest(__file__),
                                 str(protocol_path): core.digest(protocol_path)})
    try:
        with core.operator_lock(Path('C:/BX72_0105_LAB')), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((bind, 0))
            record['local_port'] = sock.getsockname()[1]
            seq = secrets.randbelow(65535)
            state = query(sock, protocol, 3, seq, board, port, 2)
            record['queries'].append(state)
            if not state['complete']:
                raise ValueError('Missing/invalid STATUS ACK or reply')
            state = state['status']
            record['firmware_hex'] = f"0x{state['firmware']:04x}"
            if state['firmware'] != 0x0106 or state['capabilities'] & 0x60 != 0x60:
                raise ValueError('Expected the NEW 0106 bit; do not redo old-bit capture')
            if not state['state'] & 16 or state['state'] & 3 or state['error']:
                raise ValueError('0106 not ready, busy or device error')
            capability = query(sock, protocol, 14, seq + 1, board, port, 2)
            record['queries'].append(capability)
            if not capability['complete'] or capability['capabilities']['format'] != 1:
                raise ValueError('Missing/invalid capabilities or unexpected fresh-bit RGB default')
            record['status'] = 'NEW_0106_STATUS_AND_CAPABILITIES_CONFIRMED'
    except Exception as exc:
        record['failure'] = f'{type(exc).__name__}: {exc}'
    record['scope'] = 'New firmware/protocol handshake only; gray payload, optical quality and IO qualification remain untested.'
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.check_only:
        preflight()
        print('Offline preflight passed. No socket, query or capture.')
    else:
        if args.out is None or args.out.exists():
            raise ValueError('Use a new output file')
        args.out.parent.mkdir(parents=True, exist_ok=True)
        result = probe()
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['status'] == 'NEW_0106_STATUS_AND_CAPABILITIES_CONFIRMED' else 2)
