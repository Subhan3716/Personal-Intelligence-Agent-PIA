from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from config import GOOGLE_AUTH_CREDENTIALS_PATH, GOOGLE_OAUTH_SCOPES, GOOGLE_OAUTH_TOKEN_JSON


def main() -> int:
    credentials_path = Path(GOOGLE_AUTH_CREDENTIALS_PATH).expanduser()
    token_path = Path(GOOGLE_OAUTH_TOKEN_JSON).expanduser()

    if not credentials_path.exists():
        print(f"[PIA] Missing OAuth client credentials file: {credentials_path}")
        print("[PIA] Put your Google client JSON there, then run this script again.")
        return 1

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes=GOOGLE_OAUTH_SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    except Exception as exc:
        print(f"[PIA] Google OAuth setup failed: {exc}")
        return 1

    try:
        token_path.write_text(creds.to_json(), encoding="utf-8")
    except Exception as exc:
        print(f"[PIA] Could not save token file `{token_path}`: {exc}")
        return 1

    print(f"[PIA] Google OAuth token saved to: {token_path}")
    print("[PIA] Reopen the app and click Refresh Connectivity.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
