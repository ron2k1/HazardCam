#!/usr/bin/env python3
"""Print each task in TASK_GRAPH.json with its status from TASK_STATUS.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

status = json.loads((ROOT / "TASK_STATUS.json").read_text(encoding="utf-8"))["tasks"]
graph = json.loads((ROOT / "TASK_GRAPH.json").read_text(encoding="utf-8"))
for task in graph["tasks"]:
    state = status.get(task["id"], {}).get("status", "?")
    print(f"{task['id']:>3}  wave={task['wave']}  {state:<12} {task['title']}")
