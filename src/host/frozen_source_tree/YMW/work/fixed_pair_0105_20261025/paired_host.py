"""Independent 0105 fixed-pair CLI. Import/prepare never open a board socket."""
import argparse,contextlib,hashlib,importlib.util,json,sys,time
from pathlib import Path
import fixed_pair_runner as backend
from multiobs.ports import SDK_SHA256

HERE=Path(__file__).resolve().parent
LEGACY_SHA='d0a537d7cf0a336bb93a8b1d6f4270430e0032d326c77ca699c79dbdecb2fd6d'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(condition,message):
    if not condition:raise ValueError(message)
def read(path):
    def bad(value):raise ValueError('Nonfinite JSON: '+value)
    return json.loads(Path(path).read_bytes(),parse_constant=bad)

class Runtime:
    """Existing frozen 08/07 preflight, SDK and archive; no exposure controller run."""
    def __init__(self,lab):
        self.lab=Path(lab).resolve()
        path=self.lab/'fourlight_fixed_v1/fourlight_capture.py'
        require(sha(path)==LEGACY_SHA,'Installed 08 source differs; stop and review.')
        name='_fixed_pair_legacy_'+hashlib.sha256(str(path).encode()).hexdigest()[:12]
        if name not in sys.modules:
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        self.legacy=sys.modules[name];self.core=self.legacy.load_core(self.lab)

    def prepare(self,source):
        source_plan,snapshot,confirmation=self.legacy.prepare_plan(self.lab,source)
        files={'source_full.png':snapshot['full_png_bytes'],
               'source_geometry.json':snapshot['geometry_bytes'],'source_mask.npy':snapshot['mask_npy_bytes'],
               'source_session.json':snapshot['session_bytes'],'source_result.json':snapshot['result_bytes'],
               'source_roi_session.json':confirmation['session_bytes'],'source_roi_result.json':confirmation['result_bytes']}
        full_record=self.core.parse_json(snapshot['result_bytes'])
        roi_record=self.core.parse_json(confirmation['result_bytes'])
        for target,path,digest in [
            ('source_full.rgb565',snapshot['source']/'first_full.rgb565',full_record['raw_rgb565_sha256']),
            ('source_roi.png',confirmation['folder']/'roi_ch1.png',roi_record['png_sha256']),
            ('source_roi.rgb565',confirmation['folder']/'roi_ch1.rgb565',roi_record['raw_rgb565_sha256'])]:
            data=path.read_bytes();require(backend.digest(data)==digest,'Source snapshot changed: '+target);files[target]=data
        files['source_preview.png']=self.core.source_preview(snapshot)
        paths=[Path(self.legacy.__file__),Path(self.core.__file__),self.lab/'runtime_provenance.json',self.lab/'bx72_0105_lab.bit']
        package=self.core.PACKAGE
        paths += [package/'vendor_sources.json',package/'dependencies/dependencies.json']
        paths += [package/p for p in read(package/'vendor_sources.json')['files']]
        paths += [package/'dependencies'/p for p in read(package/'dependencies/dependencies.json')['files']]
        paths += [self.lab/'runtime/software'/p for p in SDK_SHA256]
        hashes={str(p):sha(p) for p in paths}
        context=backend.Context(source_plan['sample_id'],'unused_preflight_pose',tuple(source_plan['roi']),
                                snapshot['controller_native_mask'].tobytes())
        return source_plan,context,files,hashes

    def guard(self):return self.core.operator_lock(self.lab)

    def port(self,source_plan,out):
        engine=self.core.load_engine()
        # Use the exact SDK class. A progress subclass would change inspect's
        # defining-file identity and correctly fail SdkPort's frozen SDK check.
        executor=engine.sdk.acquisition_executor.AcquisitionExecutor(
            board=source_plan['board'],bind=source_plan['bind'],port=source_plan['port'],
            ymw_root=engine.root/'ymw',output_root=out/'sdk_calls',mode='strict',
            evidence_source='real_board',command_timeout=1.5,retries=3)
        try:return backend.SdkPort(executor,self.core.request_lights_off)
        except BaseException:
            executor.close();raise

    def archive(self,out,summary):return self.core.finalize_output(out,summary)

