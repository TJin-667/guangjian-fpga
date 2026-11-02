"""Unified 09 workflow. All board actions require explicit operator confirmation."""
import argparse
import contextlib
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from common import ROOT, digest, read_json, write_json, require, verify_inventory, extract_zip, verify_vendor
import capture_adapter as capture


@contextlib.contextmanager
def console_lock(lab):
    """Separate whole-workflow lock; nested 07/08 each retain their common SDK lock."""
    import msvcrt
    with (Path(lab)/'.inspection_console.lock').open('a+b') as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError('另一个09检测流程尚未结束') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def run_analysis(source, out, cancel=None, notify=lambda *a, **k: None, allow_peer=False):
    """Isolated imports; bounded, cancellable CPU process. No hardware sockets."""
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise InterruptedError('Cancelled before analysis')
    command = [sys.executable, '-B', str(ROOT/'analysis_worker.py'), '--source', str(source), '--out', str(out)]
    if allow_peer:
        command.append('--allow-peer')
    notify('progress', text='正在核验原图、H1/H2并计算B1/M1融合')
    # Capture stdout/stderr in a file: no pipe fill deadlock and no shell expansion.
    log_path = Path(out).with_name(Path(out).name+'_process.log')
    with log_path.open('x', encoding='utf-8') as log:
        with subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                              env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONIOENCODING':'utf-8'}) as process:
            started = time.monotonic()
            while process.poll() is None:
                if cancel.wait(0.1) or time.monotonic()-started > 180:
                    process.terminate()  # Own CPU-only analysis child; never touches another application.
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise InterruptedError('Analysis cancelled') if cancel.is_set() else TimeoutError('Analysis exceeded 180 seconds')
            require(process.returncode == 0, '分析失败，详见 '+str(log_path)+'：'+log_path.read_text(encoding='utf-8')[-1200:])
    return read_json(Path(out)/'analysis_summary.json')


def new_output(lab, sample, kind):
    core = capture.legacy(lab).load_core(lab)
    import re
    safe = re.sub(r'[^\w.-]', '_', sample)[:80]
    out = Path(lab)/'results'/('inspection_'+kind+'_'+safe+'_'+core.local_now().strftime('%Y%m%d_%H%M%S')+'_'+secrets.token_hex(3))
    out.mkdir(parents=True, exist_ok=False)
    return out


def execute(plan, *, automatic=False, confirmed_same_pose=False, cancel=None, notify=lambda *a, **k: None):
    require(confirmed_same_pose is True, '请先人工确认工件、轮廓、相机和灯位没有变化，并关闭预览')
    lab = Path(plan['lab_root'])
    fresh, _, _ = capture.prepare_plan(lab, plan['source'])
    require(fresh == plan and not plan.get('exposure_binding'), 'Preflight changed; reload before starting')
    cancel = cancel or threading.Event()
    require(not cancel.is_set(), 'Cancelled before start; no board command sent')
    verify_vendor()
    core = capture.legacy(lab).load_core(lab)
    with console_lock(lab):
        out = new_output(lab, plan['sample_id'], 'online')
        started = time.monotonic_ns()
        summary = dict(schema=1, status='STARTED', sample_id=plan['sample_id'], automatic_exposure_requested=automatic,
                       evidence_source='not_started', operator_started_monotonic_ns=started, operator_same_pose_confirmed=True,
                       source_frames_are_initialization_only=True, physical_freshness_verified=False,
                       external_io_qualified=False, analysis_location='PC', FPGA_complete_detector=False)
        write_json(out/'requested_plan.json', plan)
        write_json(out/'operator_summary.json', summary)
        try:
            active = plan
            if automatic:
                auto_plan, _ = core.prepare_plan(lab, plan['source'])
                notify('progress', text='先执行本轮07自动曝光；锁定后重新采集四方向')
                # Do not forward the stage-level finished event as a workflow completion.
                def auto_notify(event, **data):
                    if event != 'finished':
                        notify(event, **data)
                auto = core.run_real(auto_plan, confirmed_same_pose=True, cancel=cancel, notify=auto_notify)
                summary['automatic_exposure_result'] = dict(output=auto['output'], archive=auto['archive'],
                    archive_sha256=digest(auto['archive']), summary=auto['summary'])
                # Include the byte-preserved 07 ZIP so one 09 delivery contains its control-stage evidence.
                import shutil
                shutil.copyfile(auto['archive'], out/'auto_stage_original.zip')
                require(digest(out/'auto_stage_original.zip') == summary['automatic_exposure_result']['archive_sha256'],
                        'Embedded auto stage ZIP copy differs')
                summary['automatic_exposure_result']['embedded_archive'] = 'auto_stage_original.zip'
                write_json(out/'auto_stage_link.json', summary['automatic_exposure_result'])
                if auto['summary']['status'] != 'LOCKED':
                    summary['status'] = 'AUTO_EXPOSURE_NOT_LOCKED_REVIEW'
                    raise InterruptedError('自动曝光未锁定，不进入正式四方向采集')
                active, _, _ = capture.prepare_plan(lab, plan['source'], auto['output'])
            if cancel.is_set():
                raise InterruptedError('Cancelled after auto stage')
            write_json(out/'effective_plan.json', active)
            acquired = capture.run_capture(active, out/'acquisition', confirmed_same_pose=True, cancel=cancel, notify=notify)
            s = acquired['summary']
            summary.update(acquisition=s, evidence_source=s['evidence_source'], effective_exposure_lines=active['exposure_lines'],
                           operator_same_pose_confirmed=s['operator_same_pose_confirmed'])
            if not s['captures_complete']:
                summary['status'] = s['status']
            elif cancel.is_set():
                summary['status'] = 'CANCELLED'
            else:
                summary['analysis'] = run_analysis(out/'acquisition', out/'analysis', cancel, notify)
                summary['status'] = 'ANALYZED_REVIEW_REQUIRED' if s['lights_off']['acknowledged'] else 'ANALYZED_LIGHTS_OFF_UNCONFIRMED'
            summary['cost_scope'] = dict(saved_fourlight=s['saved_images'], fourlight_attempts=s['capture_attempts'],
                known_completed_fourlight_transaction_frames=s['known_completed_transaction_frames'],
                auto_transport_cost=summary.get('automatic_exposure_result',{}).get('summary',{}).get('transport_cost'),
                initialization_02_03_is_prior_separate_work=True,
                current_run_elapsed_includes_auto_capture_analysis_and_archive=True,
                physical_settling_time_calibrated=False)
        except BaseException as exc:
            if summary['status'] == 'STARTED':
                summary['status'] = 'CANCELLED' if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else 'PROGRAM_ERROR'
            summary['error'] = dict(type=type(exc).__name__, message=str(exc))
        summary.update(cancel_requested=cancel.is_set(), host_elapsed_ms_before_archive=(time.monotonic_ns()-started)/1e6)
        result = core.finalize_output(out, summary)
        notify('finished', **result)
        return result


