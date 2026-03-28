"""
All functions:
    get_connection()         — returns DB connection
    get_student()            — find student by reg number
    get_fee_status()         — get fee info
    get_attendance()         — get subject-wise attendance
    get_results()            — get semester results
    create_ticket()          — raise a support ticket
    save_call_summary()      — save call summary after call ends
    get_all_tickets()        — all tickets for dashboard
    close_ticket()           — admin closes a ticket
    get_dashboard_stats()    — counts for dashboard cards
    get_call_summaries()     — all call summaries for dashboard
    mark_call_reviewed()     — admin reviewed a call summary
    get_pending_followups()  — all unresolved action items
"""

import sqlite3
import os
import logging
import json
from datetime import datetime
from typing import Optional

logger = logging.getLogger("helpline.database")

# DB PATH
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, 'backend', 'college.db')


# CONNECTION HELPER
def get_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. "
            f"Run: python scripts/create_database.py"
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _query(sql: str, params: tuple = ()) -> list[dict]:
    """
    Internal helper — run a SELECT query, return list of dicts.
    Automatically opens and closes connection.
    """
    try:
        conn = get_connection()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"[DB] Query error: {e} | SQL: {sql[:80]}")
        return []


def _execute(sql: str, params: tuple = ()) -> Optional[int]:
    """
    Internal helper — run INSERT/UPDATE/DELETE.
    Returns lastrowid (useful for getting ID of inserted row).
    Returns None on error.
    """
    try:
        conn = get_connection()
        cursor = conn.execute(sql, params)
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        return last_id
    except Exception as e:
        logger.error(f"[DB] Execute error: {e} | SQL: {sql[:80]}")
        return None


# STUDENT FUNCTIONS
def get_student(reg_number: str) -> Optional[dict]:
    """
    Find a student by registration number.

    Args:
        reg_number: e.g. "12345678"

    Returns:
        dict with all student info, or None if not found.

    Example:
        student = get_student("12345678")
        if student:
            print(student['name'])     # "Rohit Sharma"
            print(student['course'])   # "B.Tech CSE"
            print(student['phone'])    # "9876543210"
    """
    reg_number = reg_number.strip().upper()
    rows = _query(
        "SELECT * FROM students WHERE id = ? AND is_active = 1",
        (reg_number,)
    )

    if not rows:
        logger.info(f"[DB] Student not found: {reg_number}")
        return None

    logger.info(f"[DB] Student found: {reg_number} — {rows[0]['name']}")
    return rows[0]


def search_student_by_name(name: str) -> list[dict]:
    """
    Search students by partial name match.
    Useful for admin dashboard search.

    Args:
        name: partial name e.g. "Rohit"

    Returns:
        List of matching students (max 10)
    """
    return _query(
        "SELECT id, name, course, year, phone FROM students "
        "WHERE name LIKE ? AND is_active = 1 LIMIT 10",
        (f"%{name}%",)
    )


# FEE FUNCTIONS

def get_fee_status(reg_number: str) -> Optional[dict]:
    """
    Get fee status for a student.

    Returns:
        {
            student_id, semester, total_amount, paid_amount,
            due_date, paid_date, status, fine_amount,
            balance  ← calculated field (total - paid)
        }

    Example:
        fee = get_fee_status("12345678")
        print(fee['status'])       # "Pending"
        print(fee['total_amount']) # 185000
        print(fee['balance'])      # 185000 (unpaid)
    """
    rows = _query(
        "SELECT * FROM fees WHERE student_id = ? "
        "ORDER BY semester DESC LIMIT 1",
        (reg_number.upper(),)
    )

    if not rows:
        return None

    fee = rows[0]
    fee['balance'] = fee['total_amount'] - fee['paid_amount']   # Add calculated field
    return fee


