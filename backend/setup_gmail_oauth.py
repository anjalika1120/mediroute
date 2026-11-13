"""Authorize MediRoute to send mail from the dedicated Gmail account."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parent
CLIENT = ROOT / "google_oauth_client.json"
TOKEN = ROOT / "gmail_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

if not CLIENT.is_file():
    raise SystemExit("Download the OAuth Desktop app client JSON from Google Cloud and save it as backend/google_oauth_client.json")
credentials = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES).run_local_server(port=0, access_type="offline", prompt="consent")
TOKEN.write_text(credentials.to_json(), encoding="utf-8")
print(f"Gmail OAuth token saved to {TOKEN}. Keep this file private.")
