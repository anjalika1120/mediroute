"""Send MediRoute mail through Gmail SMTP using a Google App Password."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def send_message(message: EmailMessage, *, smtp_user: str, password: str) -> None:
    message["From"] = f"MediRoute <{smtp_user}>"
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(smtp_user, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_user, password)
            server.send_message(message)
