"""Generate eight fixed requests for interface review; never capture frames."""
def build_plan(low, high):
    if any(type(v) is not int or not 400 <= v <= 800 for v in (low,high)) or low>=high:
        raise ValueError('Expected two ordered, supported development exposures')
    observations=[]
    for channel,direction in ((1,'上'),(2,'右'),(3,'下'),(4,'左')):
        for role,exposure in (('low',low),('high',high)):
            observations.append(dict(observation_id=f'CH{channel}_{role}',channel=channel,
                direction=direction,role=role,exposure_lines=exposure,gain16=16,led=128))
    return dict(schema='fixed-eight-observation-plan-v0.1',status='REVIEW_ONLY_NOT_CAPTURE_AUTHORIZATION',
        formal_observations=8,online_exposure_search=False,supplement_selection=False,
        automatic_retries=0,initialization_and_wait_and_failures_accounted_separately=True,
        required_before_execution=['frozen_exposure_configuration','physical_board_and_pose',
          'full_frame_and_ROI_provenance','operator_pose_lock','strict_SDK_adapter',
          'transport_capability_and_pixel_format','request_and_session_identity',
          'H1_H2_content_validation_and_final_commit','cancellation_and_LED_off_ACK'],
        observations=observations)

if __name__=='__main__':
    import argparse,json
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--low',type=int,required=True);p.add_argument('--high',type=int,required=True)
    a=p.parse_args();print(json.dumps(build_plan(a.low,a.high),ensure_ascii=False,indent=2))
