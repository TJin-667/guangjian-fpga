"""Image/fault plans over the existing SHA-verified, real-socket software peer."""
import copy
import numpy as np


def gray_word(level):
    return ((level >> 3) << 11) | ((level >> 2) << 5) | (level >> 3)


def make_peer_class(dependencies):
    original = dependencies.sdk.acquisition_test_peer
    diag = dependencies.sdk.identity_diag
    arrays = dependencies.sdk.run_xdl_revision2.synthetic_arrays
    stats = dependencies.sdk.run_xdl_revision2.stats

    class LoopPeer(original.UdpPeer):
        """No claim of electrical DDR/PHY/SCCB or physical exposure behavior."""
        def __init__(self, *, image_plan=None, fault_plan=None, first_fid=10,
                     sensor_size=(160, 160)):
            self.image_plan = image_plan or (lambda e, n, w, h: np.full((h, w), gray_word(100), np.uint16))
            self.fault_plan = fault_plan or {}
            self.captured = []
            super().__init__(dependencies.root / "ymw", sensor_size=sensor_size,
                             fault=self.fault_plan.get(1, ""))
            self.fid = first_fid

        def _handle(self, data, peer):
            if len(data) >= 8 and data[5] == 2:
                key = (2, int.from_bytes(data[6:8], "big"))
                if key not in self.cache:
                    self.fault = self.fault_plan.get(self.counter+1, "")
            return super()._handle(data, peer)

        def _start_capture(self, peer, args):
            x, y, w, h = self.roi if args[0] == 3 else [0, 0, *self.sensor_size]
            generation = self.roi_generation if args[0] == 3 else 0
            tag = dict(session=self.session, request_id=self.counter, config_epoch=self.config_epoch,
                       dvp_sequence=0, publish_sequence=0, roi_generation=generation,
                       camera_generation=self.camera_generation, light_generation=self.light_generation,
                       frame_id=self.fid)
            parameters = dict(exposure_lines=self.exp, gain16=self.gain, light_mask=self.mask,
                              brightness=self.brightness, settle_frames=self.wait, discard_frames=self.discard)
            self.last = self._empty_meta()
            self.last.update(identity=tag, parameters=parameters, roi=[x,y,w,h],
                             request_counter=self.counter)
            self._meta_valid_queries = 0
            values = self.image_plan(self.exp, self.counter, w, h)
            if values.shape != (h,w) or values.dtype != np.uint16:
                raise ValueError("software image plan must return uint16 RGB565")
            raw = values.astype(">u2").tobytes()
            mask = np.array([(self.mask_words.get(i//32,0) >> (31-i%32)) & 1
                             for i in range(w*h)], np.uint8).reshape(h,w)
            data = arrays(values, mask)
            self.dvp = (self.dvp+self.wait+self.discard+1) & 0xffffffff
            self.pub = (self.pub+1) & 0xffffffff
            tag.update(dvp_sequence=self.dvp, publish_sequence=self.pub)
            residual = np.abs(data["residual_n"].astype(np.int32))
            meta = copy.deepcopy(self.last)
            meta.update(valid=True, parameters_valid=True,
                mask_valid=self.mask_valid and self.mask_domain==(w,h,generation),
                identity=tag, bank=(self.pub-1)&1,
                statistics=dict(zip(diag.H1_KEYS, stats(data["gray"],mask,data["rgb_any_max"]))),
                fifo_reads=self.sensor_size[0]*self.sensor_size[1],
                wait_complete_frames=self.wait, discard_complete_frames=self.discard,
                features=dict(strong_count=int((residual>1620).sum()), weak_count=int((residual>648).sum()),
                    sum9_total=int(data["sum9"].sum(dtype=np.uint64)),
                    residual_n_total=int(data["residual_n"].sum(dtype=np.int64))),
                rgb_crc64=diag.crc64_ecma(raw))
            self.captured.append(dict(identity=copy.deepcopy(tag), parameters=parameters, roi=[x,y,w,h]))
            packets = list(self.v1.frame_packets(raw,w,h,self.fid))
            self.last_raw = raw
            self.last.update(identity=dict(tag), parameters_valid=True,
                             mask_valid=meta["mask_valid"], bank=meta["bank"])
            token = (self.session,self.counter)
            delay = .22 if self.fault in ("cancel","cancel_late_image","unknown_retirement","timeout_recovery","slow_capture") else .025
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
                bad = bytearray(packets[0])
                bad[-1] ^= 1
                packets = [packets[0],bytes(bad)]+packets[1:]
            if self.fault in ("missing_packet","timeout_recovery"):
                packets = packets[:-1]
            if self.fault == "truncated_image":
                packets[0] = packets[0][:-1]
            if self.fault == "stale_image":
                packets = list(self.v1.frame_packets(raw,w,h,(self.fid-1)&65535))+packets
            for i,packet in enumerate(packets):
                self._send(packet,peer,delay+i*.00002,token)
            def publish():
                self.last = meta
                self.busy = False
            self._send(None,peer,delay+len(packets)*.00002+.001,token,publish)
    return LoopPeer
