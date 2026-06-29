from fastapi import FastAPI, HTTPException, Depends, Header, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import io
import os
import json
import firebase_admin
from firebase_admin import credentials, auth, firestore
from generator import generate_agreement
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
import smtplib
import imaplib
import time
import math
from datetime import timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import base64

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
    bank_name: str = None
    account_number: str = None

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
        

    # Build dynamic table
    table_html = ""
    if data.status and data.status.startswith("withdrawal_"):
        table_html = f'''
        <div class="details-card">
          <table style="width: 100%; border-collapse: collapse;">
            <tr style="height: 35px;">
              <td style="width: 150px; color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Full Name</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.full_name or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Amount</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.loan_amount or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Bank</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.bank_name or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Account No.</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.account_number or "N/A"}</td>
            </tr>
          </table>
        </div>
        '''
    elif data.status and data.status.startswith("bank_"):
        pass # No table for bank verification
    else:
        table_html = f'''
        <div class="details-card">
          <table style="width: 100%; border-collapse: collapse;">
            <tr style="height: 35px;">
              <td style="width: 150px; color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Full Name</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.full_name or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Reference No.</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0; word-break: break-all;">{data.reference_no or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Loan Amount</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.loan_amount or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Monthly Repayment</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.monthly_repayment or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Duration</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.duration or "N/A"}</td>
            </tr>
          </table>
        </div>
        '''

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

def send_smtp_email(to_email: str, subject: str, html_content: str, plain_content: str, attachment_bytes: bytes = None, attachment_filename: str = None) -> bytes:
    smtp_host = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)

    if not smtp_user or not smtp_password:
        raise ValueError("SMTP credentials not configured")

    if attachment_bytes and attachment_filename:
        msg = MIMEMultipart('mixed')
        alt_part = MIMEMultipart('alternative')
        alt_part.attach(MIMEText(plain_content, 'plain'))
        alt_part.attach(MIMEText(html_content, 'html'))
        msg.attach(alt_part)
        
        file_part = MIMEApplication(attachment_bytes, Name=attachment_filename)
        file_part['Content-Disposition'] = f'attachment; filename="{attachment_filename}"'
        msg.attach(file_part)
    else:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(plain_content, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))

    msg['From'] = f"Primekey <{sender_email}>"
    msg['To'] = to_email
    msg['Subject'] = subject

    msg_bytes = msg.as_bytes()

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(sender_email, to_email, msg_bytes)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(sender_email, to_email, msg_bytes)
            
    return msg_bytes

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
    elif data.status == "submitted":
        banner_bg = "#1e293b"
        banner_color = "#3b82f6"
        alert_title = "Application Received"
        intro_text = "Thank you for applying for a loan with Primekey Finance. We have successfully received your application. Our underwriting team will review it shortly."
        closing_text = "You can monitor the status of your application from your user dashboard at any time. If you have any questions, please don't hesitate to contact us."
        reason_html = ""
    elif data.status == "kyc_rejected":
        banner_bg = "#2d1f1f"
        banner_color = "#f87171"
        alert_title = "KYC Verification Rejected"
        intro_text = "Unfortunately, your identity verification (KYC) documents could not be approved at this time."
        closing_text = "Please log in to your dashboard to re-upload clear and correct documents. If you have any questions, please don't hesitate to contact us."
        reason_val = data.reason if (data.reason and data.reason.strip().lower() != "null") else "No specific reason provided."
        reason_html = f"""
        <div class="reason-box">
          <h3 class="reason-title">Reason for Rejection:</h3>
          <p class="reason-content">{reason_val}</p>
        </div>
        """
    elif data.status == "withdrawal_pending":
        banner_bg = "#1e293b"
        banner_color = "#3b82f6"
        alert_title = "Withdrawal Request Received"
        intro_text = "We have successfully received your withdrawal request. It is currently pending review by our financial team."
        closing_text = "You can monitor the status of your withdrawal from your user dashboard at any time. We will notify you once it begins processing."
        reason_html = ""
    elif data.status == "withdrawal_processing":
        banner_bg = "#1e3a8a"
        banner_color = "#60a5fa"
        alert_title = "Withdrawal Processing"
        intro_text = "Great news! Your withdrawal request is now being processed. The funds are being routed to your designated bank account."
        closing_text = "Depending on your bank, it may take 1-3 business days for the funds to reflect in your account. We will notify you once the transfer is fully completed."
        reason_html = ""
    elif data.status == "withdrawal_completed":
        banner_bg = "#1f2d24"
        banner_color = "#4ade80"
        alert_title = "Withdrawal Completed!"
        intro_text = "Your withdrawal has been successfully processed and completed. The funds have been transferred to your bank account."
        closing_text = "If you do not see the funds in your account within the next 24-48 hours, please contact your bank or reach out to our support team."
        reason_html = ""
    elif data.status == "withdrawal_failed":
        banner_bg = "#2d1f1f"
        banner_color = "#f87171"
        alert_title = "Withdrawal Failed"
        intro_text = "Unfortunately, we encountered an issue while processing your withdrawal request and it has failed."
        closing_text = "Please check your bank account details or contact our support team for further assistance. The funds have been returned to your Primekey balance."
        reason_html = ""
    elif data.status == "bank_pending":
        banner_bg = "#3f2c00"
        banner_color = "#eab308"
        alert_title = "Bank Account Verification Pending"
        intro_text = "Your bank account status has been updated to Pending. You will soon receive another email with instructions to verify your bank account."
        closing_text = "Please keep an eye on your inbox for the verification instructions. Thank you for your patience."
        reason_html = ""
    elif data.status == "bank_verified":
        banner_bg = "#1f2d24"
        banner_color = "#4ade80"
        alert_title = "Bank Account Verified!"
        intro_text = "Good news! Your bank account has been successfully verified. You can now use this account for seamless withdrawals."
        closing_text = "No further action is required for this account."
        reason_html = ""
    elif data.status == "bank_rejected":
        banner_bg = "#2d1f1f"
        banner_color = "#f87171"
        alert_title = "Bank Account Rejected"
        intro_text = "Unfortunately, we were unable to verify your bank account at this time."
        closing_text = "Please log in to your dashboard to review your account details or add a different bank account."
        reason_html = ""
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
            

    # Build dynamic table
    table_html = ""
    if data.status and data.status.startswith("withdrawal_"):
        table_html = f'''
        <div class="details-card">
          <table style="width: 100%; border-collapse: collapse;">
            <tr style="height: 35px;">
              <td style="width: 150px; color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Full Name</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.full_name or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Amount</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.loan_amount or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Bank</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.bank_name or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Account No.</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.account_number or "N/A"}</td>
            </tr>
          </table>
        </div>
        '''
    elif data.status and data.status.startswith("bank_"):
        pass # No table for bank verification
    elif data.status in ["approved", "rejected", "submitted"]:
        table_html = f'''
        <div class="details-card">
          <table style="width: 100%; border-collapse: collapse;">
            <tr style="height: 35px;">
              <td style="width: 150px; color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Full Name</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.full_name or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Reference No.</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0; word-break: break-all;">{data.reference_no or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Loan Amount</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.loan_amount or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Monthly Repayment</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.monthly_repayment or "N/A"}</td>
            </tr>
            <tr style="height: 35px;">
              <td style="color: #9ca3af; font-size: 14px; font-weight: 600; padding: 4px 0;">Duration</td>
              <td style="color: #f3f4f6; font-size: 14px; font-weight: 700; padding: 4px 0;">{data.duration or "N/A"}</td>
            </tr>
          </table>
        </div>
        '''
    else:
        pass # No table for kyc_rejected, bank verifications, or other statuses

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
      
      {table_html}
      
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

