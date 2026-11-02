"""Same detector structure, allow proposal seed floor below the old hard-coded14.

The proposal floor is a computational superset only. Every admitted component
still requires the configured actual strong seed. No geometry or merge rule is
relaxed. Frozen runtime modules are not modified or monkeypatched.
"""
from joint_gate import build_cache,cutoff
from body_guard import supplements,extend
from sleeve_guard import apply as apply_sleeve

def predict(x,c):
    h=x['hysteresis'];pool_strong=c.get('proposal_strong',14.0)
    if not 0<=pool_strong<=min(c['strong'],14):raise ValueError('Proposal floor must cover actual strong threshold')
    keys={}
    for weak in set([6.,c['weak']]):
        key=('proposal-floor',weak,pool_strong);keys[weak]=key
        if key not in x['caches']:
            wp=h(x['r'],x['v'],cutoff(weak),1620)['mask']&x['board'];pool=h(x['r'],x['v'],cutoff(weak),cutoff(pool_strong))['mask']&x['board']
            x['caches'][key]=build_cache(x['r'],x['v'],x['board'],x['guide'],wp,pool,x['planes']['gray'],x['planes']['valid'],policy='fixed6_20_isolated_supplements')
    base,anchor,s6,low=supplements(x['caches'][keys[6.]],x['caches'][keys[c['weak']]],c,x['original'])
    ordinary=h(x['r'],x['v'],cutoff(c['weak']),cutoff(c['strong']))['mask']&x['board']
    body=extend(base,anchor,ordinary,x['r'],c,c['reach'],c['half_width'],x['tip_cache']);res=apply_sleeve(body['candidate'],x['sleeve'],c['side_radius'],c['strong'])
    if (x['original']&~res['candidate']).any() or (res['candidate']&~ordinary).any():raise AssertionError('Containment failed')
    return dict(original=x['original'],guide6_20=x['guide'],without_sleeve=body['candidate'],candidate=res['candidate'],side_addition=res['side_addition'],side_envelope=res['side_envelope'],isolated6=s6,isolated_low=low,terminal_extension=body['extension'],ordinary=ordinary)