def get_fee_summary_text(reg_number: str) -> str:
    """
    Returns a ready-to-speak fee summary string.
    Used directly by the AI model as context.

    Example output:
        "Semester 4 fee: Rs.185000. Paid: Rs.0. Balance: Rs.185000.
         Status: Pending. Due date: March 31, 2025. Fine: Rs.500."
    """
    fee = get_fee_status(reg_number)
    if not fee:
        return "Fee records not found for this student."

    lines = [
        f"Semester {fee['semester']} fee: Rs.{fee['total_amount']}.",
        f"Paid: Rs.{fee['paid_amount']}.",
        f"Balance: Rs.{fee['balance']}.",
        f"Status: {fee['status']}.",
        f"Due date: {fee['due_date']}.",
    ]
    if fee['fine_amount'] > 0:
        lines.append(f"Late fine: Rs.{fee['fine_amount']}.")

    return " ".join(lines)


# ATTENDANCE FUNCTIONS

def get_attendance(reg_number: str) -> list[dict]:
    """
    Get subject-wise attendance for a student.

    Returns:
        List of dicts:
        [
            { subject: "Maths", percentage: 82.5, status: "Safe", ... },
            { subject: "Physics", percentage: 63.0, status: "Short", ... },
        ]
    """
    return _query(
        "SELECT subject, total_classes, attended, percentage, status "
        "FROM attendance WHERE student_id = ? "
        "ORDER BY percentage ASC",   # Lowest first — most important to see
        (reg_number.upper(),)
    )


def get_attendance_summary_text(reg_number: str) -> str:
    """
    Returns a ready-to-speak attendance summary.
    Used directly by AI model as context.

    Example output:
        "Attendance summary — Physics: 63.0% (Short),
         CN: 71.2% (Warning), Maths: 82.5% (Safe).
         2 subjects below 75%."
    """
    records = get_attendance(reg_number)
    if not records:
        return "Attendance records not found."

    parts = []
    short_count   = 0
    warning_count = 0

    for r in records:
        parts.append(f"{r['subject']}: {r['percentage']}% ({r['status']})")
        if r['status'] == 'Short':
            short_count += 1
        elif r['status'] == 'Warning':
            warning_count += 1

    summary = "Attendance — " + ", ".join(parts) + "."

    if short_count > 0:
        summary += f" {short_count} subject(s) are SHORT (below 65%) — detention risk."
    if warning_count > 0:
        summary += f" {warning_count} subject(s) are in WARNING zone (65-75%)."

    return summary


# RESULTS FUNCTIONS

def get_results(reg_number: str, semester: Optional[int] = None) -> list[dict]:
    """
    Get semester results for a student.

    Args:
        reg_number: Student ID
        semester: Specific semester, or None for latest

    Returns:
        List of subject results with grades
    """
    if semester:
        return _query(
            "SELECT * FROM results WHERE student_id = ? AND semester = ? "
            "ORDER BY subject",
            (reg_number.upper(), semester)
        )
    else:
        # Latest semester
        return _query(
            "SELECT * FROM results WHERE student_id = ? "
            "AND semester = (SELECT MAX(semester) FROM results WHERE student_id = ?) "
            "ORDER BY subject",
            (reg_number.upper(), reg_number.upper())
        )


def get_results_summary_text(reg_number: str) -> str:
    """
    Returns a ready-to-speak results summary.

    Example output:
        "Semester 3 results — Maths: 78/100 B+ (Pass),
         Physics: 45/100 D (Pass), DSA: 32/100 F (Backlog).
         1 backlog subject."
    """
    results = get_results(reg_number)
    if not results:
        return "Results not found. They may not have been declared yet."

    parts      = []
    backlogs   = 0
    semester   = results[0]['semester'] if results else "?"

    for r in results:
        parts.append(f"{r['subject']}: {r['total']}/100 {r['grade']} ({r['result']})")
        if r['result'] == 'Backlog':
            backlogs += 1

    summary = f"Semester {semester} results — " + ", ".join(parts) + "."

    if backlogs > 0:
        summary += f" {backlogs} backlog subject(s) — reappear exam required."
    else:
        summary += " No backlogs."

    return summary


