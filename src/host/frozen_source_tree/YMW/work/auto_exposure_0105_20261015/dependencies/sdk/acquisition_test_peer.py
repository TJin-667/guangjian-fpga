"""Fault-injected *software* UDP peer and unmodified RTL-packet replay.

This models the inspected command contracts, never physical MIG/SCCB/LEDs.
The executor still talks through actual sockets and the pinned wire-v1 codec.
"""
from __future__ import annotations

import copy
import csv
import heapq
import json
from pathlib import Path
import socket
import struct
import threading
import time

import numpy as np

import identity_diag as diag
from acquisition_support import load_protocol, sha_file
from run_xdl_revision2 import synthetic_arrays, stats


def envelope(kind, seq, payload):
    return struct.pack("!4sBBHH", b"LGHT", 1, kind, seq, len(payload)) + payload


def encode_metadata(seq, meta):
    t = meta["identity"]
    p = meta["parameters"]
    flags = int(meta["valid"]) | (int(t["session"] != 0) << 1) | (int(meta["parameters_valid"]) << 2) | (int(meta["mask_valid"]) << 3)
    tag = struct.pack("!Q4I4H", *(t[k] for k in ("session", "request_id", "config_epoch", "dvp_sequence", "publish_sequence", "roi_generation", "camera_generation", "light_generation", "frame_id")))
    payload = (bytes((1, flags, meta["error"], 0)) + struct.pack("!HH", 0x0105, t["frame_id"]) + tag + bytes((meta["bank"], 0)) +
               struct.pack("!HH4B", *(p[k] for k in ("exposure_lines", "gain16", "light_mask", "brightness", "settle_frames", "discard_frames"))) +
               struct.pack("!4H", *meta["roi"]) + struct.pack("!10I", *(meta["statistics"][k] for k in diag.H1_KEYS)) +
               struct.pack("!2B5I", meta["wait_complete_frames"], meta["discard_complete_frames"], meta["stale_drops"], meta["fifo_reads"], meta["request_counter"], meta["features"]["strong_count"], meta["features"]["weak_count"]) +
               struct.pack("!QqQ", meta["features"]["sum9_total"], meta["features"]["residual_n_total"], meta["rgb_crc64"]) + bytes(16))
    if len(payload) != 160:
        raise ValueError("peer metadata layout")
    return envelope(0x85, seq, payload)


def rtl_fixture(work, ymw_root, index=0):
    """Extract exact image packets/sidecar/readback from real XSim output."""
    work = Path(work)
    v1 = load_protocol(ymw_root)
    rows = list(csv.DictReader((work/"packets_index.csv").open()))
    blob = (work/"packets.bin").read_bytes()
    offset = 0
    images = {}
    cameras = []
    rois = []
    completed = []
    for row in rows:
        length = int(row["length"])
        packet = blob[offset:offset+length]
        offset += length
        if len(packet) != length:
            raise ValueError("truncated RTL packet artifact")
        if packet[5] == 0x90:
            fid, *_ = v1.parse_frame(packet)
            images.setdefault(fid, []).append(packet)
        elif packet[5] == 0x83:
            cameras.append(packet)
        elif packet[5] == 0x84:
            rois.append(packet)
        elif packet[5] == 0x85:
            meta = diag.decode(packet)
            if meta["valid"]:
                completed.append(dict(metadata_packet=packet, metadata=meta, image_packets=images[meta["identity"]["frame_id"]]))
    if offset != len(blob) or len(completed) != 4:
        raise ValueError("incomplete RTL packet fixture")
    chosen = completed[index]
    cam_gen = chosen["metadata"]["identity"]["camera_generation"]
    chosen["camera_packet"] = next(p for p in cameras if v1.control(p)["generation"] == cam_gen and v1.control(p)["locked"])
    chosen["inputs_sha256"] = {str(work/n):sha_file(work/n) for n in ("packets.bin", "packets_index.csv", "packet_audit.json", "board_receipt.csv", "board_trace.jsonl")}
    return chosen


