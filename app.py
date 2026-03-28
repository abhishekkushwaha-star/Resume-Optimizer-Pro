import streamlit as st
import google.generativeai as genai
import pdfplumber
import io
import json
import sqlite3
import hashlib
import time
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black

# ==========================================
# 1. DATABASE & AUTH (VERSION 2)
# ==========================================
def init_db():
    conn = sqlite3.connect('resume_app.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS skills (username TEXT, skill TEXT, bullet TEXT, UNIQUE(username, skill))''')
    conn.commit()
    conn.close()

def hash_password(password): return hashlib.sha256(str.encode(password)).hexdigest()

def verify_login(username, password):
    conn = sqlite3.connect('resume_app.db')
    c = conn.cursor()
    c.execute('SELECT password FROM users WHERE username=?', (username,))
    result = c.fetchone()
    conn.close()
    if result and result[0] == hash_password(password): return True
    return False

def create_user(username, password):
    conn = sqlite3.connect('resume_app.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hash_password(password)))
        conn.commit()
        success = True
    except sqlite3.IntegrityError: success = False
    conn.close()
    return success

def save_user_skill(username, skill, bullet):
    conn = sqlite3.connect('resume_app.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO skills (username, skill, bullet) VALUES (?, ?, ?)', (username, skill, bullet))
    conn.commit()
    conn.close()

def get_user_skills(username):
    conn = sqlite3.connect('resume_app.db')
    c = conn.cursor()
    c.execute('SELECT skill, bullet FROM skills WHERE username=?', (username,))
    results = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}

init_db()

# ==========================================
# 2. BEAUTIFUL PDF GENERATOR (REPORTLAB)
# ==========================================
def create_pdf(text):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    name_style = ParagraphStyle('Name', parent=styles['Heading1'], alignment=1, fontSize=18, spaceAfter=4, textColor=HexColor("#2C3E50"), fontName="Helvetica-Bold")
    contact_style = ParagraphStyle('Contact', parent=styles['Normal'], alignment=1, fontSize=9, spaceAfter=12, textColor=HexColor("#7F8C8D"))
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=12, spaceBefore=12, spaceAfter=4, textColor=HexColor("#2980B9"), fontName="Helvetica-Bold", textTransform="uppercase")
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, spaceAfter=4, textColor=black, leading=14)
    bullet_style = ParagraphStyle('Bullet', parent=styles['Normal'], fontSize=10, leftIndent=12, spaceAfter=3, textColor=black, leading=14)
    job_left_style = ParagraphStyle('JobLeft', parent=styles['Normal'], fontSize=11, textColor=black, leading=14)
    job_right_style = ParagraphStyle('JobRight', parent=styles['Normal'], fontSize=10, alignment=2, textColor=HexColor("#7F8C8D"), leading=14)

    flowables = []
    for line in text.split('\n'):
        line = line.strip().replace('**', '')
        if not line: continue
        try:
            if line.startswith('# '):
                flowables.append(Paragraph(line.replace('# ', ''), name_style))
            elif line.startswith('CONTACT: '):
                flowables.append(Paragraph(line.replace('CONTACT: ', ''), contact_style))
            elif line.startswith('## '):
                flowables.append(Paragraph(line.replace('## ', ''), section_style))
            elif line.startswith('### '):
                parts = line.replace('### ', '').split('|')
                if len(parts) >= 2:
                    left_text = f"<b>{parts[0].strip()}</b>"
                    if len(parts) > 1: left_text += f"<br/><i>{parts[1].strip()}</i>"
                    right_text = ""
                    if len(parts) > 2: right_text += parts[2].strip()
                    if len(parts) > 3: right_text += f"<br/>{parts[3].strip()}"
                    t_data = [[Paragraph(left_text, job_left_style), Paragraph(right_text, job_right_style)]]
                    t = Table(t_data, colWidths=[doc.width * 0.65, doc.width * 0.35])
                    t.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0), ('BOTTOMPADDING', (0,0), (-1,-1), 6)]))
                    flowables.append(t)
            elif line.startswith('- ') or line.startswith('* '):
                flowables.append(Paragraph(f"•  {line[2:]}", bullet_style))
            else:
                flowables.append(Paragraph(line, body_style))
        except: pass
    doc.build(flowables)
    return buffer.getvalue()

# ==========================================
# 3. APP INITIALIZATION & RETRY LOGIC
# ==========================================
st.set_page_config(page_title="Resume Optimizer Pro", page_icon="🎯", layout="wide")

if 'app_step' not in st.session_state: st.session_state.app_step = 1
if 'logged_in' not in st.session_state: st.session_state.logged_in = False

