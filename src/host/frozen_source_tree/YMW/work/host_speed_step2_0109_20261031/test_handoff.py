"""Actual loopback strict SDK producer, warm identities and corrupt-cache rejection."""
import argparse
import copy
from pathlib import Path
import shutil
import socket
import sys
from unittest.mock import patch
from intermediates import base, from_executor, seal, restore, snapshot, native_check, digest
from reuse_context import build_context
import numpy as np


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    base.verify_tool()
    sys.path.insert(0, str(base.BENCHMARK))
    from test_benchmark import peer_class, small_template
    from capture import Session
    from benchmark import Cancel
    real_socket = socket.socket
    class LoopbackSocket(real_socket):
        def bind(self, address):
            if address[0] != '127.0.0.1':
                raise AssertionError('Non-loopback bind prohibited')
            return super().bind(address)
        def sendto(self, data, *args):
            if args[-1][0] != '127.0.0.1':
                raise AssertionError('Non-loopback transmission prohibited')
            return super().sendto(data, *args)
    checks = []
    def reject(label, fn):
        try:
            fn()
        except (ValueError, FileNotFoundError):
            checks.append(dict(name=label, status='EXPECTED_REJECTION'))
        else:
            raise AssertionError('Accepted invalid handoff: ' + label)
    with patch.object(socket, 'socket', LoopbackSocket):
        Peer, engine = peer_class()
        with Peer(engine.root / 'ymw', sensor_size=(96, 32)) as peer:
            template = small_template(peer, out)
            tools = base.Tools(False); session = Session(tools, 'PL', template, sensor_size=(96, 32))
            try:
                snapshots = []; caches = []
                for condition in ('cold', 'warm'):
                    folder = out / condition
                    row, _, _ = session.run(folder, condition, 1, Cancel(out))
                    value = from_executor(session.client, base.read(folder / 'OFF.json'))
                    target = seal(value, out / (condition + '_handoff'), tools)
                    restored = restore(value['native'], target, tools)
                    self_context, _ = build_context(tools, restored)
                    base.check_result(tools, tools.algorithm.frozen_runtime.process(self_context), folder)
                    assert np.array_equal(restored['residual_n'], value['residual_n']) and np.array_equal(restored['valid'], value['valid'])
                    snapshots.append(value); caches.append(target)
                    checks.append(dict(name=condition + '_actual_strict_SDK_roundtrip_and_frozen_results', status='PASS', group=row['group'], session=row['session'], mask_commands=row['mask_commands']))
                assert len(peer.captured) == 18 and not peer.off_live
                first, second = snapshots
                reject('wrong_group_even_with_same_ROI', lambda: restore(second['native'], caches[0], tools))
                reject('missing_handoff', lambda: restore(first['native'], out / 'missing', tools))
                reject('wrong_quality_dtype', lambda: snapshot(first['native'], first['residual_n'], first['valid'].astype(np.uint8), 'bad'))
                reject('incomplete_live_group', lambda: from_executor(session.client, {'acknowledged': False}))
                bad_native = dict(first['native']); bad_native['gray'] = first['native']['gray'].copy(); bad_native['gray'][0, 0, 0] ^= 1
                reject('native_RAM_modified', lambda: restore(bad_native, caches[0], tools))
                for kind in ('data', 'producer', 'status', 'roi', 'array_digest'):
                    target = out / ('corrupt_' + kind); shutil.copytree(caches[0], target)
                    receipt = base.read(target / 'CACHE.json')
                    if kind == 'data':
                        p = target / 'intermediates.npz'; raw = p.read_bytes(); p.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                    else:
                        if kind == 'producer': receipt['producer_bindings'][next(iter(receipt['producer_bindings']))] = '0' * 64
                        if kind == 'status': receipt['status'] = 'PENDING'
                        if kind == 'roi': receipt['identity']['contract']['roi'][0] += 1
                        if kind == 'array_digest': receipt['array_sha256']['residual_n'] = '0' * 64
                        base.write(target / 'CACHE.json', receipt)
                    reject('corrupt_' + kind, lambda target=target: restore(first['native'], target, tools))
                handoff = restore(first['native'], caches[0], tools)
                bad = dict(handoff); bad['residual_n'] = handoff['residual_n'].copy(); bad['residual_n'][:] = 30000
                reject('selected_R32_residual_mismatch', lambda: build_context(tools, bad))
                # Warm reuse discarded the executor rows, but owned first-group
                # snapshots remain tied to their initial frames and unchanged.
                native_check(first['native'])
                assert digest(first['residual_n']) == base.read(caches[0] / 'CACHE.json')['array_sha256']['residual_n']
                checks.append(dict(name='warm_reset_does_not_alias_previous_group', status='PASS'))
            finally:
                session.close()
    base.verify_tool()
    base.write(out / 'SELFTEST.json', dict(status='PASS', checks=checks, physical_hardware=False,
               actual_board_commands=0, software_loopback_CAP=18, real_network_configuration_changed=False,
               scope='Qualified SDK and executor against loopback peer, not a physical board test'))
    print('PASS:', len(checks), 'checks; 18 loopback captures; 0 board commands', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True)
    run(p.parse_args().out)
