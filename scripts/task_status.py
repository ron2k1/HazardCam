#!/usr/bin/env python3
import json
from pathlib import Path
s=json.loads(Path('TASK_STATUS.json').read_text())
g=json.loads(Path('TASK_GRAPH.json').read_text())
for t in g['tasks']:
    st=s.get(t['id'],{})
    print(f"{t['id']:>3}  wave={t['wave']}  {st.get('state','?'):<10} {t['title']}")
