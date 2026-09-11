"""
Page 4 — Email Outreach
- List all email drafts (initial + recruiter replies)
- Preview full email with job details
- Edit subject + body inline
- One-click SMTP send (via user's configured email)
- Recruiter reply analysis: paste inbound email → AI generates reply draft
- Sent history with timestamps
"""

import streamlit as st
import pandas as pd
import smtplib, json, base64, uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_df, execute_sql, insert_row, esc
from syntara_styles import inject_styles

inject_styles()  # Dark theme

CATALOG = "jobs_automation_db"

def run_sql(q):
    """Execute SQL and return pandas DataFrame via REST API."""
    return query_df(q)

def decrypt_password(encrypted: str) -> str:
    """Decrypt AES-256 encrypted app password."""
    try:
        from cryptography.fernet import Fernet
        import os
        enc_key = os.getenv("EMAIL_ENCRYPTION_KEY", "")
        if enc_key:
            fernet = Fernet(enc_key.encode() if isinstance(enc_key, str) else enc_key)
            return fernet.decrypt(encrypted.encode()).decode()
    except Exception:
        pass
    try:
        return base64.b64decode(encrypted.encode()).decode()
    except Exception:
        return encrypted

def send_email_smtp(
    smtp_host: str, smtp_port: int, from_email: str, password: str,
    to_email: str, subject: str, body_text: str, display_name: str,
    attachment_bytes: bytes = None, attachment_name: str = None
) -> tuple[bool, str]:
    """Send email via SMTP with optional attachment."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{display_name} <{from_email}>"
        msg["To"]      = to_email

        msg.attach(MIMEText(body_text, "plain"))

        if attachment_bytes and attachment_name:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
            msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(from_email, password)
            server.sendmail(from_email, to_email, msg.as_string())

        return True, "Sent successfully"
    except Exception as e:
        return False, str(e)

def ai_analyze_recruiter_email(recruiter_text: str, user_name: str, job_title: str, company: str) -> dict:
    """Use NVIDIA NIM to analyze inbound recruiter email and draft reply."""
    import requests, re, os

    NVIDIA_API_KEY = os.getenv("NVIDIA_NIM_API_KEY", "")
    NVIDIA_URL     = "https://integrate.api.nvidia.com/v1/chat/completions"
    NVIDIA_MODEL   = "meta/llama-3.1-8b-instruct"

    prompt = f"""Analyze this inbound recruiter email and draft a professional reply.

Candidate Name: {user_name}
Applied For: {job_title} at {company}
Recruiter Email:
---
{recruiter_text[:2000]}
---

Respond with JSON:
{{
  "sentiment": "<positive|neutral|negative|request_info|schedule_interview>",
  "key_points": "<what the recruiter is asking for or saying>",
  "recommended_action": "<what candidate should do>",
  "reply_subject": "<suggested reply subject>",
  "reply_body": "<full professional reply email body — ready to send>",
  "urgency": "<high|medium|low>"
}}"""

    try:
        resp = requests.post(
            NVIDIA_URL,
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={"model": NVIDIA_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2, "max_tokens": 800},
            timeout=30,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                return json.loads(m.group())
    except Exception as e:
        st.error(f"AI analysis error: {e}")

    return {
        "sentiment": "unknown",
        "key_points": "Could not analyze",
        "recommended_action": "Review manually",
        "reply_subject": f"Re: {job_title} Application",
        "reply_body": f"Dear Hiring Team,\n\nThank you for reaching out regarding the {job_title} position at {company}.\n\nBest regards,\n{user_name}",
        "urgency": "medium",
    }

# ═══════════════════════════════════════════════════════════
# PAGE
# ═══════════════════════════════════════════════════════════
st.title("📧 Email Outreach")

# User selector
users_df = run_sql(f"SELECT user_id, full_name FROM {CATALOG}.users_schema.users WHERE is_active = true")
if users_df.empty:
    st.warning("No users found. Complete onboarding first.")
    st.stop()

user_opts = {r["full_name"]: r["user_id"] for _, r in users_df.iterrows()}
sel_name  = st.selectbox("👤 Select User", list(user_opts.keys()))
user_id   = user_opts[sel_name]

# Load email config for this user
email_cfg_df = run_sql(f"""
    SELECT email_id, email_address, display_name, smtp_host, smtp_port,
           app_password_encrypted, is_primary
    FROM {CATALOG}.users_schema.user_emails
    WHERE user_id = '{user_id}' AND is_active = true
    ORDER BY is_primary DESC
