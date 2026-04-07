
import os
import sys
from amprealize.auth.providers.google import GoogleOAuthProvider

# Mock env vars
os.environ["GOOGLE_CLIENT_ID"] = "test_client_id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test_client_secret"

try:
    provider = GoogleOAuthProvider(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"]
    )

    # Pass integer as redirect_uri
    url = provider.get_authorization_url(
        redirect_uri=123,
        state="test_state"
    )
    print(f"Success: {url}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
