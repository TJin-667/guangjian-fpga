"""Re-decode archived 0106 STATUS/capability packets; no hardware access."""
import argparse
import datetime
import json
from pathlib import Path

import probe_0106_capabilities as probe


def review(path):
    path = Path(path)
    raw = path.read_bytes()
    record = json.loads(raw)
    core, protocol, bit, _ = probe.preflight()
    if (record['schema'] != 'guangjian-experimental-0106-readonly-v1'
            or record['status'] != 'NEW_0106_STATUS_AND_CAPABILITIES_CONFIRMED'
            or record['allowed_commands'] != [3, 14]
            or record['captures_requested'] or record['configuration_commands_sent']
            or record['bit_programmed'] or record['board_bit_sha_readback_verified']
            or record['local_candidate_bit_sha256'] != core.digest(bit)):
        raise ValueError('Unexpected probe scope or bit provenance')
    for source, digest in record['source_sha256'].items():
        if core.digest(source) != digest:
            raise ValueError('Probe source changed: ' + source)
    queries = record['queries']
    if len(queries) != 2 or [q['kind'] for q in queries] != [3, 14]:
        raise ValueError('Unexpected command set')
    first, second = queries
    if bytes.fromhex(first['request_hex']) != protocol.command(3, first['seq']):
        raise ValueError('STATUS request bytes changed')
    if bytes.fromhex(second['request_hex']) != probe.wire.legacy.command(14, second['seq'], 0):
        raise ValueError('Capability request bytes changed')
    decoded = []
    for row in queries:
        items = []
        for response in row['responses']:
            if response['peer'] != [record['board'], record['port']]:
                raise ValueError('Unexpected packet source')
            data = bytes.fromhex(response['packet_hex'])
            item = (probe.wire.decode_capabilities(data, row['seq']) if row['kind'] == 14
                    else protocol.control(data))
            if json.loads(json.dumps(item)) != response['decoded']:
                raise ValueError('Raw response and stored decoding differ')
            if row['kind'] == 3 and item['seq'] != row['seq']:
                raise ValueError('Wrong response sequence')
            items.append(item)
        decoded.append(items)
    ack = [i for i in decoded[0] if i['type'] == protocol.ACK]
    status = [i for i in decoded[0] if i['type'] == protocol.STATUS]
    if len(ack) != 1 or len(status) != 1 or ack[0]['original'] != 3 or ack[0]['result']:
        raise ValueError('Missing/failed STATUS ACK')
    state = status[0]
    if (state['firmware'] != 0x0106 or not state['state'] & 16 or state['state'] & 3
            or state['error'] or state['capabilities'] != 127):
        raise ValueError('New firmware is not ready/error-free')
    if len(decoded[1]) != 1 or decoded[1][0]['format'] != 1:
        raise ValueError('Unexpected transport capability result')
    local_time = datetime.datetime.fromisoformat(record['utc']).astimezone(
        datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    return dict(schema='guangjian-0106-handshake-review-v1', status='PASS', local_time=local_time,
                raw_probe_sha256=core.digest(path), reviewer_sha256=core.digest(__file__),
                firmware_hex='0x0106', ready=True, busy=False, error=0,
                formats=['RGB565', 'GRAY8+SAT1'], default_format=1, required_payload_crc64=True,
                status_sequence=first['seq'], capability_sequence=second['seq'], raw_responses=3,
                captures_requested=0, source_endpoint=[record['board'], record['port']],
                local_candidate_bit_sha256=core.digest(bit),
                on_board_full_bit_sha_readback_verified=False,
                assistant_sent_new_board_commands=False, programmed_by_assistant=False,
                scope='User-run real-board firmware/protocol handshake only',
                gray_payload_hardware_verified=False, per_pixel_equivalence_verified=False,
                external_IO_qualified=False, release_ready=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('Use a new review receipt')
    result = review(args.probe)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))
