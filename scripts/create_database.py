"""
Creates:
    backend/college.db

Tables created:
    1. students        — 500 fake Indian students (17 attributes)
    2. fees            — Fee records per student
    3. attendance      — Subject-wise attendance
    4. results         — Previous semester results
    5. tickets         — Support tickets raised during calls
    6. call_summaries  — AI generated summary after every call ends
    7. otp_store       — Temporary OTP storage (cleared after use)
"""

import sqlite3
import random
import os
from faker import Faker

fake = Faker('en_IN')   # Indian locale
random.seed(42)         # Fixed seed = same 500 students every run


# PATH SETUP
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, 'backend', 'college.db')


# COLLEGE DATA POOLS
COURSES = [
    'B.Tech CSE', 'B.Tech ECE', 'B.Tech ME', 'B.Tech CE',
    'B.Tech EEE', 'BCA', 'MCA', 'MBA', 'B.Sc IT', 'B.Com'
]

DEPARTMENTS = {
    'B.Tech CSE': 'Computer Science & Engineering',
    'B.Tech ECE': 'Electronics & Communication Engineering',
    'B.Tech ME':  'Mechanical Engineering',
    'B.Tech CE':  'Civil Engineering',
    'B.Tech EEE': 'Electrical & Electronics Engineering',
    'BCA':        'Computer Applications',
    'MCA':        'Computer Applications',
    'MBA':        'Business Administration',
    'B.Sc IT':    'Information Technology',
    'B.Com':      'Commerce',
}

COURSE_CODES = {
    'B.Tech CSE': 'CS', 'B.Tech ECE': 'EC', 'B.Tech ME': 'ME',
    'B.Tech CE':  'CE', 'B.Tech EEE': 'EE', 'BCA': 'BC',
    'MCA': 'MC', 'MBA': 'MB', 'B.Sc IT': 'IT', 'B.Com': 'CM',
}

SECTIONS     = ['A', 'B', 'C', 'D']
YEARS        = [1, 2, 3, 4]
BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
CATEGORIES   = ['General', 'OBC', 'SC', 'ST', 'EWS']
STATES       = [
    'Punjab', 'Haryana', 'Uttar Pradesh', 'Delhi', 'Rajasthan',
    'Bihar', 'Madhya Pradesh', 'Maharashtra', 'Gujarat', 'Himachal Pradesh',
    'Uttarakhand', 'Jharkhand', 'West Bengal', 'Odisha', 'Karnataka'
]

SUBJECTS_BY_COURSE = {
    'B.Tech CSE': ['Maths', 'Physics', 'DSA', 'OS', 'DBMS', 'CN', 'AI', 'Java'],
    'B.Tech ECE': ['Maths', 'Physics', 'Circuits', 'Signals', 'VLSI', 'Microprocessors'],
    'B.Tech ME':  ['Maths', 'Physics', 'Thermodynamics', 'Fluid Mechanics', 'Manufacturing'],
    'B.Tech CE':  ['Maths', 'Physics', 'Structural Analysis', 'Concrete', 'Surveying'],
    'B.Tech EEE': ['Maths', 'Physics', 'Power Systems', 'Machines', 'Control Systems'],
    'BCA':        ['Maths', 'C Programming', 'DBMS', 'Web Tech', 'Networking'],
    'MCA':        ['Advanced Java', 'Software Engineering', 'Cloud Computing', 'AI'],
    'MBA':        ['Marketing', 'Finance', 'HR', 'Operations', 'Business Law'],
    'B.Sc IT':    ['Maths', 'Python', 'Web Dev', 'DBMS', 'Networking'],
    'B.Com':      ['Accountancy', 'Economics', 'Business Studies', 'Taxation'],
}

FEE_STRUCTURE = {
    'B.Tech CSE': 185000, 'B.Tech ECE': 175000, 'B.Tech ME': 160000,
    'B.Tech CE':  160000, 'B.Tech EEE': 170000, 'BCA': 95000,
    'MCA': 120000, 'MBA': 145000, 'B.Sc IT': 85000, 'B.Com': 75000,
}

