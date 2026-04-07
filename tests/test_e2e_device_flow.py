#!/usr/bin/env python3
"""E2E Device Flow Test via REST API."""
import requests
import json

BASE_URL = "http://localhost:8000"

print("=== E2E Device Flow Test ===")

# 1. Start device flow
print("\n1. Start device flow via REST API...")
resp = requests.post(f"{BASE_URL}/api/v1/auth/device", json={
    "client_id": "e2e-test",
    "scopes": ["read:orgs", "read:projects"]
})
data = resp.json()
print(f"   user_code={data['user_code']}, device_code={data['device_code'][:20]}...")
device_code = data["device_code"]
user_code = data["user_code"]

# 2. Approve via REST API (simulating web console)
print("\n2. Approve via REST API (simulating web console)...")
resp = requests.post(f"{BASE_URL}/api/v1/auth/device/approve", json={
    "user_code": user_code,
    "approver": "dev-user"
})
print(f"   {resp.json()}")

# 3. Poll for tokens
print("\n3. Poll for tokens...")
resp = requests.post(f"{BASE_URL}/api/v1/auth/device/token", json={
    "device_code": device_code
})
tokens = resp.json()
print(f"   access_token={tokens['access_token'][:30]}..., scope={tokens['scope']}")
access_token = tokens["access_token"]

# 4. List projects using token
print("\n4. List projects using token...")
resp = requests.get(f"{BASE_URL}/api/v1/projects", headers={
    "Authorization": f"Bearer {access_token}"
})
projects = resp.json()
print(f"   Found {len(projects['items'])} project(s):")
for p in projects["items"]:
    print(f"   - {p['id']}: {p['name']}")

# 5. List orgs using token
print("\n5. List orgs using token...")
resp = requests.get(f"{BASE_URL}/api/v1/orgs", headers={
    "Authorization": f"Bearer {access_token}"
})
orgs = resp.json()
print(f"   Response: {orgs}")
if "items" in orgs:
    print(f"   Found {len(orgs['items'])} org(s):")
    for o in orgs["items"]:
        print(f"   - {o['id']}: {o['name']}")
else:
    print(f"   (orgs response format different)")

print("\n=== E2E Complete! ===")