""")

# Metrics
m_df = run_sql(f"""
    SELECT
        COUNT(*) AS total_drafts,
        SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) AS pending,
        SUM(CASE WHEN status = 'sent'  THEN 1 ELSE 0 END) AS sent,
        SUM(CASE WHEN status = 'no_hr_email' THEN 1 ELSE 0 END) AS no_hr
    FROM {CATALOG}.default.email_drafts
    WHERE user_id = '{user_id}'
""")
if not m_df.empty:
    r = m_df.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📧 Total Drafts",  int(r["total_drafts"] or 0))
    c2.metric("⏳ Pending Send",  int(r["pending"] or 0))
    c3.metric("✅ Sent",          int(r["sent"] or 0))
    c4.metric("❌ No HR Email",   int(r["no_hr"] or 0))

st.markdown("---")

tab_drafts, tab_analyze, tab_sent = st.tabs(["📨 Drafts", "🤖 Analyze Recruiter Reply", "📤 Sent History"])

# ════════════════════════════════
# TAB 1: Drafts
# ════════════════════════════════
with tab_drafts:
    drafts_df = run_sql(f"""
        SELECT d.draft_id, d.job_hash, d.resume_id, d.from_email, d.to_email,
               d.subject, d.body_text, d.status, d.created_at,
               j.job_title, j.company_name, j.apply_link
        FROM {CATALOG}.default.email_drafts d
        JOIN {CATALOG}.default.jobs_clean_silver j ON d.job_hash = j.job_hash
        WHERE d.user_id = '{user_id}'
          AND d.status IN ('draft', 'no_hr_email')
        ORDER BY d.created_at DESC
        LIMIT 50
    """)

    if drafts_df.empty:
        st.info("No pending email drafts. Generate resumes first — email drafts are auto-created.")
    else:
        for _, draft in drafts_df.iterrows():
            status_icon = "📧" if draft["status"] == "draft" else "🔗"
            has_hr      = draft["status"] == "draft" and draft.get("to_email")

            with st.expander(
                f"{status_icon} {draft['job_title']} @ {draft['company_name']}  |  "
                f"{'To: ' + str(draft['to_email']) if has_hr else '⚠️ No HR Email — Apply via link'}"
            ):
                col1, col2 = st.columns([2, 1])

                with col1:
                    # Editable fields
                    new_subject = st.text_input(
                        "Subject",
                        value=str(draft["subject"] or ""),
                        key=f"subj_{draft['draft_id']}"
                    )
                    new_body = st.text_area(
                        "Email Body",
                        value=str(draft["body_text"] or ""),
                        height=250,
                        key=f"body_{draft['draft_id']}"
                    )

                with col2:
                    st.markdown("**📋 Details**")
                    st.write(f"**Job:** {draft['job_title']}")
                    st.write(f"**Company:** {draft['company_name']}")
                    if has_hr:
                        st.write(f"**HR Email:** `{draft['to_email']}`")
                    else:
                        st.markdown(f"**Apply Link:** [Click Here]({draft['apply_link']})")
                    st.write(f"**From:** {draft['from_email']}")

                    # Email account selector
                    if not email_cfg_df.empty:
                        email_labels = [f"{r['display_name']} <{r['email_address']}>" for _, r in email_cfg_df.iterrows()]
                        selected_email_label = st.selectbox("Send From:", email_labels, key=f"from_{draft['draft_id']}")
                        sel_email_row = email_cfg_df.iloc[email_labels.index(selected_email_label)]
                    else:
                        st.warning("No email configured.")
                        sel_email_row = None

                # Action buttons
                btn1, btn2, btn3 = st.columns(3)

                with btn1:
                    if st.button("💾 Save Edits", key=f"save_{draft['draft_id']}"):
                        if spark:
                            spark.sql(f"""
                                UPDATE {CATALOG}.default.email_drafts
                                SET subject = '{new_subject.replace("'","''")}',
                                    body_text = '{new_body.replace("'","''")}',
                                    is_user_edited = true
                                WHERE draft_id = '{draft['draft_id']}'
                            """)
                        st.success("✅ Draft saved!")

                with btn2:
                    if has_hr and sel_email_row is not None:
                        if st.button("🚀 Send Email", key=f"send_{draft['draft_id']}", type="primary"):
                            password = decrypt_password(str(sel_email_row["app_password_encrypted"]))

                            # Try to get resume PDF
                            attach_bytes = None
                            attach_name  = None
                            if draft.get("resume_id") and spark:
                                try:
                                    res_df = spark.sql(f"SELECT docx_path FROM {CATALOG}.default.generated_resumes WHERE resume_id = '{draft['resume_id']}'").collect()
                                    if res_df:
                                        pass  # PDF attachment via DBFS (simplified for now)
                                except Exception:
                                    pass

                            with st.spinner("Sending..."):
                                ok, msg = send_email_smtp(
                                    smtp_host     = str(sel_email_row["smtp_host"]),
                                    smtp_port     = int(sel_email_row["smtp_port"]),
                                    from_email    = str(sel_email_row["email_address"]),
                                    password      = password,
                                    to_email      = str(draft["to_email"]),
                                    subject       = new_subject,
                                    body_text     = new_body,
                                    display_name  = str(sel_email_row["display_name"]),
                                    attachment_bytes = attach_bytes,
                                    attachment_name  = attach_name,
                                )

                            if ok:
                                if spark:
                                    spark.sql(f"""
                                        UPDATE {CATALOG}.default.email_drafts
                                        SET status = 'sent', sent_at = current_timestamp(),
                                            smtp_response = 'OK'
                                        WHERE draft_id = '{draft['draft_id']}'
                                    """)
                                    # Record submission
                                    spark.sql(f"""
                                        INSERT INTO {CATALOG}.default.job_submissions VALUES
                                        ('{uuid.uuid4()}', '{user_id}', '{draft['job_hash']}',
                                         NULL, '{draft['resume_id']}', current_timestamp(),
                                         'email_smtp', 'submitted')
                                    """)
                                st.success("✅ Email sent successfully!")
                                st.rerun()
                            else:
                                if spark:
                                    spark.sql(f"UPDATE {CATALOG}.default.email_drafts SET smtp_response = '{msg[:200]}' WHERE draft_id = '{draft['draft_id']}'")
                                st.error(f"❌ Send failed: {msg}")
                    else:
                        st.info(f"No HR email. [Apply via link]({draft['apply_link']})")

                with btn3:
                    if st.button("🗑️ Discard", key=f"disc_{draft['draft_id']}"):
                        if spark:
                            spark.sql(f"UPDATE {CATALOG}.default.email_drafts SET status = 'discarded' WHERE draft_id = '{draft['draft_id']}'")
                        st.rerun()

# ════════════════════════════════
# TAB 2: Recruiter Reply Analyzer
# ════════════════════════════════
with tab_analyze:
    st.subheader("🤖 Analyze Recruiter Email → Auto-Draft Reply")
    st.info("Paste any recruiter email below. AI will analyze sentiment and draft a professional reply for you.")

    col1, col2 = st.columns(2)
    with col1:
        recruiter_email_text = st.text_area(
            "Paste Recruiter Email Here",
            height=250,
            placeholder="Dear Candidate,\n\nThank you for your application...",
        )
    with col2:
        job_options_df = run_sql(f"""
            SELECT j.job_hash, j.job_title, j.company_name
            FROM {CATALOG}.default.job_submissions s
            JOIN {CATALOG}.default.jobs_clean_silver j ON s.job_hash = j.job_hash
            WHERE s.user_id = '{user_id}'
            LIMIT 50
        """)
        if not job_options_df.empty:
            job_opts = {f"{r['job_title']} @ {r['company_name']}": (r['job_hash'], r['job_title'], r['company_name'])
                       for _, r in job_options_df.iterrows()}
            sel_job_label = st.selectbox("Which job is this about?", list(job_opts.keys()))
            sel_job_hash, sel_job_title, sel_job_company = job_opts[sel_job_label]
        else:
            sel_job_title   = st.text_input("Job Title", placeholder="Data Engineer")
            sel_job_company = st.text_input("Company", placeholder="Acme Corp")
            sel_job_hash    = ""

    if st.button("🤖 Analyze & Generate Reply", type="primary", disabled=not recruiter_email_text):
        with st.spinner("AI analyzing recruiter email..."):
            analysis = ai_analyze_recruiter_email(
                recruiter_email_text, sel_name, sel_job_title, sel_job_company
            )

        # Sentiment display
        sentiment_colors = {
            "positive": "🟢", "schedule_interview": "🟢",
            "neutral": "🟡", "request_info": "🟡",
            "negative": "🔴",
        }
        sent_icon = sentiment_colors.get(analysis.get("sentiment", ""), "⚪")
        st.markdown(f"**Sentiment:** {sent_icon} {analysis.get('sentiment', 'unknown').replace('_',' ').title()}")
        st.markdown(f"**Key Points:** {analysis.get('key_points','')}")
        st.markdown(f"**Recommended Action:** {analysis.get('recommended_action','')}")
        st.markdown(f"**Urgency:** `{analysis.get('urgency','medium')}`")

        st.markdown("---")
        st.markdown("**✏️ AI-Drafted Reply (edit before saving)**")

        edited_reply_subj = st.text_input("Reply Subject", value=analysis.get("reply_subject",""))
        edited_reply_body = st.text_area("Reply Body", value=analysis.get("reply_body",""), height=300)

        col_sv, col_send = st.columns(2)
        with col_sv:
            if st.button("💾 Save as Draft"):
                if spark and sel_job_hash:
                    draft_row_data = {
                        "draft_id":           str(uuid.uuid4()),
                        "user_id":            user_id,
                        "job_hash":           sel_job_hash,
                        "match_id":           None,
                        "resume_id":          None,
                        "from_email":         email_cfg_df.iloc[0]["email_address"] if not email_cfg_df.empty else "",
                        "to_email":           None,
                        "subject":            edited_reply_subj,
                        "body_html":          edited_reply_body.replace("\n", "<br>"),
                        "body_text":          edited_reply_body,
                        "draft_type":         "recruiter_reply",
                        "parent_draft_id":    None,
                        "recruiter_email_raw":recruiter_email_text[:2000],
                        "status":             "draft",
                        "created_at":         datetime.now(),
                        "sent_at":            None,
                        "smtp_response":      None,
                        "is_user_edited":     True,
                    }
                    df_row = spark.createDataFrame([draft_row_data])
                    df_row.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.default.email_drafts")
                    st.success("✅ Reply draft saved! Find it in the Drafts tab.")

# ════════════════════════════════
# TAB 3: Sent History
# ════════════════════════════════
with tab_sent:
    st.subheader("📤 Sent Email History")
    sent_df = run_sql(f"""
        SELECT d.sent_at, d.to_email, d.subject, d.smtp_response,
               j.job_title, j.company_name
        FROM {CATALOG}.default.email_drafts d
        JOIN {CATALOG}.default.jobs_clean_silver j ON d.job_hash = j.job_hash
        WHERE d.user_id = '{user_id}' AND d.status = 'sent'
        ORDER BY d.sent_at DESC
        LIMIT 100
    """)

    if sent_df.empty:
        st.info("No emails sent yet.")
    else:
        st.dataframe(
            sent_df[["sent_at", "job_title", "company_name", "to_email", "subject", "smtp_response"]],
            use_container_width=True,
            hide_index=True,
        )
        st.markdown(f"**Total sent:** {len(sent_df)}")