# --- COMPLETELY STABLE INITIALIZATION ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=api_key)
    
    # We remove 'models/' and 'v1beta' entirely. 
    # The 0.8.3 library will correctly route 'gemini-1.5-flash' to the stable API.
    model = genai.GenerativeModel('gemini-1.5-flash') 
    
except Exception as e:
    st.error(f"Configuration Error: {e}")
    st.stop()

# --- Auth Sidebar ---
with st.sidebar:
    if st.session_state.logged_in:
        st.success(f"User: {st.session_state.username}")
        if st.button("Logout"): 
            st.session_state.logged_in = False
            st.rerun()
    else:
        st.header("🔐 Pro Login")
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.button("Login"):
            if verify_login(user, pw):
                st.session_state.logged_in = True
                st.session_state.username = user
                st.rerun()

# ==========================================
# STEP 1: SCAN & ANALYZE
# ==========================================
if st.session_state.app_step == 1:
    st.title("🎯 Step 1: Analyze Job Gap")
    uploaded_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"])
    jd_text = st.text_area("Paste JD", height=200)

    if st.button("Analyze Gap", type="primary"):
        if uploaded_file and jd_text:
            try:
                with st.spinner("Analyzing..."):
                    resume_text = ""
                    with pdfplumber.open(uploaded_file) as pdf:
                        for page in pdf.pages: resume_text += page.extract_text() + "\n"
                    
                    st.session_state.resume_text = resume_text
                    st.session_state.jd_text = jd_text
                    
                    prompt = f"Identify 3-5 missing skills from this Resume: {resume_text} for this JD: {jd_text}. Return ONLY raw JSON: [{{'skill': '...', 'suggestion': '...'}}]"
                    response = model.generate_content(prompt)
                    clean_json = response.text.replace("```json", "").replace("```", "").strip()
                    st.session_state.gap_data = json.loads(clean_json)
                    st.session_state.app_step = 2
                    st.rerun()
            except Exception as e:
                if "429" in str(e):
                    st.warning("🚦 Rate limit hit. Waiting 30s...")
                    progress = st.progress(0)
                    for i in range(30):
                        time.sleep(1)
                        progress.progress((i + 1) / 30)
                    st.info("Ready! Click Analyze again.")
                else: st.error(f"Error: {e}")

# ==========================================
# STEP 2: BRIDGE THE GAP
# ==========================================
elif st.session_state.app_step == 2:
    st.title("🎯 Step 2: Bridge the Gap")
    user_saved = get_user_skills(st.session_state.username) if st.session_state.logged_in else {}
    
    with st.form("gap_form"):
        for idx, item in enumerate(st.session_state.gap_data):
            skill = item['skill']
            default = user_saved.get(skill, item['suggestion'])
            st.checkbox(f"Add {skill}", value=(skill in user_saved), key=f"c_{idx}")
            st.text_input("Bullet Point", value=default, key=f"t_{idx}")
        
        if st.form_submit_button("Generate Final Resume"):
            approved = []
            for idx, item in enumerate(st.session_state.gap_data):
                if st.session_state[f"c_{idx}"]:
                    approved.append({"skill": item['skill'], "bullet": st.session_state[f"t_{idx}"]})
                    if st.session_state.logged_in:
                        save_user_skill(st.session_state.username, item['skill'], st.session_state[f"t_{idx}"])
            st.session_state.approved = approved
            st.session_state.app_step = 3
            st.rerun()

# ==========================================
# STEP 3: DOWNLOAD
# ==========================================
elif st.session_state.app_step == 3:
    st.title("🎯 Step 3: Final PDF")
    if 'final_pdf' not in st.session_state:
        # Construct final prompt with approved skills
        added_text = "\n".join([f"- {s['bullet']}" for s in st.session_state.approved])
        final_prompt = f"Rewrite resume {st.session_state.resume_text} for JD {st.session_state.jd_text}. Add these: {added_text}. Format: # Name \n CONTACT: ... \n ## SUMMARY \n ## EXPERIENCE \n ### Company | Role | Loc | Date \n - Bullets"
        response = model.generate_content(final_prompt)
        st.session_state.final_pdf = create_pdf(response.text)
        st.session_state.final_text = response.text

    st.text(st.session_state.final_text)
    st.download_button("Download PDF", st.session_state.final_pdf, "Resume.pdf", "application/pdf")
    if st.button("New Scan"):
        for k in ['app_step', 'final_pdf', 'final_text']: del st.session_state[k]
        st.rerun()

        