# INDIAN NAME POOLS
MALE_FIRST_NAMES = [
    'Aarav', 'Arjun', 'Rohit', 'Rahul', 'Amit', 'Vikram', 'Suresh', 'Rajesh',
    'Aditya', 'Karan', 'Nikhil', 'Sanjay', 'Deepak', 'Manish', 'Ravi', 'Sachin',
    'Vishal', 'Gaurav', 'Akash', 'Harsh', 'Vivek', 'Ankit', 'Mohit', 'Abhishek',
    'Prateek', 'Yash', 'Kartik', 'Shivam', 'Tushar', 'Varun', 'Pranav', 'Sumit',
    'Kunal', 'Piyush', 'Neeraj', 'Ashish', 'Sourav', 'Tarun', 'Mayank', 'Aman',
    'Rohan', 'Dhruv', 'Ishaan', 'Parth', 'Siddharth', 'Ayush', 'Lakshay', 'Himanshu',
]

FEMALE_FIRST_NAMES = [
    'Priya', 'Sneha', 'Pooja', 'Anjali', 'Neha', 'Divya', 'Kavya', 'Riya',
    'Sakshi', 'Shreya', 'Ananya', 'Tanya', 'Simran', 'Komal', 'Nisha', 'Preeti',
    'Sonal', 'Pallavi', 'Meghna', 'Swati', 'Kritika', 'Muskan', 'Aisha', 'Deepika',
    'Radhika', 'Tanvi', 'Ankita', 'Monika', 'Shweta', 'Ruchika', 'Nidhi', 'Garima',
    'Srishti', 'Mansi', 'Bhavna', 'Payal', 'Isha', 'Sonam', 'Lavanya', 'Khushi',
    'Megha', 'Ritika', 'Saloni', 'Urvashi', 'Vandana', 'Archana', 'Chandni', 'Dimple',
]

LAST_NAMES = [
    'Sharma', 'Verma', 'Singh', 'Kumar', 'Gupta', 'Joshi', 'Patel', 'Shah',
    'Mishra', 'Yadav', 'Tiwari', 'Dubey', 'Pandey', 'Chauhan', 'Rana', 'Malik',
    'Chopra', 'Arora', 'Bhatia', 'Kapoor', 'Mehta', 'Nair', 'Reddy', 'Iyer',
    'Banerjee', 'Das', 'Chatterjee', 'Mukherjee', 'Sinha', 'Aggarwal', 'Goel',
    'Saxena', 'Srivastava', 'Shukla', 'Tripathi', 'Chaudhary', 'Rawat', 'Bisht',
    'Thakur', 'Rathore', 'Bhatt', 'Kulkarni', 'Pillai', 'Menon', 'Naidu', 'Rao',
]

def generate_indian_name(gender: str) -> tuple[str, str, str]:
    """Returns (student_name, father_name, mother_name)"""
    last         = random.choice(LAST_NAMES)
    father_last  = last
    mother_last  = random.choice(LAST_NAMES)

    if gender == 'Male':
        first        = random.choice(MALE_FIRST_NAMES)
        father_first = random.choice(MALE_FIRST_NAMES)
        mother_first = random.choice(FEMALE_FIRST_NAMES)
    else:
        first        = random.choice(FEMALE_FIRST_NAMES)
        father_first = random.choice(MALE_FIRST_NAMES)
        mother_first = random.choice(FEMALE_FIRST_NAMES)

    return (
        f"{first} {last}",
        f"{father_first} {father_last}",
        f"{mother_first} {mother_last}"
    )

# REG NUMBER GENERATOR
_used_reg_numbers = set()

def generate_reg_number(course: str, year: int) -> str:
    admission_year = 25 - year  
    while True:
        num = random.randint(10000, 99999)
        reg = f"1{admission_year:02d}{num}"
        if reg not in _used_reg_numbers:
            _used_reg_numbers.add(reg)
            return reg

# GRADE CALCULATOR
def calculate_grade(total: int) -> tuple[str, str]:
    if total >= 90: return ('A+', 'Pass')
    if total >= 80: return ('A',  'Pass')
    if total >= 70: return ('B+', 'Pass')
    if total >= 60: return ('B',  'Pass')
    if total >= 50: return ('C',  'Pass')
    if total >= 40: return ('D',  'Pass')
    return ('F', 'Backlog')

