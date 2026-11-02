"""Bind independent executables; do not modify the qualified source snapshot."""
import bootstrap as b
from pathlib import Path

def main():
    import ast
    for p in b.HERE.glob('*.py'):ast.parse(p.read_text('utf-8-sig'))
    programs={p.name:b.sha(p) for p in sorted([*b.HERE.glob('*.py'),*b.HERE.glob('*.cmd')])}
    dependencies={}
    for folder in ('host_speed_step1_0109_20261031','host_speed_step2_0109_20261031'):
        root=b.HERE.parent/folder
        for name,sha in b.read(root/'PUBLISH_MANIFEST.json')['files_sha256'].items():
            if name.endswith('.py'):
                dependencies[str(root/name)]=sha
    b.write(b.HERE/'CANDIDATE_BINDING.json',dict(schema='0109-independent-speed-host-v1',program_sha256=programs,dependency_sha256=dependencies,
          qualified_source_commit='0711fa1793845c225c8968300864c777d7e1659f',frozen_id='f09eb5885e1d',firmware=265))
    b.verify();print('Bound',len(programs),'candidate programs')
if __name__=='__main__':main()
