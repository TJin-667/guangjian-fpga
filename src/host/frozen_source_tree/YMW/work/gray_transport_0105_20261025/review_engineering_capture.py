"""Offline re-review of actual archived transport bytes; never open a socket."""
import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import host_transport as wire


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def crc64(raw):
    mask = (1 << 64) - 1
    table = []
    for value in range(256):
        item = value << 56
        for _ in range(8):
            item = ((item << 1) ^ (0x42f0e1eba9ea3693 if item >> 63 else 0)) & mask
        table.append(item)
    result = 0
    for value in raw:
        result = ((result << 8) & mask) ^ table[(result >> 56) ^ value]
    return result


def planes(raw, width, height, fmt):
    count = width * height
    if fmt == 1:
        require(len(raw) == count * 2, 'RGB length')
        words = np.frombuffer(raw, dtype='>u2').astype(np.uint32)
        red, green, blue = (words >> 11) & 31, (words >> 5) & 63, words & 31
        r8, g8, b8 = (red << 3) | (red >> 2), (green << 2) | (green >> 4), (blue << 3) | (blue >> 2)
        gray = ((9798*r8 + 19235*g8 + 3735*b8 + 16384) >> 15).astype(np.uint8)
        sat = (red == 31) | (green == 63) | (blue == 31)
    else:
        require(fmt == 49 and len(raw) == count + math.ceil(count / 8), 'GRAY/SAT length')
        groups, tail = divmod(count, 8)
        block = np.frombuffer(raw[:groups*9], dtype=np.uint8).reshape(groups, 9)
        gray = np.empty(count, dtype=np.uint8)
        sat = np.empty(count, dtype=np.bool_)
        gray[:groups*8] = block[:, :8].reshape(-1)
        sat[:groups*8] = np.unpackbits(block[:, 8].copy(), bitorder='big')
        if tail:
            gray[groups*8:] = np.frombuffer(raw[groups*9:groups*9+tail], dtype=np.uint8)
            final = raw[-1]
            require(final & ((1 << (8-tail))-1) == 0, 'Nonzero SAT tail padding')
            sat[groups*8:] = [(final >> (7-i)) & 1 for i in range(tail)]
    return gray.reshape(height,width), sat.reshape(height,width)


def h1_h2(gray, sat, mask):
    g = gray.astype(np.int64)
    padded = np.pad(g, 4, mode='reflect')
    summed = np.zeros_like(g)
    for y in range(9):
        for x in range(9):
            summed += padded[y:y+g.shape[0], x:x+g.shape[1]]
    residual = 81*g - summed
    statistics = dict(pixel_count=g.size, gray_sum=int(g.sum()), near_black=int((g<=5).sum()),
        near_white=int((g>=250).sum()), rgb_any_max=int(sat.sum()), board_count=int(mask.sum()),
        board_gray_sum=int(g[mask].sum()), board_dark=int(((g<=10)&mask).sum()),
        board_white=int(((g>=250)&mask).sum()), board_rgb_any_max=int((sat&mask).sum()))
    features = dict(strong_count=int((np.abs(residual)>1620).sum()), weak_count=int((np.abs(residual)>648).sum()),
                    sum9_total=int(summed.sum()), residual_n_total=int(residual.sum()))
    return statistics, features


