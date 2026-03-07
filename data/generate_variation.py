import csv

# Greeting styles (real phone behaviour)
greetings = [
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "uh hello",
    "hello there",
    "hi support",
    "hello helpline",
]

# Ways students ask
actions = [
    "can you check",
    "please check",
    "tell me",
    "show me",
    "i want to know",
    "check",
    "let me know",
    "can you tell",
    "please tell",
]

# Topics students ask about
topics = [

    "my fee status",
    "my pending fee",
    "fee payment details",

    "my attendance",
    "attendance percentage",
    "attendance shortage",

    "exam timetable",
    "exam date",
    "exam result",

    "scholarship status",
    "scholarship payment",
    "scholarship eligibility",

    "hostel allotment",
    "hostel room",
    "hostel complaint",

    "document request",
    "bonafide certificate",
    "transfer certificate",

    "admission status",
    "course registration",
    "student profile",

    "library fine",
    "library account",

    "portal login problem",
    "student portal error",

    "complaint about hostel",
    "complaint about exam",
]

# Answer templates
answer_map = {

    "my fee status": "Please provide your Registration Number so I can check your fee status.",
    "my pending fee": "Please provide your Registration Number so I can check your pending fee details.",
    "fee payment details": "Please provide your Registration Number so I can verify your fee payment.",

    "my attendance": "Please provide your Registration Number so I can check your attendance percentage.",
    "attendance percentage": "Please provide your Registration Number so I can check your attendance.",
    "attendance shortage": "Please provide your Registration Number so I can check your attendance record.",

    "exam timetable": "The exam timetable is available on the examination section of the student portal.",
    "exam date": "Exam dates are available on the examination portal.",
    "exam result": "Please provide your Registration Number so I can check your exam result.",

    "scholarship status": "Please provide your Registration Number so I can check your scholarship status.",
    "scholarship payment": "Please provide your Registration Number so I can check your scholarship payment.",
    "scholarship eligibility": "Scholarship eligibility details are available on the scholarship portal.",

    "hostel allotment": "Hostel allotment details are available through the hostel administration office.",
    "hostel room": "Hostel room allocation details are handled by the hostel administration.",
    "hostel complaint": "I will raise a support ticket for the hostel administration to review your issue.",

    "document request": "Document requests can be submitted through the administration office.",
    "bonafide certificate": "You can apply for a bonafide certificate through the administration office.",
    "transfer certificate": "Transfer certificate requests can be submitted through the administration office.",

    "admission status": "Please provide your Registration Number so I can check your admission status.",
    "course registration": "Course registration issues should be reported to the academic office.",
    "student profile": "Please provide your Registration Number so I can access your student profile.",

    "library fine": "Please provide your Registration Number so I can check your library record.",
    "library account": "Please provide your Registration Number so I can check your library account.",

    "portal login problem": "I will create a support ticket for the IT support team.",
    "student portal error": "I will raise a support ticket for the IT department.",

    "complaint about hostel": "I will create a support ticket for the hostel department.",
    "complaint about exam": "I will raise a support ticket for the examination office.",
}

rows = []

for g in greetings:
    for a in actions:
        for t in topics:

            question = f"{g} {a} {t}"
            answer = answer_map.get(t)

            if answer:
                rows.append([question, answer])

# Append to CSV
with open("training_data.csv", "a", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerows(rows)

print(f"Generated {len(rows)} new training rows.")