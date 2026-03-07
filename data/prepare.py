import csv, json

SYSTEM_PROMPT = """You are an AI helpline assistant for a college.
Help students with: fees, exams, attendance, documents, hostel, admissions, scholarships.
Rules:
1. Keep every answer under 50 words — this is a phone call
2. If student asks personal data, ask for Registration Number first
3. After getting Reg Number, the system will verify OTP before sharing data
4. If issue needs human review, say you are raising a support ticket
5. Never answer questions outside college administration
6. Always be polite, clear, and professional"""

training_data = []

"""Opening training_data.csv for reading, and storing it in proper format"""

with open('training_data.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        example = {
        'text': 
        f'<|system|>\n{SYSTEM_PROMPT}\n<|user|>\n{row["question"]}\n<|assistant|>\n{row["answer"]}'
        }
        training_data.append(example)

"""Opening college_data.json for writing csv file to it"""

with open('college_data.json', 'w', encoding='utf-8') as f:
    json.dump(training_data, f, indent=2, ensure_ascii=False)
print(f'Created {len(training_data)} training examples')