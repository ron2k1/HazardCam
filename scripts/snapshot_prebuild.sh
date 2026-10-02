#!/usr/bin/env bash
set -euo pipefail
mkdir -p artifacts
python3 - <<'PY'
import hashlib, json, os, subprocess, datetime
root=os.getcwd()
ignore={'.git','.worktrees','artifacts','node_modules','.next','models','data/raw'}
rows=[]
for dp,dns,fns in os.walk(root):
    rel=os.path.relpath(dp,root)
    parts=set(rel.split(os.sep)) if rel!='.' else set()
    dns[:] = [d for d in dns if d not in ignore and d != '__pycache__']
    if parts & ignore: continue
    for fn in fns:
        p=os.path.join(dp,fn); r=os.path.relpath(p,root)
        if any(r==x or r.startswith(x+'/') for x in ignore): continue
        try:
            h=hashlib.sha256(open(p,'rb').read()).hexdigest()
            rows.append({'path':r,'sha256':h})
        except OSError: pass
try:
    commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
except Exception:
    commit=None
out={'captured_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'git_commit':commit,'files':sorted(rows,key=lambda x:x['path'])}
with open('artifacts/PREBUILD_SNAPSHOT.json','w') as f: json.dump(out,f,indent=2)
print('Wrote artifacts/PREBUILD_SNAPSHOT.json with',len(rows),'files')
PY
