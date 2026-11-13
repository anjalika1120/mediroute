"""Send order emails through the dedicated Gmail account using OAuth."""
import base64
from pathlib import Path
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

BACKEND = Path(__file__).resolve().parents[1]
TOKEN_FILE = BACKEND / "gmail_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def send_message(message: EmailMessage):
    token_file = TOKEN_FILE
    if not token_file.exists():
        raise FileNotFoundError(token_file)
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise RuntimeError("Gmail authorization expired. Run setup_gmail_oauth.py again.")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    session = AuthorizedSession(creds)
    response = session.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json={"raw": raw}, timeout=20)
    response.raise_for_status()
    return response.json()