def append_to_imap_sent(msg_bytes: bytes):
    imap_host = os.getenv("IMAP_HOST", "imap.hostinger.com")
    imap_port = int(os.getenv("IMAP_PORT", "993"))
    imap_user = os.getenv("SMTP_USER")
    imap_password = os.getenv("SMTP_PASSWORD")

    if not imap_user or not imap_password:
        print("IMAP sync skipped: credentials not set.")
        return

    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(imap_user, imap_password)

        common_sent_folders = ["Sent", "Sent Items", "INBOX.Sent"]
        folder = "Sent"
        selected = False

        for f in common_sent_folders:
            try:
                status, data = mail.select(f)
                if status == 'OK':
                    folder = f
                    selected = True
                    break
            except Exception:
                continue

        if not selected:
            folder = "Sent"
            mail.create(folder)
            mail.select(folder)

        mail.append(folder, '\\Seen', imaplib.Time2Internaldate(time.time()), msg_bytes)
        mail.logout()
        print(f"Successfully synced sent email to IMAP folder '{folder}'")
    except Exception as e:
        print(f"IMAP Sync failed: {str(e)}")

def get_loan_rate(country_code: str, duration: int) -> float:
    default_rates = {
        3: 15.0, 6: 15.0, 12: 12.0, 18: 12.0, 24: 10.0, 36: 10.0, 
        48: 8.0, 60: 8.0, 72: 7.0, 84: 7.0, 96: 6.0, 108: 6.0, 120: 5.0
    }
    localized_rates = {
        "US": {
            3: 15.0, 6: 15.0, 12: 12.0, 18: 12.0, 24: 10.0, 36: 10.0, 
            48: 8.0, 60: 8.0, 72: 7.0, 84: 7.0, 96: 6.0, 108: 6.0, 120: 5.0
        },
        "ZA": {
            3: 28.0, 6: 28.0, 12: 24.0, 18: 24.0, 24: 22.0, 36: 22.0, 
            48: 20.0, 60: 20.0, 72: 18.0, 84: 18.0, 96: 18.0, 108: 16.0, 120: 14.0
        },
        "BZ": {
            3: 24.0, 6: 24.0, 12: 20.0, 18: 20.0, 24: 18.0, 36: 18.0, 
            48: 16.0, 60: 16.0, 72: 15.0, 84: 14.0, 96: 14.0, 108: 12.0, 120: 10.0
        }
    }
    rates = localized_rates.get(country_code, default_rates)
    return rates.get(duration, 12.0)

