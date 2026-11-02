"""Frozen engineering parameter API; never rewrites historical configs or GUI."""
import copy,hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];WORK=HERE.parent
sys.path.insert(0,str(WORK/'trial_review_recompute_20261030'))
import run_review as review
sys.path.insert(0,str(WORK/'weak_stability_tuning_20261030'))
from seed_parameters import predict

def verify():
    binding=review.read(HERE/'FROZEN_SOURCES.json')
    for rel,digest in binding['files_sha256'].items():
        path=(REPO/rel).resolve()
        if not path.is_relative_to(REPO.resolve()) or review.file_sha(path)!=digest:raise ValueError('Frozen source changed: '+rel)
    config=review.read(HERE/'FROZEN_PARAMETERS.json');semantic=config['semantic']
    identity=hashlib.sha256(json.dumps(semantic,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12]
    if identity!=config['freeze_id']:raise ValueError('Frozen semantic identity differs')
    return config

def process(context):
    config=verify();semantic=config['semantic'];output=predict(context,semantic['detector_config']);base=review.read(WORK/'confidence_gap_review_20261029/PLAN.json');base=copy.deepcopy(base);base['gap']['raw_fraction']=semantic['review_raw_fraction'];base['gap']['min_local_line_fraction']=semantic['review_endpoint_line_fraction'];core=review.read(WORK/'confidence_large_gap004_20261029/PLAN.json');gray=context['planes']['gray'].astype(np.float32,copy=False)
    evidence=review.analyze_large_gaps(output['candidate'],gray,context['planes']['valid'],context['board'],context['planes']['residual_n'],base,core);scored=review.attach_scores(evidence,review.windows_for(evidence['gaps']),gray,context['planes']['valid'],context['board'],context['planes']['residual_n'],base,core)
    scored.update(parameter_freeze_id=config['freeze_id'],formal_config_id=semantic['detector_id'],review_raw_fraction=semantic['review_raw_fraction'],review_endpoint_line_fraction=semantic['review_endpoint_line_fraction'],production_console_switched=False)
    return output,evidence,scored
