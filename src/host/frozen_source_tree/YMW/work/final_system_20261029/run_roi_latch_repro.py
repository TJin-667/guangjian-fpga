"""Actual existing camera-core RTL reproduction; no bit generation or hardware IO."""
import argparse,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;WORK=HERE.parent
sys.path.insert(0,str(WORK/'fusion_offload_0108_20261028'))
from run_real_rtl import simulate
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    sources=[WORK/'fusion_board_0108_20261028/derived/lght_core_camera_identity.v',WORK/'auto_exposure_0105_20261015/dependencies/ymw/src/roi_config_ctrl.v',WORK/'acceptance_0107_20261026/transport_layout.v',HERE/'tb_roi_latch_repro.sv']
    hashes=simulate(out,'tb_roi_latch_repro',sources,'ROI_LATCH_REPRO_PASS 2')
    receipt=dict(status='PASS',cases=2,compiled_sources_sha256=hashes,scope='actual camera core ROI latch only; no DDR/physical camera model',hardware_contacted=False,bit_changed=False)
    with (out/'VERIFICATION.json').open('w',encoding='utf-8',newline='\n') as f:json.dump(receipt,f,indent=2);f.write('\n')
    print(json.dumps(receipt))
if __name__=='__main__':main()
