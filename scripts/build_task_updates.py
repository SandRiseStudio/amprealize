#!/usr/bin/env python3
"""Build task update mapping: task_id -> track label, for batch v3 updates."""
import json

# Parent story ID -> track mapping (from session memory + prior work)
PARENT_TRACK = {
    # Track A stories
    "6fc639c2-aa89-4193-9294-6d10961a6c72": "track-a",  # A1
    "46c12056-bc23-4717-a3f4-777b9511c7fb": "track-a",  # A2
    "4713db86-e3bf-42da-8c4a-882e7935141e": "track-a",  # A3
    "41ff0f26-10f9-4630-844e-25699e0c7112": "track-a",  # A4
    "efa3c2de-7569-4b31-8a6c-5cba7d16c92d": "track-a",  # A5
    "17f53ac5-171a-470b-81e9-7abbc8a3b583": "track-a",  # A6
    "abd73ef1-1926-4d17-96c6-0d70e3fa739e": "track-a",  # A7
    # Track B stories
    "a5a63e9c-89ec-43d3-8922-e8b9fb25cac3": "track-b",  # B1
    "277d22ad-a0ef-4b73-b4b9-a9c205356e88": "track-b",  # B2
    "2114b349-61a5-4480-9ec7-22569be70cc5": "track-b",  # B3
    "1157c49b-2503-45a8-82cb-4e5ba6875d53": "track-b",  # B4
    "2265e36a-22e4-4654-8f40-2244cfac6bb3": "track-b",  # B5
    "e7540417-2db1-4e32-b970-6aee22381cfc": "track-b",  # B6
    # Track C stories
    "a293d0ff-2c02-46bb-af9c-06564de4edc7": "track-c",  # C1
    "be301c81-0759-4d6b-8432-921b954d7421": "track-c",  # C2
    "a731f283-6d25-487c-af02-3b85ae7bc45e": "track-c",  # C3
    "6b882514-0b2a-42f0-bab4-1b765afaaf37": "track-c",  # C4
    "97675b87-af75-41e6-b96c-9a88844b55bd": "track-c",  # C5
    "9088ea85-05c3-4507-a7b3-1774c38df7f2": "track-c",  # C6
    # Track D stories
    "16219f22-bbcb-4bbd-b8af-1ed019844eec": "track-d",  # D1
    "49ee15e2-8e30-4248-adfe-0b81e0e27fa1": "track-d",  # D2
    "22c0ae57-0ec5-4111-95e9-c74b3e1c0d74": "track-d",  # D3
    "733bdb4e-029b-4f9b-a5d6-83aef8bcec41": "track-d",  # D4
    "27e56218-0cc8-4e49-82cf-82b041625d9a": "track-d",  # D5
    "99476ef4-dd8a-40ea-8096-2915f92f50e2": "track-d",  # D6
    "a7939f4a-a005-4a22-acc8-7c3885af39b0": "track-d",  # D7
    "7f22fc78-d65b-441a-8c58-20587f57e797": "track-d",  # D8
    "3a559404-66cb-4f9f-ba24-476f12e4938f": "track-d",  # D9
    "ae241d2f-8bc1-4293-8cc0-e7381e9c5296": "track-d",  # D10
    # Track E stories
    "93b6c9aa-91ba-4740-9eae-4e9a95386c30": "track-e",  # E1
    "db8c82b4-5d0a-46cd-9afc-481d2241ce40": "track-e",  # E2
    "0008c6cf-0237-4052-8a38-dc932c39f6a1": "track-e",  # E3
    "f87d8642-967c-4322-8bfa-e107a5dcb587": "track-e",  # E4
    "a5500af3-b217-4b0e-9e07-e10751b55746": "track-e",  # E5
    "eea74ec2-38e0-44d9-ba7e-07f42c44ec25": "track-e",  # E6
    "e716fe63-9851-42b5-aa29-fd55bc8f91ff": "track-e",  # E7
    # Track F stories
    "4cc6c72a-e458-483d-9c7b-6f58de140bd5": "track-f",  # F1
    "e73a6e06-f3be-49f7-950f-7c7de11dea6a": "track-f",  # F2
    "424b3c41-b746-4567-8802-2862b53af460": "track-f",  # F3
}

# Read task_ids.txt
tasks = []
with open("scripts/task_ids.txt") as f:
    for line in f:
        parts = line.strip().split("\t")
        if len(parts) >= 4:
            item_id, parent_id, labels_json, title = parts[0], parts[1], parts[2], parts[3]
            existing_labels = json.loads(labels_json) if labels_json != "[]" else []
            if parent_id == "None":
                parent_id = None
            track = PARENT_TRACK.get(parent_id, "orphan") if parent_id else "orphan"
            tasks.append({
                "item_id": item_id,
                "parent_id": parent_id,
                "title": title,
                "existing_labels": existing_labels,
                "track": track,
            })

# Output as JSON for consumption
output = []
for t in tasks:
    new_labels = list(set(t["existing_labels"] + ["installation-plan-v3", t["track"]]))
    new_labels.sort()
    output.append({
        "item_id": t["item_id"],
        "title": t["title"],
        "track": t["track"],
        "labels": new_labels,
    })

# Summary
tracks = {}
for t in output:
    tracks.setdefault(t["track"], []).append(t["title"])

print("=== TASK UPDATE PLAN ===")
for track, items in sorted(tracks.items()):
    print(f"\n{track}: {len(items)} tasks")
    for i in items[:3]:
        print(f"  - {i}")
    if len(items) > 3:
        print(f"  ... +{len(items)-3} more")

print(f"\nTotal: {len(output)} tasks to update")

# Write JSON for batch processing
with open("scripts/task_updates.json", "w") as f:
    json.dump(output, f, indent=2)
print("\nWrote scripts/task_updates.json")
