"""Integration adapter for the immutable f09 engineering algorithm bundle.

No algorithm is copied, retuned or patched here. Both capture backends call the
same public frozen API. Display/export changes are kept outside the frozen core.
"""
import contextlib,gzip,hashlib,json,shutil,sys
from pathlib import Path
import numpy as np
from contracts import DETECTOR_ID,PARAMETER_FREEZE_ID,REVIEW_COMMIT,SYSTEM_VERSION

HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]
BUNDLE=WORK/'final_parameter_check_20261030'
sys.path.insert(0,str(BUNDLE))
import frozen_runtime

def configuration():
    if Path(frozen_runtime.__file__).resolve()!=BUNDLE/'frozen_runtime.py':
        raise ValueError('Wrong frozen runtime module origin')
    config=frozen_runtime.verify()
    if config['freeze_id']!=PARAMETER_FREEZE_ID or config['semantic']['detector_id']!=DETECTOR_ID:
        raise ValueError('Integration and frozen bundle identities differ')
    return config

def metadata():
    c=configuration();s=c['semantic']
    return dict(parameter_freeze_id=c['freeze_id'],detector_id=s['detector_id'],
                review_implementation=REVIEW_COMMIT,
                detector_parameters=s['detector_config'],
                review_raw_fraction=s['review_raw_fraction'],
                review_endpoint_line_fraction=s['review_endpoint_line_fraction'],
                parameter_file_sha256=hashlib.sha256((BUNDLE/'FROZEN_PARAMETERS.json').read_bytes()).hexdigest(),
                algorithm_source_binding_sha256=hashlib.sha256((BUNDLE/'FROZEN_SOURCES.json').read_bytes()).hexdigest(),
                algorithm_entry='final_parameter_check_20261030/frozen_runtime.py:process')

def process(context,record,target,*,timing=None):
    """Compute and export a complete group; caller owns strict input validation."""
    config=configuration()
    with timing.span('frozen_algorithm_compute') if timing else contextlib.nullcontext():
        output,evidence,scored=frozen_runtime.process(context)
    scored.update(group_id=record['group_id'],sample=record['sample'],low=record['low'],high=record['high'],
                  production_console_switched=True,integration_version=SYSTEM_VERSION)
    target=Path(target);target.mkdir(parents=True,exist_ok=False)
    np.savez_compressed(target/'formal_arrays.npz',**output)
    renderer=frozen_runtime.review.frozen_review
    renderer.write(target/'REVIEW_PRIORITY.json',scored)
    with gzip.open(target/'GAP_REVIEWS.json.gz','wt',encoding='utf-8') as stream:
        json.dump(evidence,stream,ensure_ascii=False,allow_nan=False)
    before=output['candidate'].tobytes()
    display={**record,'sample':record['sample']+' · '+config['freeze_id']}
    with timing.span('group_images_and_report') if timing else contextlib.nullcontext():
        rows=renderer.render_group(target,display,context['planes'],output['candidate'],scored)
    for row in rows:row.update(sample=record['sample'],parameter_freeze_id=config['freeze_id'])
    if before!=output['candidate'].tobytes():raise ValueError('Renderer changed formal candidate')
    return rows,scored

def finalize(parent,record,rows,started):
    renderer=frozen_runtime.review.frozen_review
    renderer.write(parent/'DATASETS.json',[record])
    renderer.write(parent/'FROZEN_DEPENDENCIES.json',renderer.verify_frozen())
    for name in ('FROZEN_PARAMETERS.json','FROZEN_SOURCES.json'):
        shutil.copyfile(BUNDLE/name,parent/name)
    renderer.finalize(parent,[record],rows,started,{p.name:renderer.file_sha(p) for p in renderer.HERE.glob('*.py')})
    # Separate human annotations from historical 60%/55%-only results.
    for path in parent.rglob('*.html'):
        text=path.read_text('utf-8')
        text=text.replace('guangjian-review-priority-v1:',f'guangjian-review-{PARAMETER_FREEZE_ID}-v1:')
        text=text.replace('<body>',f'<body><p>冻结组合 {PARAMETER_FREEZE_ID} · 检测弱5.2/强12 · 复检原片55%/端点28%</p>',1)
        path.write_text(text,'utf-8')
    summary=renderer.read(parent/'SUMMARY.json')
    summary.update(**metadata(),integration_version=SYSTEM_VERSION,production_console_switched=True)
    renderer.write(parent/'SUMMARY.json',summary)
    configuration()