# TICKET FUNCTIONS

def create_ticket(
    student_id: str,
    issue: str,
    call_id: str = None,
    category: str = "other",
    priority: str = "Normal"
) -> Optional[int]:
    # Auto-detect category from issue text if not provided
    if category == "other":
        issue_lower = issue.lower()
        if any(w in issue_lower for w in ['fee', 'payment', 'challan']):
            category = "fees"
        elif any(w in issue_lower for w in ['hostel', 'room', 'mess', 'warden']):
            category = "hostel"
        elif any(w in issue_lower for w in ['exam', 'result', 'marks', 'grade']):
            category = "exam"
        elif any(w in issue_lower for w in ['attendance', 'absent', 'leave']):
            category = "attendance"
        elif any(w in issue_lower for w in ['certificate', 'document', 'tc', 'bonafide']):
            category = "document"

    # Map category to department
    dept_map = {
        "fees":       "Accounts Department",
        "hostel":     "Hostel Administration",
        "exam":       "Examination Cell",
        "attendance": "Academic Department",
        "document":   "Admin Office",
        "other":      "Student Affairs",
    }
    assigned_to = dept_map.get(category, "Student Affairs")

    ticket_id = _execute(
        """INSERT INTO tickets
           (student_id, call_id, category, issue, priority, assigned_to)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (student_id.upper(), call_id, category, issue, priority, assigned_to)
    )

    if ticket_id:
        logger.info(f"[DB] Ticket #{ticket_id} created for {student_id} — {category}")
    return ticket_id


def close_ticket(ticket_id: int, admin_note: str = "") -> bool:
    try: 
        conn = get_connection()
        cursor = conn.execute(
            """UPDATE tickets
               SET status = 'Closed',
                   resolved_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP,
                   admin_note = ?
               WHERE id = ?""",
            (admin_note, ticket_id)
        )
        conn.commit()
        rows_affected = cursor.rowcount
        conn.close()
        
        if rows_affected == 0:
            logger.warning(f"[DB] close_ticket — Ticket #{ticket_id} not found")
            return False
            
        logger.info(f"[DB] Ticket #{ticket_id} closed")
        return True
        
    except Exception as e:
        logger.error(f"[DB] close_ticket error: {e}")
        return False


def get_all_tickets(status: str = None, limit: int = 50) -> list[dict]:
    """
    Get tickets for admin dashboard.

    Args:
        status: 'Open' / 'In Progress' / 'Closed' / None (all)
        limit:  Max tickets to return

    Returns:
        List of ticket dicts with student name joined
    """
    if status:
        return _query(
            """SELECT t.*, s.name as student_name, s.course, s.phone
               FROM tickets t
               LEFT JOIN students s ON t.student_id = s.id
               WHERE t.status = ?
               ORDER BY t.created_at DESC LIMIT ?""",
            (status, limit)
        )
    else:
        return _query(
            """SELECT t.*, s.name as student_name, s.course, s.phone
               FROM tickets t
               LEFT JOIN students s ON t.student_id = s.id
               ORDER BY t.created_at DESC LIMIT ?""",
            (limit,)
        )


# CALL SUMMARY FUNCTIONS

def save_call_summary(
    call_id: str,
    student_id: Optional[str],
    student_name: Optional[str],
    topics_discussed: list[str],
    full_transcript: str,
    ai_summary: str,
    action_required: bool,
    follow_up_notes: str,
    ticket_raised: bool,
    ticket_id: Optional[int],
    call_duration: str,
    otp_verified: bool,
    call_outcome: str = "Completed"
) -> Optional[int]:
    """
    Save AI-generated call summary after every call ends.
    Called automatically from /call-end Twilio webhook.

    Args:
        call_id:          Twilio CallSid (unique per call)
        student_id:       Reg number (None if not verified)
        student_name:     For quick dashboard display
        topics_discussed: List e.g. ["fees", "attendance"]
        full_transcript:  Complete conversation text
        ai_summary:       3-4 line AI generated summary
        action_required:  True if follow up needed
        follow_up_notes:  What needs to be done
        ticket_raised:    True if a ticket was created
        ticket_id:        Ticket ID if raised
        call_duration:    e.g. "3 mins 42 secs"
        otp_verified:     True if student verified OTP
        call_outcome:     Completed / Dropped / Failed

    Returns:
        summary_id if saved, None if failed
    """
    now       = datetime.now()
    call_date = now.strftime("%Y-%m-%d")
    call_time = now.strftime("%H:%M:%S")

    # Convert topics list to JSON string for storage
    topics_json = json.dumps(topics_discussed)

    summary_id = _execute(
        """INSERT OR REPLACE INTO call_summaries
           (call_id, student_id, student_name, call_date, call_time,
            call_duration, topics_discussed, full_transcript, ai_summary,
            action_required, follow_up_notes, ticket_raised, ticket_id,
            otp_verified, call_outcome)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            call_id,
            student_id.upper() if student_id else None,
            student_name,
            call_date,
            call_time,
            call_duration,
            topics_json,
            full_transcript,
            ai_summary,
            1 if action_required else 0,
            follow_up_notes,
            1 if ticket_raised else 0,
            ticket_id,
            1 if otp_verified else 0,
            call_outcome
        )
    )

    if summary_id:
        logger.info(
            f"[DB] Call summary saved — call_id={call_id} "
            f"student={student_id} action_required={action_required}"
        )
    return summary_id