def build_plan(runtime,*,source=None,low,high,physical_specimen_id,pose_id,pair_status,pair_reference):
    backend.identifier(physical_specimen_id);backend.identifier(pose_id)
    require(all(type(v) is int and 400<=v<=800 for v in (low,high)) and low<high,'Two ordered exposures in 400..800 required.')
    require(pair_status in ('development_trial','XDL_frozen') and isinstance(pair_reference,str) and pair_reference.strip(),
            'Explicit trial/frozen status and reference required.')
    base,context,files,runtime_hashes=runtime.prepare(source)
    context=backend.Context(context.sample_id,pose_id,context.roi,context.mask)
    plan=dict(schema='fixed-pair-host-0105-v1',lab_root=str(runtime.lab),source_contract=base,
        physical_specimen_id=physical_specimen_id,pose_id=pose_id,low=low,high=high,
        pair_status=pair_status,pair_reference=pair_reference,gain16=16,brightness=128,
        formal_observations=8,automatic_exposure_search=False,automatic_supplements=False,
        source_snapshot_sha256={name:backend.digest(data) for name,data in files.items()},
        runtime_sha256=runtime_hashes,
        implementation_sha256={str(p):sha(p) for p in [HERE/'paired_host.py',HERE/'fixed_pair_runner.py']},
        source_frames_are_initialization_only=True,physical_freshness_verified=False,
        detector_or_fusion_quality_validated=False,exposure_optimum_verified=False)
    return plan,context,files

def refresh(runtime,approved):
    return build_plan(runtime,source=approved['source_contract']['source'],low=approved['low'],high=approved['high'],
        physical_specimen_id=approved['physical_specimen_id'],pose_id=approved['pose_id'],
        pair_status=approved['pair_status'],pair_reference=approved['pair_reference'])

