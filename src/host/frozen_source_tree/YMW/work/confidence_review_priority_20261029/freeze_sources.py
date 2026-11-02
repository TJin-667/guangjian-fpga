"""Maintainer-only snapshot creation; never run automatically to accept changed rules."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
FOLDERS=['confidence_large_gap004_20261029','confidence_gap_review_20261029',
         'confidence_shadow_review_20261029','confidence_large_gap_batch_20261029',
         'joint_threshold_tuning_20261029','seeded_component_tuning_20261029','weak_component_experiment_20261029',
         'confidence_review_priority_20261029']

def main():
    paths=set()
    for name in FOLDERS:
        folder=HERE.parent/name
        paths.update(folder.glob('*.py')); paths.update(folder.glob('PLAN*.json'))
    for name in ['joint_threshold_tuning_20261029/FROZEN_SLEEVE_CONFIG.json',
                 'joint_threshold_tuning_20261029/PACKAGE_BINDING.json',
                 'b1_detection_console_20261027/APP_BINDING.json',
                 'b1_detection_console_20261027/VENDOR_BINDING.json']:
        paths.add(HERE.parent/name)
    binding=dict(schema='frozen-gap-review-and-score-source-v1',
                 base_commit='09f8852688589406d59d3ac1bf8ce449a6731802',
                 formal_config_id='4c0be2d44fdd',orange_rules_changed=False,score_is_calibrated=False,
                 files_sha256={p.relative_to(REPO).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})
    (HERE/'FROZEN_DEPENDENCIES.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('FROZEN_SOURCES',len(paths))

if __name__=='__main__':main()
