"""Isolated, reviewable 0107 derivatives of the exact r4.3 software stack."""
import hashlib,json,subprocess
from pathlib import Path
from generate_acceptance import HERE,BASE,REPO,PIN,replace

def generate():
    records={}
    names=('host_transport.py','sdk_transport.py','generate_sdk_base.py','software_transport_peer.py',
           'fixed_eight.py','operator_host.py','gray_capture_bridge.py','gray_acquisition_workflow.py',
           'review_engineering_capture.py','xdl_reference.py')
    for name in names:
        data=subprocess.check_output(['git','show',PIN+':'+(BASE/name).relative_to(REPO).as_posix()],cwd=REPO)
        if (BASE/name).read_bytes()!=data:raise ValueError('Baseline changed: '+name)
        s=data.decode().replace('\r\n','\n')
        s=s.replace('0106','0107')
        if name=='host_transport.py':
            s=replace(s,'FORMATS=(1,0x31)','FORMATS=(1,0x31,0x32)\nimport dual_view')
            s=replace(s,'return n*2 if fmt==1 else gray_size','return n*2 if fmt==1 else 3*n+(n+7)//8 if fmt==50 else gray_size')
            s=replace(s,'1,0x0107,3,0,1380','1,0x0107,7,0,1380')
            s=replace(s,'    if fmt==0x31:return codec.decode(raw,width,height)',
                "    if fmt==50:return dual_view.decode(raw,width,height,codec=codec)[1:]\n    if fmt==0x31:return codec.decode(raw,width,height)")
            s=replace(s,"            gray,sat=planes_from_payload(raw,*self.roi[2:],self.fmt)",
                "            gray,sat=planes_from_payload(raw,*self.roi[2:],self.fmt)\n            if self.fmt==50:\n                rgb,_,_=dual_view.decode(raw,*self.roi[2:],codec=codec)\n                if legacy.crc64_ecma(rgb)!=meta['rgb_crc64']:raise ValueError('Original frozen RGB CRC64')")
        elif name=='sdk_transport.py':
            s=replace(s,"SOURCE_COMMIT='46f9d50cf2d854f2e9f31bf8b0dddfe9b2025c07'",
                "SOURCE_COMMIT=json.loads((HERE/'SOURCE_PIN.json').read_bytes())['candidate_source_commit']")
            s=replace(s,"Path(wire.codec.__file__),", "HERE/'SOURCE_PIN.json',HERE/'dual_view.py',Path(wire.codec.__file__),")
            s=replace(s,"raw_name='image.rgb565' if self.pixel_format==1 else 'image.gray_sat'",
                "raw_name='image.rgb565' if self.pixel_format==1 else 'image.dual_view' if self.pixel_format==50 else 'image.gray_sat'")
            s=replace(s,"        (pending/raw_name).write_bytes(self._image_raw)",
                "        (pending/raw_name).write_bytes(self._image_raw)\n        if self.pixel_format==50:\n            rgb,_,_=wire.dual_view.decode(self._image_raw,*rectangle[2:],codec=wire.codec)\n            (pending/'same_frame.rgb565').write_bytes(rgb)")
            s=replace(s,'self.sensor_size[0]*self.sensor_size[1]*2/1380','self.sensor_size[0]*self.sensor_size[1]*3.125/1380')
        elif name=='software_transport_peer.py':
            s=replace(s,'self.pixel_format,3,0,1380','self.pixel_format,7,0,1380')
            s=replace(s,'args not in (1,49)','args not in (1,49,50)')
            s=replace(s,'            else:\n                # Independent byte packing,',
                '            elif self.pixel_format==50:\n                raw=wire.dual_view.encode(rgb,gray,sat)\n            else:\n                # Independent byte packing,')
            s=replace(s,'        def _empty_meta(self):',
                '        def _reset(self):\n            self.pixel_format=1;self.dvp=0;self.pub=0;self.mask_words.clear()\n            super()._reset()\n\n        def _empty_meta(self):')
        elif name=='gray_capture_bridge.py':
            s=replace(s,"r['firmware']==262","r['firmware']==263")
        elif name=='xdl_reference.py':
            s=replace(s,"ROOT=HERE/'integration_refs/xdl_a47a'","ROOT=HERE.parent/'gray_transport_0105_20261025/integration_refs/xdl_a47a'")
        target=HERE/name;target.write_text(s,encoding='utf-8',newline='\n')
        records[name]={'baseline_sha256':hashlib.sha256(data).hexdigest(),'derived_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (HERE/'SOFTWARE_DERIVATION.json').write_text(json.dumps(dict(baseline_commit=PIN,files=records,
        production_0106_modified=False,installed_09_modified=False),indent=2)+'\n')
    # Only the lifecycle generator emits this source; it keeps the original
    # strict cleanup, readback, session/sequence and atomic publication logic.
    import importlib.util
    spec=importlib.util.spec_from_file_location('acceptance_lifecycle_generator',HERE/'generate_sdk_base.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.generate()
    return records

if __name__=='__main__':print(json.dumps(generate(),indent=2))