# DATABASE SCHEMA
# All 7 tables defined here
SCHEMA = """

-- Table 1: Students
CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    gender TEXT NOT NULL,
    father_name TEXT NOT NULL,
    mother_name TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    blood_group TEXT NOT NULL,
    phone TEXT NOT NULL,
    parent_phone TEXT NOT NULL,
    email TEXT NOT NULL,
    course TEXT NOT NULL,
    department TEXT NOT NULL,
    year INTEGER NOT NULL,
    section TEXT NOT NULL,
    category TEXT NOT NULL,
    state TEXT NOT NULL,
    address TEXT NOT NULL,
    hostel_taken INTEGER NOT NULL,
    hostel_room TEXT,
    scholarship INTEGER NOT NULL,
    scholarship_amount INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1
);

-- Table 2: Fees
CREATE TABLE IF NOT EXISTS fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    semester INTEGER NOT NULL,
    total_amount INTEGER NOT NULL,
    paid_amount INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    paid_date TEXT,
    status TEXT NOT NULL,
    fine_amount INTEGER DEFAULT 0,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

-- Table 3: Attendance
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    total_classes INTEGER NOT NULL,
    attended INTEGER NOT NULL,
    percentage REAL NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

-- Table 4: Results
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    semester INTEGER NOT NULL,
    subject TEXT NOT NULL,
    internal INTEGER NOT NULL,
    external INTEGER NOT NULL,
    total INTEGER NOT NULL,
    grade TEXT NOT NULL,
    result TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

-- Table 5: Tickets
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    call_id TEXT,
    category TEXT NOT NULL,
    issue TEXT NOT NULL,
    status TEXT DEFAULT 'Open',
    priority TEXT DEFAULT 'Normal',
    assigned_to TEXT DEFAULT 'Unassigned',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    admin_note TEXT,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

-- Table 6: Call Summaries
CREATE TABLE IF NOT EXISTS call_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT UNIQUE,
    student_id TEXT,
    student_name TEXT,
    call_date TEXT NOT NULL,
    call_time TEXT NOT NULL,
    call_duration TEXT,
    topics_discussed TEXT,
    full_transcript TEXT,
    ai_summary TEXT,
    action_required INTEGER DEFAULT 0,
    follow_up_notes TEXT,
    ticket_raised INTEGER DEFAULT 0,
    ticket_id INTEGER,
    otp_verified INTEGER DEFAULT 0,
    call_outcome TEXT DEFAULT 'Completed',
    admin_reviewed INTEGER DEFAULT 0,
    admin_note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
);

-- Table 7: OTP Store
CREATE TABLE IF NOT EXISTS otp_store (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL UNIQUE,
    call_id TEXT NOT NULL,
    otp_code TEXT NOT NULL,
    phone_sent TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    is_used INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    FOREIGN KEY (student_id) REFERENCES students(id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_fees_student ON fees(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_id);
CREATE INDEX IF NOT EXISTS idx_results_student ON results(student_id);
CREATE INDEX IF NOT EXISTS idx_tickets_student ON tickets(student_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_call_summaries_date ON call_summaries(call_date);
CREATE INDEX IF NOT EXISTS idx_call_action_required ON call_summaries(action_required);
CREATE INDEX IF NOT EXISTS idx_otp_student ON otp_store(student_id);

"""

