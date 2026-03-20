"""
otp_helper.py
Sends OTP via Twilio SMS for student identity verification.

Flow:
  1. Student asks for personal data (fees/attendance)
  2. AI asks for registration number
  3. Student gives reg number
  4. Backend calls send_otp() → SMS sent to student's phone
  5. Student speaks OTP during call
  6. Backend calls verify_otp_code() → verified or rejected
"""

import os
import random
import logging
from twilio.rest import Client
from backend.database import get_student, save_otp, verify_otp

logger = logging.getLogger("helpline.otp_helper")

# Load credentials from environment
ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "+13185965065")


def _get_client() -> Client:
    """Returns Twilio client instance."""
    return Client(ACCOUNT_SID, AUTH_TOKEN)


def send_otp(student_reg: str, call_sid: str) -> tuple[bool, str]:
    """
    Generate and send OTP to student's registered phone.

    Args:
        student_reg: Registration number e.g. "2024EC033"
        call_sid:    Twilio CallSid for this call

    Returns:
        (True, phone_number)  — OTP sent successfully
        (False, error_reason) — Failed to send

    Example:
        success, info = send_otp("2024EC033", "CAxxxxxx")
        if success:
            # Tell student to speak the OTP
        else:
            # Handle error
    """
    # Find student in DB
    student = get_student(student_reg)
    if not student:
        logger.warning(f"[OTP] Student not found: {student_reg}")
        return False, "student_not_found"

    phone = student.get("phone")
    if not phone:
        logger.warning(f"[OTP] No phone for: {student_reg}")
        return False, "no_phone"

    # Generate 6-digit OTP
    otp_code = str(random.randint(100000, 999999))

    # Save to DB
    saved = save_otp(
        student_id=student_reg,
        call_id=call_sid,
        otp_code=otp_code,
        phone_sent=phone
    )
    if not saved:
        logger.error(f"[OTP] DB save failed for {student_reg}")
        return False, "db_error"

    # Send SMS
    try:
        client = _get_client()
        message = client.messages.create(
            body=f"Your college helpline OTP is: {otp_code}. Valid for 5 minutes. Do not share.",
            from_=TWILIO_NUMBER,
            to=f"+91{phone}"  # India country code
        )
        logger.info(f"[OTP] Sent to +91{phone} — SID: {message.sid}")
        return True, phone

    except Exception as e:
        logger.error(f"[OTP] SMS failed: {e}")
        return False, "sms_failed"


def verify_otp_code(student_reg: str, entered_otp: str) -> tuple[bool, str]:
    """
    Verify OTP entered by student.

    Args:
        student_reg:  Registration number
        entered_otp:  OTP spoken by student

    Returns:
        (True, "verified")      — correct
        (False, "wrong")        — incorrect
        (False, "expired")      — OTP expired
        (False, "max_attempts") — too many tries

    Example:
        success, reason = verify_otp_code("2024EC033", "123456")
    """
    # Clean OTP — STT adds spaces sometimes
    clean_otp = entered_otp.strip().replace(" ", "")

    success, reason = verify_otp(student_reg, clean_otp)

    if success:
        logger.info(f"[OTP] Verified for {student_reg}")
    else:
        logger.warning(f"[OTP] Failed for {student_reg} — {reason}")

    return success, reason


def get_otp_message(reason: str) -> str:
    """
    Returns voice message based on OTP result.

    Args:
        reason: Result from verify_otp_code()

    Returns:
        Text to speak to student
    """
    messages = {
        "verified":          "Identity verified. Let me fetch your information.",
        "wrong":             "That OTP was incorrect. Please try again.",
        "expired":           "Your OTP has expired. Please request a new one.",
        "max_attempts":      "Too many incorrect attempts. Please call back.",
        "not_found":         "No OTP found. Please request a new one.",
        "student_not_found": "Registration number not found in our system.",
        "sms_failed":        "Could not send OTP. Please try again.",
        "db_error":          "System error. Please try again.",
    }
    return messages.get(reason, "Something went wrong. Please try again.")
