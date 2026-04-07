#!/usr/bin/env python3
"""
Nuclear cleanup script for Metabase - deletes ALL user-created dashboards and cards.
Use this to start completely fresh.
"""

import os
import sys
import requests

METABASE_URL = os.getenv("METABASE_URL", "http://localhost:3000")
USERNAME = os.getenv("METABASE_USERNAME", "nick.sanders.a@gmail.com")
PASSWORD = os.getenv("METABASE_PASSWORD")


def main():
    if not PASSWORD:
        print("ERROR: METABASE_PASSWORD environment variable not set")
        print("Set it before running: export METABASE_PASSWORD='your-password'")
        sys.exit(1)

    print("☢️  NUCLEAR CLEANUP: Deleting ALL Metabase dashboards and cards")
    print("=" * 70)

    # Authenticate
    session = requests.Session()
    auth_response = session.post(
        f"{METABASE_URL}/api/session",
        json={"username": USERNAME, "password": PASSWORD}
    )
    auth_response.raise_for_status()
    token = auth_response.json()["id"]
    session.headers["X-Metabase-Session"] = token
    print(f"✅ Authenticated to Metabase")

    # Strategy: Use multiple search terms to find all content
    search_terms = [
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
        "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        "1", "2", "3", "4", "5", "KPI", "Behavior", "Token", "Coverage",
        "Summary", "Dashboard", "Analysis", "Trends", "Compliance"
    ]

    all_dashboards = {}
    all_cards = {}

    print("\n🔍 Searching for all dashboards and cards...")
    for term in search_terms:
        try:
            search_response = session.get(f"{METABASE_URL}/api/search", params={"q": term})
            if search_response.ok:
                results = search_response.json()
                data = results.get("data", [])

                for item in data:
                    item_id = item.get("id")
                    item_name = item.get("name", "Unnamed")
                    item_model = item.get("model")

                    if item_model == "dashboard":
                        all_dashboards[item_id] = item_name
                    elif item_model == "card":
                        all_cards[item_id] = item_name
        except Exception as e:
            print(f"  ⚠️  Search error for term '{term}': {e}")
            continue

    # Delete all dashboards
    print(f"\n🗑️  Deleting {len(all_dashboards)} dashboards...")
    deleted_dashboards = 0
    for dash_id, dash_name in all_dashboards.items():
        try:
            del_response = session.delete(f"{METABASE_URL}/api/dashboard/{dash_id}")
            if del_response.status_code in (200, 204):
                print(f"  ✅ Deleted dashboard #{dash_id}: {dash_name}")
                deleted_dashboards += 1
            elif del_response.status_code == 404:
                print(f"  ⚠️  Dashboard #{dash_id} already gone")
            else:
                print(f"  ❌ Failed #{dash_id} ({dash_name}): HTTP {del_response.status_code}")
        except Exception as e:
            print(f"  ❌ Error deleting dashboard #{dash_id}: {e}")

    # Delete all cards
    print(f"\n🗑️  Deleting {len(all_cards)} cards/questions...")
    deleted_cards = 0
    for card_id, card_name in all_cards.items():
        try:
            del_response = session.delete(f"{METABASE_URL}/api/card/{card_id}")
            if del_response.status_code in (200, 204):
                print(f"  ✅ Deleted card #{card_id}: {card_name}")
                deleted_cards += 1
            elif del_response.status_code == 404:
                print(f"  ⚠️  Card #{card_id} already gone")
            else:
                print(f"  ❌ Failed #{card_id} ({card_name}): HTTP {del_response.status_code}")
        except Exception as e:
            print(f"  ❌ Error deleting card #{card_id}: {e}")

    print("\n" + "=" * 70)
    print(f"✅ Cleanup complete!")
    print(f"📊 Deleted {deleted_dashboards}/{len(all_dashboards)} dashboards")
    print(f"📇 Deleted {deleted_cards}/{len(all_cards)} cards")
    print("\n💡 Now run: python scripts/create_metabase_dashboards.py")


if __name__ == "__main__":
    main()
