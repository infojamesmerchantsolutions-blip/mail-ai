import os
import json
import sqlite3
import time
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, jsonify
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key')

# OpenRouter FREE AI
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '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')
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODEL = "meta-llama/llama-3.2-3b-instruct:free"

# Google OAuth - REPLACE WITH YOUR VALUES
GOOGLE_CLIENT_ID = "584739021684-orfgk4fke1unoqmntctj27itnbs3mpjr.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'https://your-app.onrender.com/oauth2callback')

def init_db():
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS accounts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  email TEXT UNIQUE,
                  credentials TEXT,
                  is_active INTEGER DEFAULT 1,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS account_settings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_id INTEGER,
                  ai_instructions TEXT,
                  context_info TEXT,
                  reply_style TEXT DEFAULT 'professional',
                  auto_send INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS thread_tracking
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_id INTEGER,
                  thread_id TEXT,
                  follow_up_count INTEGER DEFAULT 0,
                  last_follow_up TIMESTAMP,
                  status TEXT DEFAULT 'active',
                  original_subject TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS activity_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  account_id INTEGER,
                  action TEXT,
                  details TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def get_email_template(template_num, ticket_id, ai_response="", specialist_email="derek@avex.com"):
    if template_num == 1:
        return f'''<!DOCTYPE html><html><body><div style="max-width:600px;margin:0 auto">
        <img src="https://cdn.shopify.com/shopify-marketing_assets/static/shopify-logo.png" style="height:32px">
        <div style="border:1px solid #e5e5e5;padding:32px;border-radius:8px">
        <p>Hello,</p><p>Thank you for reaching out to Shopify Support.</p>
        <div style="background:#f8f9fa;border-left:4px solid #008060;padding:16px;margin:20px 0">{ai_response}</div>
        <p>Please let me know if you have any questions.</p><p>Best regards,<br><strong>Shopify Support Team</strong></p>
        </div><p style="font-size:12px;color:#6b6b6b">Ticket ID: {ticket_id}</p></div></body></html>'''
    elif template_num == 7:
        return f'''<!DOCTYPE html><html><body><div style="max-width:600px;margin:0 auto">
        <img src="https://cdn.shopify.com/shopify-marketing_assets/static/shopify-logo.png" style="height:32px">
        <div style="border:1px solid #e5e5e5;padding:32px;border-radius:8px">
        <p>Hello,</p><p>We are closing ticket {ticket_id} after 72 hours.</p>
        <p><strong>Derek</strong>, a Shopify Partner with Avex, can help.</p>
        <div style="text-align:center;margin:30px 0">
        <a href="mailto:{specialist_email}" style="background:#008060;color:white;padding:12px 28px;text-decoration:none;border-radius:40px">Contact Derek</a>
        </div><p>Best regards,<br><strong>Shopify Support Team</strong></p>
        </div></div></body></html>'''
    else:
        return f'''<!DOCTYPE html><html><body><div style="max-width:600px;margin:0 auto">
        <img src="https://cdn.shopify.com/shopify-marketing_assets/static/shopify-logo.png" style="height:32px">
        <div style="border:1px solid #e5e5e5;padding:32px;border-radius:8px">
        <p>Hello,</p><p>Following up on ticket {ticket_id}.</p>
        <p>Best regards,<br><strong>Shopify Support Team</strong></p>
        </div></div></body></html>'''

def generate_ai_reply(email_content, subject, settings):
    try:
        response = requests.post(OPENROUTER_URL, headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}, json={"model": FREE_MODEL, "messages": [{"role": "user", "content": f"Write a professional Shopify support reply to: {email_content}. Be concise, under 150 words."}], "max_tokens": 500}, timeout=30)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"AI error: {e}")
    return "Thank you for reaching out. I'll review and follow up shortly."

def send_email(account_id, to_email, subject, html_body):
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("SELECT credentials FROM accounts WHERE id = ?", (account_id,))
    account = c.fetchone()
    conn.close()
    if not account:
        return False
    creds = Credentials.from_authorized_user_info(json.loads(account[0]))
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    service = build('gmail', 'v1', credentials=creds)
    message = MIMEMultipart('alternative')
    message['to'] = to_email
    message['subject'] = subject
    message.attach(MIMEText(html_body, 'html'))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    try:
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        return True
    except Exception as e:
        logger.error(f"Send error: {e}")
        return False

@app.route('/')
def index():
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("SELECT id, email FROM accounts")
    accounts = c.fetchall()
    conn.close()
    return render_template('dashboard.html', accounts=accounts)

@app.route('/add_account')
def add_account():
    flow = Flow.from_client_config({"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [REDIRECT_URI]}}, scopes=['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.modify'], redirect_uri=REDIRECT_URI)
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')
    session['state'] = state
    return redirect(auth_url)

@app.route('/oauth2callback')
def oauth2callback():
    flow = Flow.from_client_config({"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [REDIRECT_URI]}}, scopes=['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.modify'], redirect_uri=REDIRECT_URI, state=session.get('state'))
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    service = build('gmail', 'v1', credentials=creds)
    profile = service.users().getProfile(userId='me').execute()
    email = profile['emailAddress']
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO accounts (email, credentials) VALUES (?, ?)", (email, creds.to_json()))
    c.execute("SELECT id FROM accounts WHERE email = ?", (email,))
    acc_id = c.fetchone()[0]
    c.execute("INSERT OR IGNORE INTO account_settings (account_id, ai_instructions, context_info) VALUES (?, ?, ?)", (acc_id, "Be professional and helpful.", "Derek is a Shopify Partner with Avex."))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/remove_account/<int:account_id>')
def remove_account(account_id):
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    return redirect('/')

@app.route('/save_settings/<int:account_id>', methods=['POST'])
def save_settings(account_id):
    data = request.json
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("UPDATE account_settings SET ai_instructions = ?, context_info = ? WHERE account_id = ?", (data.get('ai_instructions', ''), data.get('context_info', ''), account_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/get_settings/<int:account_id>')
def get_settings(account_id):
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("SELECT ai_instructions, context_info FROM account_settings WHERE account_id = ?", (account_id,))
    row = c.fetchone()
    conn.close()
    return jsonify({'ai_instructions': row[0] if row else '', 'context_info': row[1] if row else ''})

@app.route('/get_activity/<int:account_id>')
def get_activity(account_id):
    conn = sqlite3.connect('mail_ai.db')
    c = conn.cursor()
    c.execute("SELECT action, details, created_at FROM activity_log WHERE account_id = ? ORDER BY created_at DESC LIMIT 20", (account_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{'action': r[0], 'details': r[1], 'time': r[2]} for r in rows])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)