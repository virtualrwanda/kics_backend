"""
Email service for KICS IT Help Desk.
Handles SMTP delivery and provides all email templates.
"""

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr
from typing import List
import logging

from ..core.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# SMTP CONFIGURATION (KICS vrt.rw — port 465 SSL)
# ============================================================
conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_FROM_NAME=getattr(settings, "MAIL_FROM_NAME", "KICS IT Help Desk"),
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=getattr(settings, "MAIL_USE_CREDENTIALS", True),
    VALIDATE_CERTS=True,
    TIMEOUT=30,
)

fm = FastMail(conf)


# ============================================================
# CORE SEND FUNCTION
# ============================================================
async def send_email(
    recipients: List[EmailStr],
    subject: str,
    body: str,
    html: bool = True,
) -> bool:
    """Send an email. Returns True on success, False on failure."""
    try:
        message = MessageSchema(
            subject=subject,
            recipients=recipients,
            body=body,
            subtype=MessageType.html if html else MessageType.plain,
        )
        await fm.send_message(message)
        logger.info(f"✉️  Email sent to {recipients}: {subject}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send email to {recipients}: {e}")
        return False


# ============================================================
# BASE HTML TEMPLATE
# ============================================================
def _base_template(title: str, content: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px; margin: 0; }}
            .container {{ max-width: 600px; margin: auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .header {{ background: #1e3a8a; color: white; padding: 24px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 22px; }}
            .content {{ padding: 32px; color: #333; line-height: 1.6; }}
            .button {{ display: inline-block; background: #f97316; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 16px 0; }}
            .footer {{ background: #f9fafb; padding: 16px; text-align: center; font-size: 12px; color: #666; }}
            code {{ background: #f3f4f6; padding: 4px 8px; border-radius: 4px; font-family: 'Courier New', monospace; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎧 KICS IT Help Desk</h1>
            </div>
            <div class="content">
                <h2>{title}</h2>
                {content}
            </div>
            <div class="footer">
                This is an automated message from KICS IT Help Desk. Please do not reply.
            </div>
        </div>
    </body>
    </html>
    """


# ============================================================
# EMAIL TEMPLATES
# ============================================================
def verification_email_template(full_name: str, verify_url: str) -> str:
    content = f"""
        <p>Hello <strong>{full_name}</strong>,</p>
        <p>Thank you for registering on the KICS IT Help Desk system.</p>
        <p>Please verify your email address by clicking the button below:</p>
        <p style="text-align: center;">
            <a href="{verify_url}" class="button">Verify Email</a>
        </p>
        <p>Or copy this link into your browser:</p>
        <p style="word-break: break-all; font-size: 13px; color: #555;">{verify_url}</p>
        <p>This link expires in <strong>24 hours</strong>.</p>
        <p>If you did not register, you can ignore this email.</p>
    """
    return _base_template("Verify Your Email", content)


def password_reset_email_template(full_name: str, reset_url: str) -> str:
    content = f"""
        <p>Hello <strong>{full_name}</strong>,</p>
        <p>We received a request to reset your password.</p>
        <p>Click the button below to set a new password:</p>
        <p style="text-align: center;">
            <a href="{reset_url}" class="button">Reset Password</a>
        </p>
        <p>Or copy this link into your browser:</p>
        <p style="word-break: break-all; font-size: 13px; color: #555;">{reset_url}</p>
        <p><strong>This link expires in 30 minutes.</strong></p>
        <p>If you did not request a password reset, please ignore this email — your password is safe.</p>
    """
    return _base_template("Reset Your Password", content)


def magic_link_email_template(full_name: str, login_url: str) -> str:
    content = f"""
        <p>Hello <strong>{full_name}</strong>,</p>
        <p>Click the button below to log into the KICS IT Help Desk:</p>
        <p style="text-align: center;">
            <a href="{login_url}" class="button">Log In</a>
        </p>
        <p>Or copy this link into your browser:</p>
        <p style="word-break: break-all; font-size: 13px; color: #555;">{login_url}</p>
        <p><strong>This link expires in 15 minutes and can only be used once.</strong></p>
        <p>If you did not request this link, you can safely ignore this email.</p>
    """
    return _base_template("Your Login Link", content)


def otp_email_template(full_name: str, code: str, purpose: str = "login") -> str:
    """OTP verification email (2FA)."""
    purpose_text = {
        "login_2fa": "sign in to your KICS Help Desk account",
        "email_verify": "verify your email address",
        "password_reset": "reset your password",
        "magic_link": "log in",
    }.get(purpose, "continue")

    content = f"""
        <p>Hello <strong>{full_name}</strong>,</p>
        <p>Use this code to {purpose_text}:</p>
        <div style="text-align: center; margin: 32px 0;">
            <div style="
                display: inline-block;
                background: #f3f4f6;
                padding: 20px 40px;
                border-radius: 8px;
                font-size: 36px;
                font-weight: bold;
                letter-spacing: 8px;
                color: #1e3a8a;
                font-family: 'Courier New', monospace;
            ">
                {code}
            </div>
        </div>
        <p style="text-align: center; font-size: 16px;">
            This code expires in <strong>5 minutes</strong>.
        </p>
        <p style="color: #888; font-size: 13px;">
            If you didn't request this, please ignore this email — your account is safe.
        </p>
    """
    return _base_template("Your Verification Code", content)

def csat_survey_email_template(
    full_name: str,
    ticket_number: str,
    ticket_title: str,
    technician_name: str,
    rate_url: str,
) -> str:
    content = f"""
        <p>Hello <strong>{full_name}</strong>,</p>
        <p>Your support ticket has been closed. We'd love to hear how we did!</p>

        <div style="background: #f9fafb; padding: 16px; border-radius: 6px; margin: 16px 0; border-left: 4px solid #1e3a8a;">
            <p style="margin: 0;"><strong>Ticket:</strong> {ticket_number}</p>
            <p style="margin: 4px 0;"><strong>Subject:</strong> {ticket_title}</p>
            <p style="margin: 4px 0;"><strong>Handled by:</strong> {technician_name}</p>
        </div>

        <p>Please take 10 seconds to rate your experience:</p>

        <p style="text-align: center; font-size: 32px; letter-spacing: 4px;">
            ⭐ ⭐ ⭐ ⭐ ⭐
        </p>

        <p style="text-align: center;">
            <a href="{rate_url}" class="button">Rate Your Experience</a>
        </p>

        <p>Or copy this link:<br>
        <span style="word-break:break-all;font-size:13px;color:#555;">{rate_url}</span></p>

        <p>Thank you for helping us improve!</p>
    """
    return _base_template("How did we do?", content)