def get_call_summaries(
    date: str = None,
    action_required_only: bool = False,
    limit: int = 50
) -> list[dict]:
    """
    Get call summaries for admin dashboard.

    Args:
        date:                 Filter by date 'YYYY-MM-DD' (None = all)
        action_required_only: Only show calls needing follow up
        limit:                Max records to return

    Returns:
        List of call summary dicts (topics_discussed parsed back to list)
    """
    conditions = []
    params     = []

    if date:
        conditions.append("call_date = ?")
        params.append(date)

    if action_required_only:
        conditions.append("action_required = 1")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = _query(
        f"""SELECT * FROM call_summaries
            {where}
            ORDER BY created_at DESC LIMIT ?""",
        tuple(params) + (limit,)
    )

    # Parse topics JSON back to list
    for row in rows:
        try:
            row['topics_discussed'] = json.loads(row['topics_discussed'] or "[]")
        except Exception:
            row['topics_discussed'] = []

    return rows


def mark_call_reviewed(summary_id: int, admin_note: str = "") -> bool:
    """Admin marks a call summary as reviewed."""
    result = _execute(
        """UPDATE call_summaries
           SET admin_reviewed = 1, admin_note = ?
           WHERE id = ?""",
        (admin_note, summary_id)
    )
    return result is not None


def get_pending_followups() -> list[dict]:
    """
    Get all calls that need follow up and are not yet reviewed.
    Used for admin dashboard alert section.
    """
    rows = _query(
        """SELECT cs.*, s.phone as student_phone
           FROM call_summaries cs
           LEFT JOIN students s ON cs.student_id = s.id
           WHERE cs.action_required = 1
           AND cs.admin_reviewed = 0
           ORDER BY cs.created_at DESC"""
    )

    for row in rows:
        try:
            row['topics_discussed'] = json.loads(row['topics_discussed'] or "[]")
        except Exception:
            row['topics_discussed'] = []

    return rows


# OTP FUNCTIONS

def save_otp(
    student_id: str,
    call_id: str,
    otp_code: str,
    phone_sent: str
) -> bool:
    """
    Save OTP to database.
    OTP expires in 5 minutes automatically.

    Returns True if saved, False if failed.
    """
    # Delete any existing OTP for this student first
    _execute("DELETE FROM otp_store WHERE student_id = ?", (student_id.upper(),))

    result = _execute(
        """INSERT INTO otp_store
           (student_id, call_id, otp_code, phone_sent, expires_at)
           VALUES (?, ?, ?, ?,
           datetime('now', '+5 minutes'))""",
        (student_id.upper(), call_id, otp_code, phone_sent)
    )
    return result is not None