# MAIN GENERATOR
def create_database():
    print(f"\n{'='*55}")
    print(" UNI AI HELPLINE — DATABASE GENERATOR")
    print(f"{'='*55}")
    print(f"  Target  : {DB_PATH}")
    print(f"  Students: 500 fake Indian students")
    print(f"{'='*55}\n")

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # Fresh start — delete old DB if exists
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("  ♻️  Removed old database.")

    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    # Create all 7 tables + indexes
    c.executescript(SCHEMA)
    print("  ✅ All 7 tables created.\n")

    # Counters 
    counts = {
        'students': 0, 'fees': 0,
        'attendance': 0, 'results': 0
    }

    print("  Generating students...")

    for i in range(500):
        # Basic info 
        course      = random.choice(COURSES)
        year        = random.choice(YEARS)
        gender      = random.choice(['Male', 'Female'])
        section     = random.choice(SECTIONS)
        category    = random.choices(
            CATEGORIES,
            weights=[50, 25, 12, 5, 8]
        )[0]
        state       = random.choice(STATES)
        blood_group = random.choice(BLOOD_GROUPS)

        # Names 
        name, father_name, mother_name = generate_indian_name(gender)

        # Registration number 
        reg_number = generate_reg_number(course, year)

        # Contact 
        phone        = '9' + ''.join([str(random.randint(0,9)) for _ in range(9)])
        parent_phone = '9' + ''.join([str(random.randint(0,9)) for _ in range(9)])
        first_name   = name.split()[0].lower()
        email        = f"{first_name}.{reg_number.lower()}@uni.co.in"

        # Date of birth (17–24 years) 
        birth_year  = random.randint(2000, 2006)
        birth_month = random.randint(1, 12)
        birth_day   = random.randint(1, 28)
        dob         = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"

        # Address 
        city    = fake.city()
        address = f"{random.randint(1,999)}, {fake.street_name()}, {city}, {state}"

        # Hostel 
        hostel_taken = 1 if random.random() < 0.55 else 0
        if hostel_taken:
            block       = random.choice(['A', 'B', 'C', 'D', 'E', 'F'])
            room_num    = random.randint(100, 499)
            hostel_room = f"Block-{block} Room-{room_num}"
        else:
            hostel_room = None

        # Scholarship 
        scholarship = 1 if random.random() < 0.3 else 0
        scholarship_amount = (
            random.choice([10000, 15000, 20000, 25000, 50000, 75000])
            if scholarship else 0
        )

        # Insert student 
        c.execute("""
            INSERT INTO students VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1
            )
        """, (
            reg_number, name, gender, father_name, mother_name,
            dob, blood_group, phone, parent_phone, email,
            course, DEPARTMENTS[course], year, section,
            category, state, address,
            hostel_taken, hostel_room,
            scholarship, scholarship_amount
        ))
        counts['students'] += 1

        # Fees 
        semester  = max(1, min((year * 2) - random.choice([0, 1]), 8))
        total_fee = FEE_STRUCTURE[course]
        if hostel_taken:
            total_fee += 60000

        fee_status = random.choices(
            ['Paid', 'Pending', 'Partial'],
            weights=[60, 25, 15]
        )[0]

        if fee_status == 'Paid':
            paid_amount = total_fee
            paid_date   = f"2025-{random.randint(1,2):02d}-{random.randint(1,28):02d}"
            fine_amount = 0
        elif fee_status == 'Partial':
            paid_amount = random.randint(total_fee // 3, total_fee - 1)
            paid_date   = None
            fine_amount = 500
        else:
            paid_amount = 0
            paid_date   = None
            fine_amount = random.choice([0, 500, 1000, 1500])

        c.execute("""
            INSERT INTO fees
            (student_id, semester, total_amount, paid_amount,
             due_date, paid_date, status, fine_amount)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            reg_number, semester, total_fee, paid_amount,
            '2025-03-31', paid_date, fee_status, fine_amount
        ))
        counts['fees'] += 1

        # Attendance 
        subjects = SUBJECTS_BY_COURSE.get(course, ['Maths', 'English', 'Physics'])
        for subject in subjects:
            total_classes = random.randint(40, 60)
            att_type = random.choices(
                ['excellent', 'good', 'warning', 'short'],
                weights=[30, 40, 20, 10]
            )[0]

            if att_type == 'excellent':
                pct = random.uniform(88, 100)
            elif att_type == 'good':
                pct = random.uniform(75, 88)
            elif att_type == 'warning':
                pct = random.uniform(65, 75)
            else:
                pct = random.uniform(45, 65)

            attended   = int(total_classes * pct / 100)
            percentage = round((attended / total_classes) * 100, 1)
            att_status = (
                'Safe'    if percentage >= 75 else
                'Warning' if percentage >= 65 else
                'Short'
            )

            c.execute("""
                INSERT INTO attendance
                (student_id, subject, total_classes, attended, percentage, status)
                VALUES (?,?,?,?,?,?)
            """, (reg_number, subject, total_classes, attended, percentage, att_status))
            counts['attendance'] += 1

        #  Results (only for year 2+ students) 
        if year > 1:
            prev_semester = max(1, semester - 1)
            for subject in subjects:
                internal = random.randint(20, 40)
                external = random.randint(20, 60)
                total    = internal + external
                grade, result = calculate_grade(total)

                c.execute("""
                    INSERT INTO results
                    (student_id, semester, subject, internal, external, total, grade, result)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    reg_number, prev_semester, subject,
                    internal, external, total, grade, result
                ))
                counts['results'] += 1

        # Progress
        if (i + 1) % 100 == 0:
            print(f"  ⏳ {i+1}/500 students done...")

    conn.commit()
    conn.close()

    # Summary
    db_size = os.path.getsize(DB_PATH) / 1024

    print("\nDatabase created successfully.")
    print(f"Location : {DB_PATH}")
    print(f"Size     : {db_size:.1f} KB")

    print(f"\nStudents   : {counts['students']}")
    print(f"Fees       : {counts['fees']}")
    print(f"Attendance : {counts['attendance']}")
    print(f"Results    : {counts['results']}")

    print("\nNext step:")
    print("Run verify_database.py (optional)")


if __name__ == "__main__":
    create_database()
