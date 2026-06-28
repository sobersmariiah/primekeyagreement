from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import io
import os
import json
import firebase_admin
from firebase_admin import credentials, auth
from generator import generate_agreement
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Primekey Loan Agreement API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Initialize Firebase Admin
service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if service_account_json:
    cred_dict = json.loads(service_account_json)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
else:
    try:
        firebase_admin.initialize_app()
    except Exception:
        print("Firebase Admin could not be initialized.")

# CORS
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5000",
    "https://primekey-finance.web.app",
    "https://primekeyapp-49jj.onrender.com"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)

class LoanRequest(BaseModel):
    clientName: str
    loanAmount: float
    annualRatePct: float
    loanTermMonths: int
    monthlyPayment: float
    firstPaymentDate: str
    agreementDate: str
    referenceNo: str
    currencySymbol: str = "$"

class EmailRequest(BaseModel):
    to_email: str
    subject: str
    content: str

async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split("Bearer ")[1]
    try:
        return auth.verify_id_token(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

@app.post("/generate-agreement")
@limiter.limit("5/minute")
async def generate(request: Request, data: LoanRequest, user=Depends(verify_token)):
    try:
        pdf_bytes = generate_agreement(data)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=agreement_{data.referenceNo}.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-notification-email")
@limiter.limit("3/minute")
async def send_email(request: Request, data: EmailRequest, user=Depends(verify_token)):
    # Only allow admins to send generic notification emails, 
    # or implement logic to allow users to trigger specific transactional ones.
    
    sg_key = os.getenv('SENDGRID_API_KEY')
    sender = os.getenv('SENDGRID_SENDER_EMAIL', 'noreply@primekey-finance.com')
    
    if not sg_key:
        raise HTTPException(status_code=500, detail="Email service not configured")

    message = Mail(
        from_email=sender,
        to_emails=data.to_email,
        subject=data.subject,
        plain_text_content=data.content
    )
    try:
        sg = SendGridAPIClient(sg_key)
        sg.send(message)
        return {"status": "success", "message": "Email sent"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

@app.get("/")
def root():
    return {"message": "Primekey Finance API is active", "status": "healthy"}
