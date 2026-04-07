#!/usr/bin/env python3
"""Test parent_id PATCH for work items."""
import requests

def main():
    url = 'http://localhost:8080/api/v1/work-items'
    resp = requests.get(url, params={'limit': 10})
    print('GET work items:', resp.status_code)

    if not resp.ok:
        print(f"Error: {resp.text}")
        return

    items = resp.json().get('items', [])
    task_id = None
    story_id = None

    for item in items:
        item_type = item['item_type']
        title = item['title'][:40]
        item_id = item['item_id'][:8]
        print(f"  {item_id}: type={item_type}, title={title}")

        if item_type == 'task' and not task_id:
            task_id = item['item_id']
        elif item_type == 'story' and not story_id:
            story_id = item['item_id']

    if task_id and story_id:
        print(f"\nTrying PATCH task {task_id[:8]} to parent story {story_id[:8]}")
        patch_resp = requests.patch(f"{url}/{task_id}", json={"parent_id": story_id})
        print(f"PATCH response: {patch_resp.status_code}")

        if patch_resp.ok:
            parent_id = patch_resp.json()['item'].get('parent_id')
            if parent_id:
                print(f"Success! Task now has parent_id: {parent_id[:8]}")
            else:
                print("Success! But parent_id is still None (check if returned)")
        else:
            print(f"Error: {patch_resp.text}")
    else:
        print("\nCould not find both a task and a story to test")

if __name__ == '__main__':
    main()