def verify_otp(student_id: str, entered_otp: str) -> tuple[bool, str]:
    """
    Verify OTP entered by student.

    Returns:
        (True, "verified")     — correct OTP
        (False, "expired")     — OTP expired
        (False, "wrong")       — wrong OTP
        (False, "not_found")   — no OTP exists
        (False, "max_attempts")— tried too many times

    Usage:
        success, reason = verify_otp("2024CS001", "123456")
        if success:
            # proceed with verified session
        else:
            # handle reason
    """
    rows = _query(
        "SELECT * FROM otp_store WHERE student_id = ? AND is_used = 0",
        (student_id.upper(),)
    )

    if not rows:
        return False, "not_found"

    otp_record = rows[0]

    # Check max attempts (3 tries allowed)
    if otp_record['attempts'] >= 3:
        _execute("DELETE FROM otp_store WHERE student_id = ?", (student_id.upper(),))
        return False, "max_attempts"

    # Check expiry
    rows_expired = _query(
        "SELECT 1 FROM otp_store WHERE student_id = ? "
        "AND expires_at < datetime('now')",
        (student_id.upper(),)
    )
    if rows_expired:
        _execute("DELETE FROM otp_store WHERE student_id = ?", (student_id.upper(),))
        return False, "expired"

    # Increment attempts
    _execute(
        "UPDATE otp_store SET attempts = attempts + 1 WHERE student_id = ?",
        (student_id.upper(),)
    )

    # Check OTP
    if otp_record['otp_code'] == entered_otp.strip():
        # Mark as used — one time only
        _execute(
            "UPDATE otp_store SET is_used = 1 WHERE student_id = ?",
            (student_id.upper(),)
        )
        logger.info(f"[DB] OTP verified for {student_id}")
        return True, "verified"

    logger.warning(f"[DB] Wrong OTP for {student_id} — attempt {otp_record['attempts']}")
    return False, "wrong"


def cleanup_expired_otps() -> int:
    """
    Delete all expired OTPs from database.
    Call this periodically (e.g. every hour).
    Returns number of deleted records.
    """
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM otp_store WHERE expires_at < datetime('now') OR is_used = 1"
    )
    conn.commit()
    count = cursor.rowcount
    conn.close()
    if count > 0:
        logger.info(f"[DB] Cleaned up {count} expired OTPs")
    return count



# DASHBOARD STATS

def get_dashboard_stats() -> dict:
    """
    Returns all counts needed for admin dashboard cards.

    Returns:
        {
            total_students,
            total_tickets,
            open_tickets,
            calls_today,
            pending_followups,
            fees_pending_count
        }
    """
    today = datetime.now().strftime("%Y-%m-%d")

    total_students    = _query("SELECT COUNT(*) as c FROM students WHERE is_active=1")[0]['c']
    total_tickets     = _query("SELECT COUNT(*) as c FROM tickets")[0]['c']
    open_tickets      = _query("SELECT COUNT(*) as c FROM tickets WHERE status='Open'")[0]['c']
    calls_today       = _query("SELECT COUNT(*) as c FROM call_summaries WHERE call_date=?", (today,))[0]['c']
    pending_followups = _query("SELECT COUNT(*) as c FROM call_summaries WHERE action_required=1 AND admin_reviewed=0")[0]['c']
    fees_pending      = _query("SELECT COUNT(*) as c FROM fees WHERE status IN ('Pending','Partial')")[0]['c']

    return {
        "total_students":    total_students,
        "total_tickets":     total_tickets,
        "open_tickets":      open_tickets,
        "calls_today":       calls_today,
        "pending_followups": pending_followups,
        "fees_pending_count": fees_pending,
    }
