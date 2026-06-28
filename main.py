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
    status: str = None
    full_name: str = None
    reference_no: str = None
    loan_amount: str = None
    monthly_repayment: str = None
    duration: str = None
    reason: str = None

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
        html_paragraphs.append(f"<p style='margin: 0 0 16px 0; color: #4b5563; font-size: 15px;'>{formatted_p}</p>")
    
    html_body = '\n'.join(html_paragraphs)
    current_year = datetime.now().year
    
    # Check if we should render a CTA button
    show_button = False
    btn_text = "Go to Dashboard"
    if "Welcome" in subject or "Approved" in subject or "Received" in subject or "Verification" in subject:
        show_button = True
        if "Approved" in subject:
            btn_text = "Review & Sign Agreement"
        elif "Welcome" in subject:
            btn_text = "Get Started"
            
    cta_html = ""
    if show_button:
        cta_html = f"""
        <div style="text-align: center; margin: 35px 0 15px 0;">
          <a href="https://primekeyfinance.com" target="_blank" style="
            display: inline-block;
            padding: 14px 30px;
            background-color: #023428;
            color: #ffffff !important;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 700;
            font-size: 14px;
            letter-spacing: 0.5px;
            border: 2px solid #be8c2a;
            box-shadow: 0 4px 6px rgba(2, 52, 40, 0.15);
          ">{btn_text}</a>
        </div>
        """
        
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
      border-radius: 16px;
      border: 1px solid #e5e7eb;
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
      overflow: hidden;
    }}
    .header {{
      background-color: #023428;
      padding: 35px 24px;
      text-align: center;
      border-bottom: 5px solid #be8c2a;
    }}
    .header h1 {{
      margin: 0;
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 2px;
    }}
    .body-content {{
      padding: 40px 32px;
      line-height: 1.7;
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
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header">
      <h1>
        <span style="color: #ffffff;">PRIME</span><span style="color: #be8c2a;">KEY</span>
      </h1>
      <div style="color: #be8c2a; font-size: 11px; letter-spacing: 3px; margin-top: 5px; font-weight: 600; text-transform: uppercase;">
        &mdash; Credit Financial &mdash;
      </div>
    </div>
    <div class="body-content">
      {html_body}
      {cta_html}
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

def build_structured_email(data: EmailRequest) -> str:
    first_name = data.full_name.split(' ')[0] if data.full_name else "Client"
    current_year = datetime.now().year
    
    if data.status == "rejected":
        banner_bg = "#2d1f1f"
        banner_color = "#f87171"
        alert_title = "Application Not Approved"
        intro_text = "Thank you for applying for a loan with Primekey Finance. After careful review, we regret to inform you that your application has not been approved at this time."
        closing_text = "This decision does not prevent you from applying again in the future. If you have any questions or would like to discuss your application, please don't hesitate to contact us."
        
        reason_val = data.reason if (data.reason and data.reason.strip().lower() != "null") else "No specific reason provided."
        reason_html = f"""
        <div class="reason-box">
          <h3 class="reason-title">Reason:</h3>
          <p class="reason-content">{reason_val}</p>
        </div>
        """
    else:  # approved
        banner_bg = "#1f2d24"
        banner_color = "#4ade80"
        alert_title = "Application Approved!"
        intro_text = "We are pleased to inform you that your loan application has been approved. Below are the details of your loan agreement."
        closing_text = "Please log in to your dashboard to review and sign your loan agreement contract to finalize the payout. If you have any questions, please don't hesitate to contact us."
        
        reason_html = ""
        if data.reason and data.reason.strip().lower() != "null":
            reason_html = f"""
            <div class="reason-box">
              <h3 class="reason-title">Officer Remarks:</h3>
              <p class="reason-content">{data.reason}</p>
            </div>
            """
            
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{data.subject}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #111827;
      color: #f3f4f6;
      -webkit-font-smoothing: antialiased;
    }}
    .email-container {{
      max-width: 580px;
      margin: 30px auto;
      background: #1f2937;
      border-radius: 16px;
      border: 1px solid #374151;
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
      overflow: hidden;
    }}
    .header {{
      background-color: #023428;
      padding: 35px 24px;
      text-align: center;
      border-bottom: 5px solid #be8c2a;
    }}
    .header h1 {{
      margin: 0;
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 2px;
    }}
    .body-content {{
      padding: 40px 32px;
      line-height: 1.7;
    }}
    .alert-banner {{
      padding: 20px;
      background-color: {banner_bg};
      border-left: 4px solid {banner_color};
      border-radius: 8px;
      margin-bottom: 30px;
    }}
    .alert-title {{
      font-size: 18px;
      font-weight: 700;
      color: {banner_color};
      margin: 0 0 4px 0;
    }}
    .alert-subtitle {{
      font-size: 13px;
      color: #9ca3af;
      margin: 0;
      word-break: break-all;
    }}
    .details-card {{
      background-color: #111827;
      border: 1px solid #374151;
      border-radius: 12px;
      padding: 24px;
      margin: 30px 0;
    }}
    .reason-box {{
      padding: 20px;
      background-color: #27211a;
      border-left: 4px solid #be8c2a;
      border-radius: 8px;
      margin: 30px 0;
    }}
    .reason-title {{
      font-size: 14px;
      font-weight: 700;
      color: #be8c2a;
      margin: 0;
    }}
    .reason-content {{
      font-size: 14px;
      color: #d1d5db;
      margin: 4px 0 0 0;
    }}
    .footer {{
      background-color: #111827;
      padding: 24px 32px;
      text-align: center;
      font-size: 12px;
      color: #9ca3af;
      border-top: 1px solid #374151;
      line-height: 1.5;
    }}
    .footer a {{
      color: #be8c2a;
      text-decoration: underline;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header">
      <h1>
        <span style="color: #ffffff;">PRIME</span><span style="color: #be8c2a;">KEY</span>
      </h1>
      <div style="color: #be8c2a; font-size: 11px; letter-spacing: 3px; margin-top: 5px; font-weight: 600; text-transform: uppercase;">
        &mdash; Credit Financial &mdash;
      </div>
    </div>
    <div class="body-content">
      <div class="alert-banner">
        <h2 class="alert-title">{alert_title}</h2>
        <p class="alert-subtitle">Reference: {data.reference_no}</p>
      </div>
      
      <p style="color: #d1d5db; font-size: 15px; margin: 0 0 20px 0;">Dear {first_name},</p>
      <p style="color: #d1d5db; font-size: 15px; margin: 0 0 24px 0;">{intro_text}</p>
      
      <div class="details-card">
        <table style="width: 100%; border-collapse: collapse;">
          <tr style="height: 35px;">
            <td style="width: 150px; color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Full Name</td>
            <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.full_name}</td>
          </tr>
          <tr style="height: 35px;">
            <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Reference No.</td>
            <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0; word-break: break-all;">{data.reference_no}</td>
          </tr>
          <tr style="height: 35px;">
            <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Loan Amount</td>
            <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.loan_amount}</td>
          </tr>
          <tr style="height: 35px;">
            <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Monthly Repayment</td>
            <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.monthly_repayment}</td>
          </tr>
          <tr style="height: 35px;">
            <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Duration</td>
            <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.duration}</td>
          </tr>
        </table>
      </div>
      
      {reason_html}
      
      <p style="color: #d1d5db; font-size: 15px; margin: 24px 0 0 0;">{closing_text}</p>
    </div>
    <div class="footer">
      &copy; {current_year} Primekey Finance. All rights reserved.<br>
      If you have any questions, contact us at <a href="mailto:finance@primekeyfinance.com">finance@primekeyfinance.com</a>.
    </div>
  </div>
</body>
</html>
"""

@app.post("/send-notification-email")
@limiter.limit("3/minute")
async def send_email(request: Request, data: EmailRequest, user=Depends(verify_token)):
    if data.status in ["approved", "rejected"]:
        html_content = build_structured_email(data)
    else:
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
