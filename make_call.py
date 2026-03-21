import os
from dotenv import load_dotenv
from twilio.rest import Client

# Load .env file
load_dotenv()

# Get values from .env
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
twilio_number = os.getenv("TWILIO_PHONE_NUMBER")


to_number = os.getenv("PERSONAL_PHONE_NUMBER")

client = Client(account_sid, auth_token)

call = client.calls.create(
    to=to_number,
    from_=twilio_number,
    url="https://snidely-unheavy-deegan.ngrok-free.dev/voice/incoming"
)

print("Call initiated:", call.sid)