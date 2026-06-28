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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
    "https://primekeyapp-49jj.onrender.com",
    "https://primekeyfinance.com",
    "https://www.primekeyfinance.com"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.primekeyfinance\.com|https://primekeyfinance\.com|http://localhost:.*|http://127\.0\.0\.1:.*|https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
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

from datetime import datetime

def build_html_email(subject: str, content: str) -> str:
    paragraphs = content.strip().split('\n\n')
    html_paragraphs = []
    for p in paragraphs:
        formatted_p = p.replace('\n', '<br>')
        html_paragraphs.append(f"<p style='margin: 0 0 16px 0; color: #374151;'>{formatted_p}</p>")
    
    html_body = '\n'.join(html_paragraphs)
    current_year = datetime.now().year
    
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f3f4f6;
      color: #1f2937;
      -webkit-font-smoothing: antialiased;
    }}
    .email-container {{
      max-width: 580px;
      margin: 30px auto;
      background: #ffffff;
      border-radius: 12px;
      border: 1px solid #e5e7eb;
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.03);
      overflow: hidden;
    }}
    .header {{
      background-color: #023428;
      padding: 32px 24px;
      text-align: center;
      border-bottom: 4px solid #be8c2a;
    }}
    .header h1 {{
      color: #ffffff;
      margin: 0;
      font-size: 22px;
      font-weight: 800;
      letter-spacing: 1.5px;
    }}
    .body-content {{
      padding: 40px 32px;
      line-height: 1.6;
      font-size: 15px;
    }}
    .footer {{
      background-color: #f9fafb;
      padding: 24px 32px;
      text-align: center;
      font-size: 12px;
      color: #6b7280;
      border-top: 1px solid #e5e7eb;
      line-height: 1.5;
    }}
    .footer a {{
      color: #023428;
      text-decoration: underline;
      font-weight: 500;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header">
      <h1>PRIMEKEY FINANCE</h1>
    </div>
    <div class="body-content">
      {html_body}
    </div>
    <div class="footer">
      &copy; {current_year} Primekey Finance. All rights reserved.<br>
      If you have any questions, contact us at <a href="mailto:finance@primekeyfinance.com">finance@primekeyfinance.com</a>.
    </div>
  </div>
</body>
</html>
"""

def send_smtp_email(to_email: str, subject: str, html_content: str, plain_content: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)

    if not smtp_user or not smtp_password:
        raise ValueError("SMTP credentials not configured")

    msg = MIMEMultipart('alternative')
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(plain_content, 'plain'))
    msg.attach(MIMEText(html_content, 'html'))

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(sender_email, to_email, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(sender_email, to_email, msg.as_string())

@app.post("/send-notification-email")
@limiter.limit("3/minute")
async def send_email(request: Request, data: EmailRequest, user=Depends(verify_token)):
    html_content = build_html_email(data.subject, data.content)

    # 1. Try SMTP if user has configured it
    smtp_user = os.getenv("SMTP_USER")
    if smtp_user:
        try:
            send_smtp_email(data.to_email, data.subject, html_content, data.content)
            return {"status": "success", "message": "Email sent via SMTP"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SMTP email failed: {str(e)}")

    # 2. Fallback to SendGrid
    sg_key = os.getenv('SENDGRID_API_KEY')
    sender = os.getenv('SENDGRID_SENDER_EMAIL', 'noreply@primekey-finance.com')
    
    if not sg_key:
        raise HTTPException(status_code=500, detail="Email service not configured. Please set SMTP_USER or SENDGRID_API_KEY.")

    message = Mail(
        from_email=sender,
        to_emails=data.to_email,
        subject=data.subject,
        html_content=html_content
    )
    try:
        sg = SendGridAPIClient(sg_key)
        sg.send(message)
        return {"status": "success", "message": "Email sent via SendGrid"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SendGrid email failed: {str(e)}")

@app.get("/")
def root():
    return {"message": "Primekey Finance API is active", "status": "healthy"}
