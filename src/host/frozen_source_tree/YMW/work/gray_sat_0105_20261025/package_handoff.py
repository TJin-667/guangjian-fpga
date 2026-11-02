from pathlib import Path
import hashlib,json,zipfile

HERE=Path(__file__).resolve().parent
WORKSPACE=Path('C:/Users/yue/Documents/ChatGPT/fpga创新设计大赛 光鉴项目')
OUT=WORKSPACE/'output/GRAY_SAT_Execution_20261025_r2'
OUT.mkdir(parents=True,exist_ok=True)
result=json.loads((HERE/'verification/run_04/verification.json').read_text(encoding='utf-8'))
assert result['status']=='PASS' and result['unique_gray_sat_payloads']==16
status=dict(date='2026-10-25',revision='r2',stage='ISOLATED_PRIMITIVE_AND_OFFLINE_CONTRACT_READY',
    coding_and_fixed_plan_tests=9,RGB565_codes_in_software_and_RTL=65536,
    checked_image_members=24,unique_historical_inputs=16,
    ooc_primitive=dict(LUT=290,FF=219,BRAM=0,DSP=0,clock_MHz=125,
       internal_setup_slack_ns=1.841,internal_hold_slack_ns=.202,
       summary_WNS_ns=.881,summary_WHS_ns=-.219,
       all_timing_constraints_met=False,
       pending='OOC port hold and actual integrated-board timing/constraints'),
    new_board_bit_built=False,board_tested=False,new_fusion_validated=False,
    protected_files_unchanged=35,team_messages_sent=False,
    TJ_is_current_execution_dependency=False,
    next=dict(XDL='Confirm post-meeting route; update 004 references; fixed exposure, labels, fusion training and validation',
              YMW_assistant='RTL sender/format/capability/CRC, full-board evidence, strict SDK/archive and fixed eight-frame entry',
              YMW_human='Owner of former TJ task; all physical sampling, flashing and final现场验证'),
    target_technical_freeze='2026-10-30',target_video_and_materials='2026-10-31')
(HERE/'STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
review=WORKSPACE/'output/XDL_aa5669d_Review_20261024'
sample005=WORKSPACE/'output/BX72_Sample005_Review_20261024'
context_inputs={
 'HUMAN_REVIEW.json':review/'HUMAN_REVIEW.json',
 'lower_extension/lower_extension_candidate_regions.png':review/'lower_extension/lower_extension_candidate_regions.png',
 'sample004_raw_rgb_coordinate_panel.png':review/'lower_extension/raw_rgb_coordinate_panel.png',
 'reference_proposal_raw_only.png':review/'pinned/XDL/result/2026-10-24_01_sample004_exposure_review/reference_proposal_raw_only.png',
 'sample004_original_reference_proposal.json':review/'pinned/XDL/fourlight_fusion/XDL_Algorithm/exposure_complement_v1/references/sample004_v1_proposal.json',
 'sample005/README.md':sample005/'README.md',
 'sample005/USER_FEEDBACK.json':sample005/'USER_FEEDBACK.json',
 'sample005/v0/verification.json':sample005/'v0/verification.json',
 'sample005/v1/verification.json':sample005/'v1/verification.json',
}
context_sources=[]
for relative,source in context_inputs.items():
    data=source.read_bytes();target=HERE/'context'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    context_sources.append(dict(path='context/'+relative,original_path=str(source),sha256=hashlib.sha256(data).hexdigest()))
human=json.loads((HERE/'context/HUMAN_REVIEW.json').read_text(encoding='utf-8'))
assert hashlib.sha256((HERE/'context/lower_extension/lower_extension_candidate_regions.png').read_bytes()).hexdigest()==human['lower_fading']['region_review']['reviewed_figure_sha256']
assert hashlib.sha256((HERE/'context/reference_proposal_raw_only.png').read_bytes()).hexdigest()==human['reviewed_reference_figure_sha256']
(HERE/'context/README.md').write_text('''# XDL阅读顺序与证据范围

先读根目录HANDOFF_TO_XDL.txt和MEETING_ROUTE_CONFIRMATION.md，确认会后技术路线和本轮YMW接手TJ任务的新分工，再看本目录证据。

1. HUMAN_REVIEW.json与两张004参考/定位图：原话、固定图像哈希和同一划痕归属，端点及精确中心线仍有unknown。
2. sample004_original_reference_proposal.json是XDL原提案，保留原样；后续人工确认单独叠加，不自动把整份参考升级为真值。
3. sample004_raw_rgb_coordinate_panel.png是已有400/600/800行1倍同坐标原图裁剪，无亮度拉伸。
4. sample005/包含已有005审计摘要/凭证和用户定性反馈，不含两份原ZIP；如需离线原包向YMW索取已保存文件，不要求重拍。

原始错误会议PDF不作为新路线依据。先前更正版PDF中的TJ分工也已被这次r2安排覆盖；本轮不依赖TJ。
''',encoding='utf-8')
selected=list(HERE.glob('*.py'))+list(HERE.glob('*.v'))+list(HERE.glob('*.sv'))+list(HERE.glob('*.tcl'))
selected += [HERE/'README.md',HERE/'HANDOFF_TO_YMW_FPGA.txt',HERE/'HANDOFF_TO_XDL.txt',HERE/'MEETING_ROUTE_CONFIRMATION.md',HERE/'STATUS.json',HERE/'verification/protected_files.json']
selected += [p for p in (HERE/'context').rglob('*') if p.is_file()]
selected += [HERE/'verification/run_04'/n for n in ('verification.json','image_equivalence.json','python_tests.txt','rtl_tool_0.txt','rtl_tool_1.txt','rtl_tool_2.txt')]
selected += list((HERE/'verification/run_04/rtl').glob('*.hex'))
selected += [HERE/'verification/ooc_02'/n for n in ('utilization.rpt','timing.rpt','internal_setup.rpt','internal_hold.rpt','vivado.log','vivado.jou')]
selected=sorted(set(selected))
manifest=dict(files=[dict(path=p.relative_to(HERE).as_posix(),bytes=p.stat().st_size,
    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in selected],
    original_archives_included=False,raw_RGB_full_frames_included=False,existing_raw_crops_and_reference_figures_included=True,
    context_sources=context_sources,installed_runtime_modified=False,
    purpose='Internal implementation handoff, not a claim of official submission ZIP requirements')
(HERE/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
archive=OUT/'GRAY_SAT_YMW_XDL_更新交接_20261025_r2.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in selected+[HERE/'PACKAGE_MANIFEST.json']:
        z.write(p,p.relative_to(HERE).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for entry in manifest['files']:
        data=z.read(entry['path'])
        assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
for name in ('README.md','HANDOFF_TO_YMW_FPGA.txt','HANDOFF_TO_XDL.txt','MEETING_ROUTE_CONFIRMATION.md','STATUS.json'):
    (OUT/name).write_bytes((HERE/name).read_bytes())
receipt=dict(path=str(archive),bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
             entries=len(selected)+1,zip_crc_and_all_member_hashes='PASS',status=status)
(OUT/'DELIVERY_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in receipt.items() if k!='status'},ensure_ascii=False))
