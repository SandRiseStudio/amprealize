#!/usr/bin/env python3
"""
Create a story with tasks for the behavior lifecycle workflow feature.
"""
import requests

BOARD_ID = "96cf2703-8a4b-4bab-a740-981abb6c33df"
API_URL = "http://localhost:8080/api/v1/work-items"

def main():
    # Create a story for the behavior lifecycle workflow feature
    story_payload = {
        "board_id": BOARD_ID,
        "title": "Behavior Lifecycle Workflow - Student/Strategist/Teacher Approval Flow",
        "description": """## Summary
Implement first-class platform support for the behavior lifecycle workflow defined in AGENTS.md.

## Current State
- BehaviorService has DRAFT -> IN_REVIEW -> APPROVED lifecycle in backend
- MCP tools exist: behaviors.create, behaviors.submit, behaviors.approve
- No UI workflow guides agents through proper lifecycle

## Desired State
1. **Student Role**: Can DISCOVER patterns and escalate to Strategist
2. **Strategist Role**: Can PROPOSE new behaviors (creates DRAFT)
3. **Teacher Role**: Can APPROVE/REJECT behavior proposals (DRAFT -> APPROVED)
4. **All Roles**: Can USE approved behaviors

## Acceptance Criteria
- [ ] Behavior proposals visible on project boards as work items
- [ ] Role-based permissions (only Teachers can approve)
- [ ] Confidence score tracking (>=0.8 eligible for auto-approval)
- [ ] Historical validation tracking (3+ cases required)
- [ ] Approval workflow with review UI
- [ ] Integration with web console and VS Code extension

## Reference
- AGENTS.md section: Behavior Lifecycle (lines 115-230)
- behavior_curate_behavior_handbook
""",
        "item_type": "story",
        "priority": "high"
    }

    resp = requests.post(API_URL, json=story_payload)
    print(f"Create story: {resp.status_code}")

    if not resp.ok:
        print(f"Error: {resp.text}")
        return

    story = resp.json()["item"]
    print(f"Story created: {story['item_id'][:8]}... - {story['title'][:50]}")
    story_id = story["item_id"]

    # Create tasks that roll up to this story
    tasks = [
        "Add behavior proposal form to web console with DRAFT status",
        "Implement role-based approval permissions for Teacher role",
        "Add confidence score + historical validation tracking",
        "Create approval review UI with accept/reject workflow",
        "Wire behavior proposals as board work items",
        "Add VS Code extension integration for behavior lifecycle"
    ]

    for i, title in enumerate(tasks, 1):
        task_payload = {
            "board_id": BOARD_ID,
            "title": title,
            "item_type": "task",
            "priority": "medium",
            "parent_id": story_id
        }
        task_resp = requests.post(API_URL, json=task_payload)
        if task_resp.ok:
            task = task_resp.json()["item"]
            print(f"  Task {i}: {task['item_id'][:8]}... - {title[:45]}")
        else:
            print(f"  Task {i} FAILED: {task_resp.status_code} - {task_resp.text}")

if __name__ == "__main__":
    main()