def calculate_monthly_payment(amount: float, annual_rate: float, months: int) -> float:
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        return round(amount / months, 2)
    monthly = (amount * monthly_rate * math.pow(1 + monthly_rate, months)) / (math.pow(1 + monthly_rate, months) - 1)
    return round(monthly, 2)

def get_currency_symbol(country_code: str) -> str:
    symbols = {
        "BZ": "BZ$",
        "ZA": "R",
        "US": "$",
        "CA": "CA$",
        "GB": "£",
        "EU": "€"
    }
    return symbols.get(country_code, "$")

def get_loan_agreement_pdf(reference_no: str) -> bytes:
    try:
        db = firestore.client()
        doc_ref = db.collection('loan_applications').document(reference_no)
        doc = doc_ref.get()
        if not doc.exists:
            print(f"Loan application document {reference_no} not found in Firestore.")
            return None
            
        app_data = doc.to_dict()
        user_id = app_data.get('userId')
        
        user_data = {}
        if user_id:
            user_doc_ref = db.collection('users').document(user_id)
            user_doc = user_doc_ref.get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                
        client_name = user_data.get('fullName', app_data.get('fullName', 'Client'))
        loan_amount = float(app_data.get('loanAmount', 0.0))
        loan_duration = int(app_data.get('loanDuration', 12))
        country_code = app_data.get('countryCode', 'BZ')
        
        interest_rate = get_loan_rate(country_code, loan_duration)
        monthly_payment = calculate_monthly_payment(loan_amount, interest_rate, loan_duration)
        
        today = datetime.now()
        agreement_date = today.strftime("%B %d, %Y")
        
        first_payment = today + timedelta(days=60)
        first_payment_date = first_payment.strftime("%Y-%m-%d")
        
        currency_symbol = get_currency_symbol(country_code)
        
        class LoanData:
            def __init__(self, clientName, loanAmount, annualRatePct, loanTermMonths, monthlyPayment, firstPaymentDate, agreementDate, referenceNo, currencySymbol):
                self.clientName = clientName
                self.loanAmount = loanAmount
                self.annualRatePct = annualRatePct
                self.loanTermMonths = loanTermMonths
                self.monthlyPayment = monthlyPayment
                self.firstPaymentDate = firstPaymentDate
                self.agreementDate = agreementDate
                self.referenceNo = referenceNo
                self.currencySymbol = currencySymbol
                
        loan_obj = LoanData(
            clientName=client_name,
            loanAmount=loan_amount,
            annualRatePct=interest_rate,
            loanTermMonths=loan_duration,
            monthlyPayment=monthly_payment,
            firstPaymentDate=first_payment_date,
            agreementDate=agreement_date,
            referenceNo=reference_no,
            currencySymbol=currency_symbol
        )
        
        return generate_agreement(loan_obj)
    except Exception as e:
        print(f"Failed to generate loan agreement PDF in backend: {e}")
        return None

@app.post("/send-notification-email")
@limiter.limit("3/minute")
async def send_email(request: Request, data: EmailRequest, background_tasks: BackgroundTasks, user=Depends(verify_token)):
    if data.status in ["approved", "rejected", "submitted", "kyc_rejected", "withdrawal_pending", "withdrawal_processing", "withdrawal_completed", "withdrawal_failed", "bank_pending", "bank_verified", "bank_rejected"]:
        html_content = build_structured_email(data)
    else:
        html_content = build_html_email(data.subject, data.content)

    attachment_bytes = None
    attachment_filename = None
    
    if data.status == "approved" and data.reference_no:
        attachment_bytes = get_loan_agreement_pdf(data.reference_no)
        if attachment_bytes:
            attachment_filename = f"agreement_{data.reference_no}.pdf"

    # 1. Try SMTP if user has configured it
    smtp_user = os.getenv("SMTP_USER")
    if smtp_user:
        try:
            msg_bytes = send_smtp_email(
                to_email=data.to_email, 
                subject=data.subject, 
                html_content=html_content, 
                plain_content=data.content,
                attachment_bytes=attachment_bytes,
                attachment_filename=attachment_filename
            )
            background_tasks.add_task(append_to_imap_sent, msg_bytes)
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
    
    if attachment_bytes and attachment_filename:
        try:
            encoded_pdf = base64.b64encode(attachment_bytes).decode()
            attached_file = Attachment(
                FileContent(encoded_pdf),
                FileName(attachment_filename),
                FileType('application/pdf'),
                Disposition('attachment')
            )
            message.add_attachment(attached_file)
        except Exception as e:
            print(f"Failed to attach PDF to SendGrid message: {e}")
            
    try:
        sg = SendGridAPIClient(sg_key)
        sg.send(message)
        return {"status": "success", "message": "Email sent via SendGrid"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SendGrid email failed: {str(e)}")

@app.get("/")
def root():
    return {"message": "Primekey Finance API is active", "status": "healthy"}
