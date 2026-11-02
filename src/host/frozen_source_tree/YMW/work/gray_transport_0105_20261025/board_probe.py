"""Read-only STATUS_QUERY probe. Sends command 3 only, under the shared lock."""
import argparse,datetime,json,secrets,socket,struct,time
from pathlib import Path
import host_transport as wire

HERE=Path(__file__).resolve().parent
CORE_SHA='448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857'

def core_module():
    return wire.pinned_module('_gray_probe_core',HERE.parent/'auto_exposure_0105_20261015/app_core.py',CORE_SHA)

def probe(*,lab=Path('C:/BX72_0105_LAB'),board='192.168.0.2',bind='192.168.0.3',port=5000,timeout=1.5,interface_index=None):
    if not 0<timeout<=3:raise ValueError('Bounded query timeout required')
    core=core_module();engine=core.load_engine()
    protocol_path=engine.root/'ymw/host/protocol.py'
    protocol=wire.pinned_module('_gray_probe_protocol',protocol_path,core.digest(protocol_path))
    record=dict(schema='guangjian-readonly-status-v1',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        status='NO_REPLY',board=board,bind=bind,port=port,allowed_commands=[3],queries=[],
        captures_requested=0,configuration_commands_sent=0,bit_programmed=False,interface_index=interface_index,
        source_sha256={str(Path(__file__).resolve()):core.digest(__file__),str(protocol_path):core.digest(protocol_path)})
    with core.operator_lock(lab),socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        if interface_index is not None:
            if type(interface_index) is not int or not 0<interface_index<2**32:raise ValueError('Interface index')
            # Windows IP_UNICAST_IF affects this socket only; no route/VPN edits.
            sock.setsockopt(socket.IPPROTO_IP,31,struct.pack('!I',interface_index))
        sock.bind((bind,0));record['local_port']=sock.getsockname()[1]
        first=secrets.randbelow(65535)
        for seq in (first,first+1):
            packet=protocol.command(3,seq);sock.sendto(packet,(board,port))
            row=dict(seq=seq,request_hex=packet.hex(),responses=[]);record['queries'].append(row)
            deadline=time.monotonic()+timeout;ack=status=None
            while time.monotonic()<deadline:
                sock.settimeout(max(.001,deadline-time.monotonic()))
                try:data,peer=sock.recvfrom(65535)
                except socket.timeout:break
                if peer!=(board,port):continue
                try:item=protocol.control(data)
                except ValueError:continue
                if item.get('seq')!=seq:continue
                row['responses'].append(dict(packet_hex=data.hex(),decoded=item))
                if item['type']==protocol.ACK and item['original']==3:ack=item
                elif item['type']==protocol.STATUS:status=item
                if ack is not None and status is not None:break
            row.update(ack=ack,status=status)
            if ack is None or ack['result'] or status is None:break
        if len(record['queries'])==2 and all(r['ack'] and r['ack']['result']==0 and r['status'] for r in record['queries']):
            record['status']='STATUS_CONFIRMED'
            record['firmware_hex']=f"0x{record['queries'][-1]['status']['firmware']:04x}"
            record['busy']=bool(record['queries'][-1]['status']['state']&3)
            record['ready']=bool(record['queries'][-1]['status']['state']&16)
    return record

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--interface-index',type=int);args=p.parse_args()
    if args.out.exists():raise ValueError('Use a new evidence file')
    record=probe(interface_index=args.interface_index);args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as f:json.dump(record,f,indent=2);f.write('\n')
    print(json.dumps(record,indent=2))
    if record['status']!='STATUS_CONFIRMED':raise SystemExit(2)

if __name__=='__main__':main()