class UdpPeer:
    def __init__(self, ymw_root, *, fault="", firmware=0x0105, sensor_size=(32,32), fixture=None):
        self.v1 = load_protocol(ymw_root)
        self.fault = fault
        self.firmware = firmware
        self.sensor_size = tuple(sensor_size)
        self.fixture = fixture
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(.002)
        self.endpoint = self.sock.getsockname()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.tasks = []
        self._order = 0
        self.errors = []
        self.received = []
        self.capture_event = threading.Event()
        self.commands = 0
        self.camera_executions = 0
        self.camera_generation = self.roi_generation = self.light_generation = self.config_epoch = 0
        self.session = self.counter = self.dvp = self.pub = 0
        self.fid = 65534 if fault == "frame_wrap" else 10
        self.exp = 600
        self.gain = 16
        self.mask = 1
        self.brightness = 128
        self.wait, self.discard = 1, 3
        self.roi = [0,0,*self.sensor_size]
        self.busy = False
        self.mask_valid = False
        self.mask_words = {}
        self.mask_domain = None
        self.cache = {}
        self._dropped_once = False
        self._meta_valid_queries = 0
        self.last = self._empty_meta()
        self.last_raw = None
        self.thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(3)
        self.sock.close()
        if self.thread.is_alive() or self.errors:
            raise RuntimeError("peer failed: " + repr(self.errors))

    def _empty_meta(self):
        return dict(valid=False, parameters_valid=False, mask_valid=False, bank=0, error=0,
                    identity=dict(session=0,request_id=0,config_epoch=0,dvp_sequence=0,publish_sequence=0,roi_generation=0,camera_generation=0,light_generation=0,frame_id=0),
                    parameters=dict(exposure_lines=0,gain16=0,light_mask=0,brightness=0,settle_frames=1,discard_frames=3),
                    roi=[0,0,*self.sensor_size], statistics=dict.fromkeys(diag.H1_KEYS,0), wait_complete_frames=0,discard_complete_frames=0,
                    stale_drops=0,fifo_reads=0,request_counter=0,features=dict(strong_count=0,weak_count=0,sum9_total=0,residual_n_total=0),rgb_crc64=0)

    def _send(self, data, peer, delay=0., token=None, callback=None):
        self._order += 1
        heapq.heappush(self.tasks, (time.monotonic()+delay,self._order,data,peer,token,callback))

    def _run(self):
        try:
            while not self.stop.is_set():
                now = time.monotonic()
                while self.tasks and self.tasks[0][0] <= now:
                    _,_,data,peer,token,callback = heapq.heappop(self.tasks)
                    if token is not None and token != (self.session,self.counter):
                        continue
                    if callback is not None:
                        callback()
                    if data is not None:
                        self.sock.sendto(data,peer)
                try:
                    data,peer = self.sock.recvfrom(65535)
                except socket.timeout:
                    continue
                self._handle(data,peer)
        except BaseException as exc:
            self.errors.append(repr(exc))

    def _ack(self, kind, seq, result=0, fid=None):
        return envelope(0x81,seq,struct.pack("!BB4H",kind,result,self.fid if fid is None else fid,int(self.busy),255 if self.firmware==0x0105 else 127,0))

    def _camera(self, seq):
        if self.fixture is not None:
            data = bytearray(self.fixture["camera_packet"])
            data[6:8] = seq.to_bytes(2,"big")
            return bytes(data)
        exposure = (self.exp+1 if self.fault=="readback" else self.exp)*16
        raw = bytes((3,(exposure>>16)&15,(exposure>>8)&255,exposure&255,(self.gain>>8)&3,self.gain&255,9,196,4,96,0,0,0x56,0x40))
        return envelope(0x83,seq,bytes((1,1,0,0))+raw+self.camera_generation.to_bytes(2,"big")+bytes(2))

    def _roi(self, seq):
        x,y,w,h = self.roi
        pixels = w*h
        packets = (pixels+689)//690
        return envelope(0x84,seq,struct.pack("!BB7HIBB",1,int(self.roi_generation!=0),x,y,w,h,packets,pixels-(packets-1)*690,self.roi_generation,pixels,0,0))

    def _reply_pair(self, kind, seq, peer, extra, delay=0.):
        ack = self._ack(kind,seq)
        packets = [extra,ack] if self.fault == "status_first" else [ack,extra]
        if self.fault == "missing_status" and kind == 4:
            packets = [ack]
        if self.fault == "drop_ack_once" and kind == 4 and not self._dropped_once:
            self._dropped_once = True
            packets = [extra]
        if self.fault == "drop_capture_ack" and kind == 2:
            packets = []
        for packet in packets:
            self._send(packet,peer,delay)

    def _handle(self, data, peer):
        if len(data)!=20 or data[:6]!=b"LGHT\x01"+data[5:6] or data[8:12]!=b"\0\x0a\0\0":
            raise ValueError("peer received malformed command")
        kind,seq = data[5],int.from_bytes(data[6:8],"big")
        args = int.from_bytes(data[12:],"big")
        values = struct.unpack("!4H",data[12:])
        self.commands += 1
        self.received.append(dict(kind=kind,seq=seq,args=args,request_hex=data.hex(),host_monotonic_ns=time.monotonic_ns()))
        if kind == 3:
            state = 16|8|int(self.busy)|(32 if self.last["error"] else 0)
            status = envelope(0x82,seq,struct.pack("!5H3I",0,self.firmware,127,state,0,self.commands,self.counter,0))
            self._reply_pair(kind,seq,peer,status)
        elif kind == 8:
            if self.busy:
                self._send(self._ack(kind,seq,3),peer)
            elif args == 0:
                self._send(self._ack(kind,seq,2),peer)
            else:
                if self.session != args:
                    self.session,self.counter = args,0
                    self.cache.clear()
                    self.last["valid"] = False
                self._send(self._ack(kind,seq),peer)
        elif kind in (4,5):
            key = (kind,seq)
            if kind == 4 and key not in self.cache:
                self.exp,self.gain = values[:2]
                self.camera_generation = (self.camera_generation+1)&65535
                self.config_epoch += 1
                self.camera_executions += 1
                self.cache[key] = args
            delay = .12 if self.fault == "slow_execution" and kind == 4 else 0
            self._reply_pair(kind,seq,peer,self._camera(seq),delay)
        elif kind == 1:
            self.mask,self.brightness = values[:2]
            self.light_generation = (self.light_generation+1)&65535
            self.config_epoch += 1
            self._send(self._ack(kind,seq),peer)
        elif kind in (6,7):
            if kind == 6 and (kind,seq) not in self.cache:
                self.roi = list(values)
                self.roi_generation = (self.roi_generation+1)&65535
                self.cache[(kind,seq)] = args
            if self.fault == "roi_changed_after" and kind == 7 and self.counter:
                self.roi_generation += 1
            self._reply_pair(kind,seq,peer,self._roi(seq))
        elif kind == 12:
            self.wait,self.discard = values[:2]
            self._send(self._ack(kind,seq),peer)
        elif kind == 10:
            address,bits = args>>32,args&0xffffffff
            if address == 0:
                self.mask_words.clear()
            self.mask_words[address] = bits
            self.mask_valid = False
            self._send(self._ack(kind,seq,2 if self.fault=="mask_ack_error" else 0),peer)
        elif kind == 11:
            width,height,generation,crc = values
            import binascii
            blob = b"".join(self.mask_words[k].to_bytes(4,"big") for k in sorted(self.mask_words))
            ok = len(self.mask_words)==(width*height+31)//32 and binascii.crc_hqx(blob,0xffff)==crc
            self.mask_valid = ok
            self.mask_domain = (width,height,generation)
            self._send(self._ack(kind,seq,0 if ok else 2),peer)
        elif kind == 2:
            if (kind,seq) in self.cache:
                if self.fault != "drop_capture_ack":
                    self._send(self._ack(kind,seq,fid=self.cache[(kind,seq)]),peer)
                return
            self.counter += 1
            self.fid = self.fixture["metadata"]["identity"]["frame_id"] if self.fixture is not None else (self.fid+1)&65535
            self.busy = True
            self.capture_event.set()
            self.cache[(kind,seq)] = self.fid
            if self.fault not in ("drop_capture_ack","drop_capture_once") or self._dropped_once:
                self.sock.sendto(self._ack(kind,seq),peer)
            elif self.fault == "drop_capture_once":
                self._dropped_once=True
            self._start_capture(peer,values)
        elif kind == 9:
            meta = copy.deepcopy(self.last)
            meta["request_counter"] = self.counter
            if self.fault == "counter_exhausted" and not self.counter and self.camera_generation:
                meta["request_counter"] = 0xffffffff
            if self.counter:
                self._mutate_metadata(meta)
            packet = encode_metadata(seq,meta)
            if self.fixture is not None and meta["valid"]:
                packet = bytearray(self.fixture["metadata_packet"])
                packet[6:8] = seq.to_bytes(2,"big")
                packet = bytes(packet)
            if self.fault == "unknown_schema" and self.counter:
                packet = packet[:10]+b"\x02"+packet[11:]
            if self.fault == "wrong_query_seq" and self.counter:
                packet = packet[:6]+((seq-1)&65535).to_bytes(2,"big")+packet[8:]
            if self.fault == "late_query" and self.counter and not self._dropped_once:
                self._dropped_once=True
                old = bytearray(packet)
                old[6:8] = ((seq-1)&65535).to_bytes(2,"big")
                self._send(bytes(old),peer)
            self._send(packet,peer)
        elif kind == 13:
            if self.fault == "unknown_retirement":
                return
            if not self.busy or args>>32!=self.counter:
                self._send(self._ack(kind,seq,2),peer)
            else:
                self.busy=False
                self.last["valid"]=False
                self.last["error"]=3
                self.tasks = [t for t in self.tasks if t[4] is None]
                heapq.heapify(self.tasks)
                self._send(self._ack(kind,seq),peer)
                if self.fault == "cancel_late_image" and self.last_raw:
                    x,y,w,h = self.last["roi"]
                    for packet in self.v1.frame_packets(self.last_raw,w,h,self.fid):
                        self._send(packet,peer,.01)
        else:
            self._send(self._ack(kind,seq,3),peer)

    def _start_capture(self, peer, args):
        x,y,w,h = self.roi if args[0]==3 else [0,0,*self.sensor_size]
        generation = self.roi_generation if args[0]==3 else 0
        t = dict(session=self.session,request_id=self.counter,config_epoch=self.config_epoch,dvp_sequence=0,publish_sequence=0,
                 roi_generation=generation,camera_generation=self.camera_generation,light_generation=self.light_generation,frame_id=self.fid)
        p = dict(exposure_lines=self.exp,gain16=self.gain,light_mask=self.mask,brightness=self.brightness,settle_frames=self.wait,discard_frames=self.discard)
        self.last = self._empty_meta()
        self.last.update(identity=t,parameters=p,roi=[x,y,w,h],request_counter=self.counter)
        self._meta_valid_queries = 0
        if self.fixture is not None:
            meta = copy.deepcopy(self.fixture["metadata"])
            if self.counter!=meta["identity"]["request_id"] or self.session!=meta["identity"]["session"]:
                raise ValueError("RTL fixture session/request must not be rewritten")
            self.fid = meta["identity"]["frame_id"]
            packets = list(self.fixture["image_packets"])
            receiver = self.v1.FrameReceiver()
            raw=None
            for packet in packets:
                finished=receiver.add(packet,self.fid,now=0)
                if finished is not None:raw=finished
        else:
            values = ((np.arange(w*h,dtype=np.uint32)*13)^(self.counter*271)^(self.exp*7)^(self.mask*123)).astype(np.uint16).reshape(h,w)
            raw = values.astype(">u2").tobytes()
            mask = np.array([(self.mask_words.get(i//32,0)>>(31-i%32))&1 for i in range(w*h)],dtype=np.uint8).reshape(h,w)
            arr = synthetic_arrays(values,mask)
            s = stats(arr["gray"],mask,arr["rgb_any_max"])
            self.dvp += self.wait+self.discard+1
            self.pub += 1
            t.update(dvp_sequence=self.dvp,publish_sequence=self.pub)
            residual = np.abs(arr["residual_n"].astype(np.int32))
            meta = copy.deepcopy(self.last)
            meta.update(valid=True,parameters_valid=True,mask_valid=self.mask_valid and self.mask_domain==(w,h,generation),
                        identity=t,bank=(self.pub-1)&1,statistics=dict(zip(diag.H1_KEYS,s)),fifo_reads=self.sensor_size[0]*self.sensor_size[1],
                        wait_complete_frames=self.wait,discard_complete_frames=self.discard,
                        features=dict(strong_count=int((residual>1620).sum()),weak_count=int((residual>648).sum()),sum9_total=int(arr["sum9"].sum(dtype=np.uint64)),residual_n_total=int(arr["residual_n"].sum(dtype=np.int64))),rgb_crc64=diag.crc64_ecma(raw))
            packets = list(self.v1.frame_packets(raw,w,h,self.fid))
        self.last_raw = raw
        self.last["identity"] = dict(meta["identity"])
        self.last["parameters_valid"] = True
        self.last["mask_valid"] = meta["mask_valid"]
        self.last["bank"] = meta["bank"]
        token = (self.session,self.counter)
        delay = .22 if self.fault in ("cancel","cancel_late_image","unknown_retirement","timeout_recovery","slow_capture") else .05
        if self.fault == "reset":
            self._send(None,peer,.008,callback=self._reset)
        if self.fault == "unknown_retirement":
            return
        if self.fault == "old_image":
            raw = bytes((raw[0]^1,))+raw[1:]
            packets = list(self.v1.frame_packets(raw,w,h,self.fid))
        if self.fault == "out_of_order":
            packets.reverse()
        if self.fault == "duplicate":
            packets = packets[:1]+packets
        if self.fault == "conflict":
            bad = bytearray(packets[0]);bad[-1]^=1
            packets = [packets[0],bytes(bad)]+packets[1:]
        if self.fault in ("missing_packet","timeout_recovery"):
            packets=packets[:-1]
        if self.fault == "truncated_image":
            packets[0]=packets[0][:-1]
        if self.fault == "stale_image":
            stale = list(self.v1.frame_packets(raw,w,h,(self.fid-1)&65535))
            packets=stale+packets
        if self.fault == "foreign_source":
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as foreign:
                foreign.sendto(packets[0],peer)
        for i,packet in enumerate(packets):
            self._send(packet,peer,delay+i*.00002,token)
        def publish():
            self.last=meta
            self.busy=False
        self._send(None,peer,delay+len(packets)*.00002+.001,token,publish)

    def _reset(self):
        self.session=self.counter=self.config_epoch=self.camera_generation=self.light_generation=self.roi_generation=0
        self.mask_valid=self.busy=False
        self.cache.clear()
        self.last=self._empty_meta()

    def _mutate_metadata(self, meta):
        field = {"wrong_session":"session","wrong_request":"request_id","wrong_config":"config_epoch","wrong_roi":"roi_generation","wrong_camera_generation":"camera_generation","wrong_light_generation":"light_generation","wrong_fid":"frame_id","wrong_dvp":"dvp_sequence","wrong_pub":"publish_sequence"}.get(self.fault)
        if field:
            if self.fault in ("wrong_config","wrong_light_generation","wrong_dvp","wrong_pub") and not meta["valid"]:
                return
            if self.fault == "wrong_pub":meta["identity"][field] += 2
            else:meta["identity"][field] ^= 1
        if meta["valid"]:
            self._meta_valid_queries += 1
            if self.fault == "wrong_bank" and self._meta_valid_queries>1:
                meta["bank"]^=1
            if self.fault == "mask_unknown":meta["mask_valid"]=False
            if self.fault == "unfinished_wait":meta["wait_complete_frames"]=0
            if self.fault == "bad_crc":meta["rgb_crc64"]^=1
            if self.fault == "bad_statistics":meta["statistics"]["gray_sum"]+=1
            if self.fault == "bad_features":meta["features"]["sum9_total"]+=1
            if self.fault == "short_fifo":meta["fifo_reads"]-=1
            if self.fault == "bad_mask_count":meta["statistics"]["board_count"]-=1
            if self.fault == "bad_parameters":meta["parameters"]["brightness"]^=1