def execute(approved,*,out,confirmed_same_pose=False,cancel=None,timeout_s=360,single_timeout_s=60,_runtime=None):
    """Explicit operator invocation only. Private runtime injection is for tests."""
    require(confirmed_same_pose is True,'Review source_preview, close other clients and confirm same specimen/pose before capture.')
    started_ns=time.monotonic_ns()
    runtime=_runtime or Runtime(approved['lab_root'])
    fresh,context,files=refresh(runtime,approved)
    require(fresh==approved,'Source, implementation or plan changed; prepare and review again.')
    out=Path(out).resolve()
    require(not any(p.exists() for p in [out,out.with_name(out.name+'.zip'),out.with_name(out.name+'.zip.sha256'),out.with_name(out.name+'.zip.receipt.json')]),
            'Output or archive already exists; use a new output directory.')
    binding={k:approved['source_contract'][k] for k in ['source_full_png_sha256','source_session_sha256','source_roi_session_sha256','native_mask_sha256']}
    binding.update(verified_from_02_03=True,physical_specimen_id=approved['physical_specimen_id'])

    @contextlib.contextmanager
    def guard():
        with runtime.guard():
            # Re-read after obtaining the shared OS lock, before creating SDK.
            locked,_,_=refresh(runtime,approved)
            require(locked==approved,'Source changed while waiting for the acquisition lock.')
            yield

    def port_factory():
        for name,data in files.items():(out/name).write_bytes(data)
        backend.write(out/'approved_plan.json',approved)
        return runtime.port(approved['source_contract'],out)

    preflight_ms=(time.monotonic_ns()-started_ns)/1e6
    try:
        result=backend.run_fixed_eight(context,low=approved['low'],high=approved['high'],
            pair_status=approved['pair_status'],pair_reference=approved['pair_reference'],source_binding=binding,
            port_factory=port_factory,guard_factory=guard,out=out,pose_confirmed=True,cancel=cancel,
            timeout_s=timeout_s,single_timeout_s=single_timeout_s)
    except backend.RoundFailure as exc:result=exc.summary
    except BaseException as exc:
        if not out.exists():raise
        result=dict(status='CANCELLED' if isinstance(exc,KeyboardInterrupt) else 'FAILED',observations=[],
                    error={'type':type(exc).__name__,'message':str(exc)},lights_off={'acknowledged':False},
                    evidence_source='not_started_or_incomplete')
    changed=[]
    for path,digest in {**approved['implementation_sha256'],**approved['runtime_sha256']}.items():
        try:unchanged=sha(path)==digest
        except OSError:unchanged=False
        if not unchanged:changed.append(path)
    status='ACQUIRED_EIGHT_REVIEW_REQUIRED' if result['status']=='COMPLETE_EIGHT' else result['status']
    if changed:status='FAILED'
    summary=dict(schema='fixed-pair-host-0105-v1',status=status,backend_status=result['status'],
        backend_summary='summary.json',physical_specimen_id=approved['physical_specimen_id'],
        sample_id=context.sample_id,pose_id=context.pose_id,pair_status=approved['pair_status'],pair_reference=approved['pair_reference'],
        low=approved['low'],high=approved['high'],gain16=16,brightness=128,
        evidence_source=result.get('evidence_source'),saved_observations=len(result['observations']),
        lights_off=result['lights_off'],changed_runtime_files=changed,
        operator_same_pose_confirmed=True,operator_started_monotonic_ns=started_ns,
        host_preflight_ms=preflight_ms,acquisition_budget_s=timeout_s,
        acquisition_budget_excludes_initial_host_preflight_and_final_zip=True,
        backend_inventory_scope='files present at backend completion; outer output_manifest binds final host additions',
        source_02_03_elapsed_scope='Historical initialization captures; excluded from current host elapsed.',
        source_frames_counted_as_new_pair_observations=False,
        physical_freshness_verified=False,external_io_qualified=False,
        detector_or_fusion_quality_validated=False,workflow_complete_end_to_end_measured=False)
    return runtime.archive(out,summary)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    prepare=sub.add_parser('prepare',help='Offline source/bit/SDK checks; writes plan and exact source preview.')
    prepare.add_argument('--lab-root',type=Path,default=Path('C:/BX72_0105_LAB'));prepare.add_argument('--source',type=Path)
    prepare.add_argument('--low',type=int,required=True);prepare.add_argument('--high',type=int,required=True)
    prepare.add_argument('--physical-specimen-id',required=True);prepare.add_argument('--pose-id',required=True)
    prepare.add_argument('--pair-status',choices=['development_trial','XDL_frozen'],required=True)
    prepare.add_argument('--pair-reference',required=True);prepare.add_argument('--out',type=Path,required=True)
    capture=sub.add_parser('capture',help='Explicit operator action: connects to the existing 0105 board.')
    capture.add_argument('--plan',type=Path,required=True);capture.add_argument('--out',type=Path,required=True)
    capture.add_argument('--confirm-same-pose',action='store_true')
    args=parser.parse_args()
    if args.action=='prepare':
        plan,_,files=build_plan(Runtime(args.lab_root),source=args.source,low=args.low,high=args.high,
            physical_specimen_id=args.physical_specimen_id,pose_id=args.pose_id,pair_status=args.pair_status,pair_reference=args.pair_reference)
        args.out.mkdir(parents=True,exist_ok=False)
        backend.write(args.out/'plan.json',plan);(args.out/'source_preview.png').write_bytes(files['source_preview.png'])
        print(json.dumps({'status':'OFFLINE_PLAN_REVIEW_REQUIRED','plan':str((args.out/'plan.json').resolve()),
                          'preview':str((args.out/'source_preview.png').resolve()),'board_contacted':False},ensure_ascii=False))
        return
    result=execute(read(args.plan),out=args.out,confirmed_same_pose=args.confirm_same_pose)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['summary']['status']!='ACQUIRED_EIGHT_REVIEW_REQUIRED':raise SystemExit(2)

if __name__=='__main__':main()