def review(run):
    run = Path(run).resolve()
    plan = json.loads((run/'engineering_plan.json').read_bytes())
    summary = json.loads((run/'operator_summary.json').read_bytes())
    require(summary['status']=='ENGINEERING_TRANSPORT_VERIFIED' and summary['evidence_source']=='real_board', 'Not a passed real-board run')
    require(summary['captures_verified']==2 and not summary['source_changed'] and summary['error'] is None, 'Incomplete/changed run')
    require(not summary['training_data'] and not summary['same_frozen_input'] and not summary['release_ready'], 'Qualification scope changed')
    for source,digest in plan['source_sha256'].items():
        require(sha(Path(source))==digest, 'Executable/bit/handshake source changed: '+source)
    inventory = json.loads((run/'output_manifest.json').read_bytes())['files']
    for name,digest in inventory.items():
        path=(run/name).resolve()
        require(path.is_relative_to(run) and sha(path)==digest, 'Directory inventory changed: '+name)
    archive=run.with_name(run.name+'.zip')
    receipt=json.loads(run.with_name(run.name+'.zip.receipt.json').read_bytes())
    require(sha(archive)==receipt['archive_sha256'] and archive.stat().st_size==receipt['archive_bytes'], 'ZIP SHA/size')
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist())==len(set(z.namelist())) and set(z.namelist())==set(inventory)|{'output_manifest.json'}, 'ZIP inventory')
        for name,digest in inventory.items():
            require(hashlib.sha256(z.read(name)).hexdigest()==digest and z.read(name)==(run/name).read_bytes(), 'ZIP member differs: '+name)
        require(z.read('output_manifest.json')==(run/'output_manifest.json').read_bytes(), 'ZIP manifest differs')
    rows=[]
    for fmt in (1,49):
        paths=list((run/f'format_{fmt:02x}').glob('*/committed/result.json'))
        require(len(paths)==1,'One committed frame per format required')
        record=json.loads(paths[0].read_bytes()); folder=paths[0].parent
        require(record['status']=='COMMITTED' and record['strict_verified'] and record['evidence_source']=='real_board', 'Provisional frame')
        for name,digest in record['archived_file_sha256'].items():
            require(Path(name).name==name and sha(folder/name)==digest, 'Frame artifact changed: '+name)
        meta=wire.decode_metadata((folder/'metadata_packet.bin').read_bytes(),record['metadata_query_seq'])
        require(meta==record['diagnostic'] and meta['pixel_format']==fmt and meta['roi']==plan['roi'] and meta['parameters']==plan['parameters'], 'Metadata context changed')
        require(meta['valid'] and meta['mask_valid'] and meta['parameters_valid'] and not meta['error'], 'Invalid final metadata')
        raw=(folder/record['raw_payload_file']).read_bytes(); width,height=plan['roi'][2:]
        require(crc64(raw)==meta['payload_crc64'] and len(raw)==meta['payload_bytes'], 'Independent CRC/length')
        gray,sat=planes(raw,width,height,fmt)
        mask=np.frombuffer((folder/'board_mask.bin').read_bytes(),dtype=np.uint8).reshape(height,width).astype(bool)
        require(mask.all(), 'Diagnostic mask must remain all ones')
        statistics,features=h1_h2(gray,sat,mask)
        require(statistics==meta['statistics'] and features==meta['features'], 'Independent H1/H2 differ')
        require((folder/'image.gray8').read_bytes()==gray.tobytes(), 'Saved gray differs')
        require((folder/'image.sat1').read_bytes()==np.packbits(sat.reshape(-1),bitorder='big').tobytes(), 'Saved SAT differs')
        count=math.ceil(len(raw)/1380)
        require(record['complete_packets']==record['expected_packets']==count, 'Packet count')
        require(meta['fifo_reads']==math.prod(plan['sensor_size']), 'Incomplete DDR drain')
        cost=record['cost']
        require(cost['capture_requests']==cost['capture_command_transmissions']==cost['saved_images']==1, 'Unexpected capture budget')
        require(all(cost[k]==0 for k in ['command_retries','missing_image_packets','duplicate_image_packets','foreign_packets','failed_calls']), 'Transport anomaly')
        cleanup=list((run/f'format_{fmt:02x}').glob('cleanup_*/outcome.json'))
        require(len(cleanup)==1,'Missing cleanup record')
        off=json.loads(cleanup[0].read_bytes())
        require(off['requested'] and off['acknowledged'] and off['ack']['result']==0 and off['ack']['original']==1, 'OFF not acknowledged')
        events=[json.loads(line) for line in (cleanup[0].parent/'frame_trace.jsonl').read_text().splitlines()]
        commands=[e for e in events if e['event']=='command']
        require(len(commands)==1 and commands[0]['kind']==1 and commands[0]['args']==[0,0,0,0] and commands[0]['ack']==off['ack'], 'OFF trace mismatch')
        matching=[r for r in summary['rows'] if r['pixel_format']==fmt]
        require(len(matching)==1 and matching[0]['payload_sha256']==sha(folder/record['raw_payload_file']) and matching[0]['identity']==meta['identity'], 'Summary differs from frame')
        rows.append(dict(pixel_format=fmt,payload_bytes=len(raw),packets=count,payload_sha256=sha(folder/record['raw_payload_file']),
            payload_crc64=meta['payload_crc64'],identity=meta['identity'],bank=meta['bank'],statistics=statistics,features=features,
            fifo_reads=meta['fifo_reads'],command_retries=0,missing_packets=0,OFF_acknowledged=True))
    require(rows[0]['identity']['session']!=rows[1]['identity']['session'],'Fresh sessions required')
    for key,bits in [('dvp_sequence',32),('publish_sequence',32),('frame_id',16)]:
        delta=(rows[1]['identity'][key]-rows[0]['identity'][key])%(1<<bits)
        require(0<delta<1<<(bits-1),'Nonforward '+key)
    return dict(schema='guangjian-real-dual-format-transport-review-v1',status='PASS',
        source_run=str(run),reviewer_sha256=sha(Path(__file__)),rows=rows,inventory_files=len(inventory),
        archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,
        independent_CRC_gray_SAT_H1_H2_recomputed=True,gray_payload_hardware_verified=True,
        all_OFF_acknowledged=True,real_capture_requests=2,roi=plan['roi'],
        saturation_nonzero_exercised=any(row['statistics']['rgb_any_max']>0 for row in rows),
        near_black_exercised=any(row['statistics']['near_black']>0 for row in rows),
        near_white_exercised=any(row['statistics']['near_white']>0 for row in rows),
        partial_SAT_tail_exercised=(plan['roi'][2]*plan['roi'][3])%8!=0,
        same_frozen_input=False,pixelwise_cross_format_equivalence=False,training_data=False,
        optical_quality_evaluated=False,physical_OFF_measured=False,external_IO_qualified=False,release_ready=False,
        operator_timed_phase_s=summary['host_check_elapsed_s'],
        timed_phase_through_archive_ms=receipt['host_elapsed_ms_through_archive'],
        timing_scope='operator timer excludes startup and source preflight',assistant_sent_new_hardware_commands=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();require(not args.out.exists(),'Use a new review receipt')
    result=review(args.run);args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_bytes((json.dumps(result,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({k:result[k] for k in ['status','roi','real_capture_requests','gray_payload_hardware_verified','archive_sha256','saturation_nonzero_exercised']},indent=2))
