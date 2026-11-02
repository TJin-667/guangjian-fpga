"""Run the original replay and explain strict comparison failures without changing it."""
from pathlib import Path
import json
import runpy

ROOT=Path(__file__).resolve().parents[1]

def differences(actual,expected,path='$',limit=20):
    result=[]
    def visit(a,b,p):
        if len(result)>=limit:return
        if isinstance(a,dict) and isinstance(b,dict):
            for key in sorted(set(a)|set(b),key=str):
                if key not in a or key not in b:
                    result.append(dict(path=p+'.'+str(key),actual=repr(a.get(key)),expected=repr(b.get(key))))
                else:visit(a[key],b[key],p+'.'+str(key))
        elif isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
            if len(a)!=len(b):result.append(dict(path=p+'.length',actual=len(a),expected=len(b)))
            for i,(x,y) in enumerate(zip(a,b)):visit(x,y,p+'['+str(i)+']')
        elif a!=b:result.append(dict(path=p,actual=repr(a),expected=repr(b)))
    visit(actual,expected,path)
    return result

try:
    runpy.run_path(str(ROOT/'scripts/replay_example.py'),run_name='__main__')
except Exception as error:
    frame=error.__traceback__
    while frame:
        values=frame.tb_frame.f_locals
        if 'differences' in values and 'expected_evidence' in values:
            identity=values['score_identity']
            print(json.dumps(dict(strict_replay_failure=str(error),
                formal_array_differences=values['differences'],
                review_differences=differences(values['evidence'],values['expected_evidence']),
                score_differences=differences(identity(values['scored']),identity(values['expected_scores'])),
                numerical_sources_modified=False,comparison_relaxed=False),ensure_ascii=False),flush=True)
        frame=frame.tb_next
    raise
