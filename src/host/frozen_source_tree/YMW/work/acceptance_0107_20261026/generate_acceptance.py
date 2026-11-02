"""Derive isolated acceptance RTL from committed 0106, leaving it untouched."""
import hashlib,json,re,subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
BASE=HERE.parent/'gray_transport_0105_20261025'
PIN='2000d04ecba10e707bf24ef0151a30e383268c23'
TJ='TJ/work/fpga_image_pipeline/'

def sha(data):return hashlib.sha256(data).hexdigest()
def replace(text,old,new,count=1):
    if text.count(old)!=count:raise ValueError('Unexpected anchor count: '+old)
    return text.replace(old,new)

def generate():
    records={}
    def original(relative):
        p=BASE/relative
        blob=subprocess.check_output(['git','show',PIN+':'+p.relative_to(REPO).as_posix()],cwd=REPO)
        if p.read_bytes()!=blob:raise ValueError('Modified baseline: '+relative)
        records[relative]={'source_sha256':sha(blob)}
        return blob.decode().replace('\r\n','\n')
    for relative in ('transport_packet_store.v','transport_layout.v','derived/lght_identity_router.v',
                     'derived/lght_core_camera_identity.v','derived/tj_frozen_packet_source.v','derived/bx72_ddr_identity_top.v'):
        s=original(relative)
        if relative=='transport_packet_store.v':
            s=re.sub(r"\bformat==8'h31", "(format==8'h31 || format==8'h32)",s)
            s=replace(s,'gray_sat_encoder encoder(', 'dual_view_encoder encoder(')
            s=replace(s,".start(start && pixel_format==8'h31),", ".start(start && (pixel_format==8'h31 || pixel_format==8'h32)),.dual_view(pixel_format==8'h32),")
            s=replace(s,'.out_sof(),','')
            s=replace(s,"pixel_format==1 || pixel_format==8'h31", "pixel_format==1 || pixel_format==8'h31 || pixel_format==8'h32")
            s=replace(s,"pixel_format!=1 && pixel_format!=8'h31", "pixel_format!=1 && pixel_format!=8'h31 && pixel_format!=8'h32")
            s=replace(s,"expected_bytes<=pixel_format==8'h31 ?", "expected_bytes<=pixel_format==8'h32 ? ({10'd0,total_pixels}*3)+(({10'd0,total_pixels}+7)>>3) : pixel_format==8'h31 ?")
        elif relative=='transport_layout.v':
            s=s.replace('22 restoring','23 restoring').replace('[21:0] dividend,quotient','[22:0] dividend,quotient')
            s=s.replace('dividend[21]','dividend[22]').replace('quotient[20:0]','quotient[21:0]').replace('[21:0] next_quotient','[22:0] next_quotient')
            s=s.replace('size[21:0]','size[22:0]').replace('dividend[20:0]','dividend[21:0]').replace('step==21','step==22')
            s=replace(s,"size=pixel_format==8'h31 ?", "size=pixel_format==8'h32 ? ({10'd0,total_pixels}*3)+(({10'd0,total_pixels}+7)>>3) : pixel_format==8'h31 ?")
            s=replace(s,"pixel_format!=1 && pixel_format!=8'h31", "pixel_format!=1 && pixel_format!=8'h31 && pixel_format!=8'h32")
        elif relative.endswith('lght_identity_router.v'):
            s=s.replace("16'h0106","16'h0107")
            s=replace(s,"pixel_format,8'h03", "pixel_format,8'h07")
            s=replace(s,"args!=64'd1 && args!=64'h31", "args!=64'd1 && args!=64'h31 && args!=64'h32")
        elif relative.endswith('lght_core_camera_identity.v'):
            s=s.replace("16'h0106","16'h0107")
            s=replace(s,'12:tx_data=1;13:tx_data=6;','12:tx_data=1;13:tx_data=7;')
            s=s.replace("active_format==8'h31", "(active_format==8'h31 || active_format==8'h32)")
            s=s.replace("active_format!=8'h31", "(active_format!=8'h31 && active_format!=8'h32)")
        out=HERE/relative;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(s,encoding='utf-8',newline='\n')
        records[relative]['derived_sha256']=sha(out.read_bytes())
    s=original('build_candidate.py')
    s=replace(s,'from generate_candidate import generate,HERE,REPO,PIN,TJ,replace',
        "from generate_acceptance import generate,HERE,REPO,PIN,TJ,replace\nimport sys\nsys.path.append(str(HERE.parent/'gray_transport_0105_20261025'))")
    s=replace(s,"HERE/'transport_layout.v',", "HERE/'transport_layout.v',HERE/'dual_view_encoder.v',")
    s=replace(s,'frozen_frame_owner.v gray_sat_encoder.v transport_packet_store.v',
        'frozen_frame_owner.v gray_sat_encoder.v dual_view_encoder.v transport_packet_store.v')
    (HERE/'build_candidate.py').write_text(s,encoding='utf-8',newline='\n')
    records['build_candidate.py']['derived_sha256']=sha((HERE/'build_candidate.py').read_bytes())
    data={'baseline_commit':PIN,'changes':['fw0107/capability bit2 with diagnostic format0x32',
        'single gray encoder plus 8 RGB words, grouped same-frozen-stream dual view',
        '23-bit layout division for maximum6480000 bytes'],
        'baseline_files_modified':False,'image_algorithm_changed':False,'files':records}
    (HERE/'derived/SOURCE_MANIFEST.json').write_text(json.dumps(data,indent=2)+'\n')
    return data

if __name__=='__main__':print(json.dumps(generate(),indent=2))
