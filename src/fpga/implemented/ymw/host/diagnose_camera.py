"""Read status, test a small generated image, then try two camera frames.
No firmware, lights, VPN, firewall or network settings are changed.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import zipfile

from udp_client import CameraClient, EXPECTED_BIT_SHA256
from protocol import CAPTURE, FRAME_DATA, STATUS, STATUS_QUERY, FrameReceiver, control, parse_frame, save_png


SOURCE_REASONS = {0:'none', 1:'no completed camera frame published within source timeout',
                  2:'DDR read FIFO could not fill one packet within source timeout',
                  3:'invalid packet index transition', 4:'invalid DDR source state'}


def decoded_status(value):
    result = dict(value)
    state, error = value['state'], value['error']
    reason = (error >> 8) & 7
    result['decoded'] = {
        'frame_busy': bool(state & 1), 'light_busy': bool(state & 2),
        'camera_config_and_ddr_ready': bool(state & 16),
        'ddr_source_failed': bool(state & 32),
        'packet_id_mod1024': state >> 6,
        'source_reason_code': reason, 'source_reason': SOURCE_REASONS.get(reason,'unknown'),
        'legacy_error': error & 255,
    }
    return result


def status(client):
    ack, _, value = client.transact(STATUS_QUERY)
    if ack['result']:
        raise RuntimeError(f'Status ACK rejected: {ack}')
    deadline = time.monotonic() + 1
    while value is None:
        data = client.receive(deadline)
        try:
            reply = control(data)
        except ValueError:
            continue
        if reply['type'] == STATUS and reply['seq'] == client.seq:
            value = reply
    return decoded_status(value)


def attempt(client, out, name, source, width, height, wait=8):
    result = {'name':name,'source':source,'width':width,'height':height,
              'datagrams_from_board':0,'frame_datagrams':0,'valid_frame_datagrams':0,
              'wrong_frame_id_packets':0,'parse_errors':0,'samples':[],
              'status':'RUNNING'}
    started = time.monotonic()
    try:
        ack, buffered, _ = client.transact(CAPTURE,(source,width,height,0))
        result['ack'] = ack
        if ack['result']:
            raise RuntimeError(f'Capture rejected: {ack}')
        fid = ack['frame_id']
        receiver = FrameReceiver(wait,max_bytes=width*height*2)
        deadline = time.monotonic()+wait
        while True:
            try:
                data = buffered.pop(0) if buffered else client.receive(deadline)
            except TimeoutError:
                result['unique_packets'] = len(receiver.parts)
                result['expected_packets'] = (width*height*2+1379)//1380
                result['first_missing_packet_ids'] = receiver.missing()[:24]
                raise TimeoutError(f"Incomplete: {len(receiver.parts)}/{result['expected_packets']} packets")
            result['datagrams_from_board'] += 1
            if len(data)<6 or data[5]!=FRAME_DATA:
                continue
            result['frame_datagrams'] += 1
            try:
                frame,pid,count,w,h,_ = parse_frame(data)
            except ValueError as exc:
                result['parse_errors'] += 1
                if len(result['samples'])<8:
                    result['samples'].append({'error':str(exc),'length':len(data),'header_hex':data[:32].hex()})
                continue
            result['valid_frame_datagrams'] += 1
            if frame!=fid:
                result['wrong_frame_id_packets'] += 1
                if len(result['samples'])<8:
                    result['samples'].append({'expected_frame':fid,'received_frame':frame,'packet_id':pid})
                continue
            if (w,h)!=(width,height):
                raise RuntimeError(f'Unexpected size {w}x{h}')
            raw = receiver.add(data,fid)
            if raw is not None:
                (out/(name+'.rgb565')).write_bytes(raw)
                save_png(out/(name+'.png'),raw,width,height)
                result.update(status='PASS',unique_packets=len(receiver.parts),
                              bytes=len(raw),sha256_rgb565=hashlib.sha256(raw).hexdigest())
                break
    except Exception as exc:
        result.update(status='FAIL',error=f'{type(exc).__name__}: {exc}')
    result['elapsed_s'] = round(time.monotonic()-started,3)
    try:
        result['status_after'] = status(client)
    except Exception as exc:
        result['status_after_error'] = str(exc)
    return result


def run(args):
    root = Path(__file__).resolve().parents[1]/'results'
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = root/f'BX72_CAMERA_DIAG_{stamp}_{uuid.uuid4().hex[:6]}'
    out.mkdir(parents=True)
    report = {'started_at':datetime.now().astimezone().isoformat(),
              'candidate_bit_sha256':EXPECTED_BIT_SHA256,
              'bit_hash_note':'local package hash, not FPGA readback',
              'bind_ip':args.bind,'board_ip':args.board,'port':args.port,
              'light_control':'not changed by this diagnostic',
              'diagnostic_tool':'stdlib-v2; no NumPy, Pillow or GUI imports',
              'test_label':getattr(args,'label','current_bit'),
              'expected_firmware':getattr(args,'expected_firmware',None),
              'tests':[],'status':'RUNNING'}
    client = None
    def record():
        (out/'diagnostic.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    record()
    try:
        client = CameraClient(args.bind,args.board,args.port,threading.Event())
        report['status_before'] = status(client)
        firmware = report['status_before']['firmware']
        if firmware == 257:
            report['candidate_bit_sha256'] = '0A8C7CBE9F12A8CC9EB726EFC59838195599C8FA6D2996D8D7AEEA54B417E32F'
        report['bit_hash_note'] = 'reference build associated with version; NOT FPGA bit hash readback'
        record()
        print('Initial board status:',json.dumps(report['status_before'],ensure_ascii=True))
        expected = getattr(args,'expected_firmware',None)
        if expected is not None and firmware != expected:
            raise RuntimeError(f'Board firmware {firmware}; this comparison requires {expected}. Program the correct bit first.')
        # Generated pattern bypasses DVP/DDR, distinguishing bulk UDP from camera failures.
        for name,source,width,height in [('pattern_320x240',0,320,240),
                                         ('camera_attempt_1',2,1920,1080),
                                         ('camera_attempt_2',2,1920,1080)]:
            print('Testing',name,flush=True)
            item = attempt(client,out,name,source,width,height)
            report['tests'].append(item);record()
            print(item['status'],item.get('error','complete'),flush=True)
            if 'status_after' in item:
                print('Decoded status:',json.dumps(item['status_after']['decoded']),flush=True)
            time.sleep(.3)
        report['status'] = 'PASS' if all(x['status']=='PASS' for x in report['tests']) else 'FAIL'
    except Exception as exc:
        report.update(status='FAIL',error=f'{type(exc).__name__}: {exc}')
        print(report['error'])
    finally:
        if client:client.close()
        report['finished_at'] = datetime.now().astimezone().isoformat();record()
        archive = out.with_suffix('.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for path in out.iterdir():
                if path.is_file():z.write(path,out.name+'/'+path.name)
        print('RESULT:',report['status'])
        print('ZIP TO SEND:',archive)
    return out,report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind',default='192.168.0.3')
    parser.add_argument('--board',default='192.168.0.2')
    parser.add_argument('--port',type=int,default=5000)
    parser.add_argument('--expected-firmware',type=int)
    parser.add_argument('--label',default='current_bit')
    args = parser.parse_args()
    run(args)


if __name__=='__main__':main()
