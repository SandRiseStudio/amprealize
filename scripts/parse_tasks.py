#!/usr/bin/env python3
"""Parse task list from content.json and extract IDs for batch update."""
import json
import sys
from collections import defaultdict

CONTENT_FILE = "/Users/nick/Library/Application Support/Code/User/workspaceStorage/c35cc553ea993f672445c56786439044/GitHub.copilot-chat/chat-session-resources/6756e2cc-7cf7-46e1-a457-0dddf81a0e8f/toolu_01N2k9RAujGCupeMv2UPFD8i__vscode-1773336195095/content.json"

with open(CONTENT_FILE) as f:
    data = json.load(f)

items = data.get("items", [])
print(f"Total tasks: {len(items)}")

# Orphans
orphans = [i for i in items if not i.get("parent_id")]
print(f"Orphan tasks (no parent): {len(orphans)}")
for o in orphans:
    print(f'  {o["item_id"]} "{o["title"][:60]}"')

# Group by parent
by_parent = defaultdict(list)
for i in items:
    pid = i.get("parent_id", "NONE")
    by_parent[pid or "NONE"].append(i)

print(f"\n=== Tasks grouped by parent ===")
for pid, tasks in sorted(by_parent.items()):
    print(f"\nParent: {pid} ({len(tasks)} tasks)")
    for t in tasks:
        labels = t.get("labels", [])
        print(f'  {t["item_id"]}  "{t["title"][:70]}"  labels={labels}')

# Write all IDs to file for batch processing
with open("/Users/nick/amprealize/scripts/task_ids.txt", "w") as f:
    for i in items:
        pid = i.get("parent_id", "NONE")
        labels = json.dumps(i.get("labels", []))
        f.write(f'{i["item_id"]}\t{pid}\t{labels}\t{i["title"]}\n')

print(f"\nWrote {len(items)} task IDs to scripts/task_ids.txt")
