"""Consistent synthetic records; provenance identifies constructed captures only."""
from dataclasses import fields
from capture_metrics import FrameInput, FrameMetrics, source_identity


def make_frame(**overrides):
    values = dict(context_id='scan_A', observation_id='fixture-1', sample_id='sample001',
                  pose='A', exposure_lines=600, gain16=16, channel=1, led=128,
                  saved_width=100, saved_height=100, roi=(0, 0, 100, 100),
                  png_sha256='a' * 64, rgb565_sha256='b' * 64,
                  source_mode='constructed_fixture',
                  source_metadata=dict(dataset_id='fixture-dataset', capture_id='capture-1',
                                       frame_id='frame-1', member='frame-1.png',
                                       storage_root='fixture-storage'))
    values.update(overrides)
    return FrameInput(**values)


def geometry_for(frame):
    identity = source_identity(frame)
    record = ({'source_mode': frame.source_mode,
               **{k: frame.source_metadata[k] for k in ('dataset_id', 'capture_id', 'frame_id', 'member')},
               'png_sha256': frame.png_sha256, 'rgb565_sha256': frame.rgb565_sha256}
              if identity is not None else None)
    return {**{field.name: getattr(frame, field.name) for field in fields(frame)},
            'source_identity': identity, 'source_identity_record': record,
            'source_identity_available': identity is not None,
            'evaluation_area_version': 'common-evaluation-1', 'common_mask_sha256': 'c' * 64,
            'native_area': 10000, 'common_area': 10000,
            'coverage_numerator': 10000, 'coverage_denominator': 10000,
            'min_area': 10000, 'min_coverage_bp': 9500, 'available': identity is not None,
            'reason_codes': () if identity else ('source_identity_unavailable',),
            'mask_sources': ({'observation_id': frame.observation_id,
                              'source_identity': identity, 'roi': frame.roi,
                              'native_mask_sha256': 'd' * 64,
                              'mask_source': 'constructed_fixture', 'needs_manual_review': True},)}


def make_metrics(**overrides):
    values = dict(n=10000, gray_sum=1000000, dark_count=0, near_white_count=0,
                  rgb_max_count=0, effective_count=10000, line_center_count=0,
                  line_contrast_sum_n=0, background_count=10000,
                  background_activity_sum_n=0, baseline_candidate_count=0,
                  native_reference_statistics={}, geometry=geometry_for(make_frame()))
    values.update(overrides)
    return FrameMetrics(**values)