def import_existing(lab, source, *, cancel=None, notify=lambda *a, **k: None):
    """Read-only offline replay; creates a NEW output and never connects to the board."""
    source, lab = Path(source).resolve(), Path(lab).resolve()
    require(source.exists(), 'Input does not exist')
    core = capture.legacy(lab).load_core(lab)
    cancel = cancel or threading.Event()
    with tempfile.TemporaryDirectory(prefix='bx72_import_', dir=str(lab/'results')) as temporary:
        root = extract_zip(source, Path(temporary)/'package') if source.is_file() else source
        verify_inventory(root)
        plan = read_json(root/'plan.json')
        require('channels' in plan, 'Choose an 08 four-direction package, not a single/07/09 result')
        out = new_output(lab, plan['sample_id'], 'offline')
        started = time.monotonic_ns()
        summary = dict(schema=1, status='STARTED', sample_id=plan['sample_id'], evidence_source='offline_replay_of_real_board',
                       operator_started_monotonic_ns=started, original_source=str(source),
                       input_archive_sha256=digest(source) if source.is_file() else None,
                       physical_board_contacted_by_this_run=False, FPGA_complete_detector=False, analysis_location='PC')
        write_json(out/'input_link.json', dict(original_source=str(source), source_manifest=read_json(root/'output_manifest.json'),
                                              archive_sha256=summary['input_archive_sha256'], raw_data_copied=False))
        try:
            summary['analysis'] = run_analysis(root, out/'analysis', cancel, notify)
            summary['status'] = 'OFFLINE_ANALYZED_REVIEW_REQUIRED'
            # Never leave a temporary path as the user's source locator.
            summary['analysis']['input_folder'] = str(source)
            write_json(out/'analysis/analysis_summary.json', summary['analysis'])
        except BaseException as exc:
            summary['status'] = 'CANCELLED' if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else 'PROGRAM_ERROR'
            summary['error'] = dict(type=type(exc).__name__, message=str(exc))
        summary['host_elapsed_ms_before_archive'] = (time.monotonic_ns()-started)/1e6
        result = core.finalize_output(out, summary)
        notify('finished', **result)
        return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root', type=Path, default=Path('C:/BX72_0105_LAB'))
    p.add_argument('--source', type=Path)
    p.add_argument('--plan-only', action='store_true')
    p.add_argument('--analyze-existing', type=Path)
    a = p.parse_args()
    if a.analyze_existing:
        r = import_existing(a.lab_root, a.analyze_existing)
        print(r['summary']['status']+'\n'+r['archive'])
        raise SystemExit(0 if 'ANALYZED' in r['summary']['status'] else 2)
    if a.plan_only:
        plan, _, _ = capture.prepare_plan(a.lab_root, a.source)
        print(__import__('json').dumps(plan, ensure_ascii=False, indent=2))
    else:
        p.error('Real capture is operator-started from inspection_app.py; use --plan-only or --analyze-existing here')
