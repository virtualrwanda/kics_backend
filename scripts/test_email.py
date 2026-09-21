"""
Test SMTP connection to KICS mail server.
Run: python scripts/test_email.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from app.core.config import settings


async def test_smtp():
    print("=" * 60)
    print("📧 Testing KICS SMTP Connection")
    print("=" * 60)
    print(f"Server:   {settings.MAIL_SERVER}:{settings.MAIL_PORT}")
    print(f"Username: {settings.MAIL_USERNAME}")
    print(f"From:     {settings.MAIL_FROM}")
    print(f"SSL:      {settings.MAIL_SSL_TLS}, STARTTLS: {settings.MAIL_STARTTLS}")
    print("=" * 60)

    conf = ConnectionConfig(
        MAIL_USERNAME=settings.MAIL_USERNAME,
        MAIL_PASSWORD=settings.MAIL_PASSWORD,
        MAIL_FROM=settings.MAIL_FROM,
        MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
        MAIL_PORT=settings.MAIL_PORT,
        MAIL_SERVER=settings.MAIL_SERVER,
        MAIL_STARTTLS=settings.MAIL_STARTTLS,
        MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
        USE_CREDENTIALS=settings.MAIL_USE_CREDENTIALS,
        VALIDATE_CERTS=True,
    )

    fm = FastMail(conf)

    # Ask recipient
    recipient = input("\n📬 Enter recipient email (e.g., your personal email): ").strip()
    if not recipient:
        print("❌ No recipient provided")
        return

    print(f"\n📤 Sending test email to {recipient}...")

    try:
        message = MessageSchema(
            subject="✅ KICS Help Desk — SMTP Test",
            recipients=[recipient],
            body="""
            <h2>SMTP Test Successful!</h2>
            <p>If you're reading this, your KICS email integration is working.</p>
            <p>— KICS IT Help Desk</p>
            """,
            subtype=MessageType.html,
        )
        await fm.send_message(message)
        print("✅ Email sent successfully!")
        print(f"   Check inbox at: {recipient}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        print("\n🔍 Troubleshooting:")
        print("  1. Check MAIL_PASSWORD in .env is correct")
        print("  2. Check MAIL_PORT=465 and MAIL_SSL_TLS=True")
        print("  3. Try from a different network (some ISPs block SMTP)")
        print("  4. Check with your hosting provider that SMTP is enabled")


if __name__ == "__main__":
    asyncio.run(test_smtp())