# Force writable caches BEFORE any other imports
import json
import os
import pathlib
import re
import time
import traceback

import requests
import streamlit as st
from bs4 import BeautifulSoup
from chains import Chain
from langchain_community.document_loaders import WebBaseLoader
from portfolio import Portfolio
from utils import clean_text

# Always override (not setdefault)
os.environ["XDG_CACHE_HOME"] = "/tmp/.cache"
os.environ["HF_HOME"] = "/tmp/hf"
os.environ["TRANSFORMERS_CACHE"] = "/tmp/hf/transformers"
os.environ["HF_HUB_CACHE"] = "/tmp/hf/hub"
os.environ["USER_AGENT"] = "Mozilla/5.0"

# Optional: silence Chroma telemetry noise
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["CHROMA_TELEMETRY_IMPLEMENTATION"] = "none"

for p in ("/tmp/.cache", "/tmp/hf", "/tmp/hf/transformers", "/tmp/hf/hub"):
    pathlib.Path(p).mkdir(parents=True, exist_ok=True)

st.set_page_config(layout="wide", page_title="AIジョブサーチ", page_icon="📧")


def extract_company_from_url(url):
    """Extract likely company name from URL"""
    try:
        if "greenhouse.io" in url:
            m = re.search(r'greenhouse\.io/([^/]+)', url)
            if m:
                return m.group(1).replace('-', ' ').title()
        elif "lever.co" in url:
            m = re.search(r'lever\.co/([^/]+)', url)
            if m:
                return m.group(1).replace('-', ' ').title()
        else:
            m = re.search(r'://(?:www\.)?([^./]+)', url)
            if m:
                return m.group(1).replace('-', ' ').title()
    except:
        pass
    return "Company, Inc."


def fetch_text(url: str) -> str:
    """Try LangChain loader first; if short/empty, fallback to requests+bs4."""
    text = ""
    st.write(f"🔍 Fetching text from: {url}")

    try:
        loader = WebBaseLoader(
            [url],
            header_template={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0")},
        )
        docs = loader.load()
        if docs:
            text = docs[0].page_content or ""
            st.write(f"✅ WebBaseLoader succeeded: {len(text)} characters")
    except Exception as e:
        st.write(f"❌ WebBaseLoader failed: {str(e)}")
        text = ""

    if len(text) < 800:
        st.write("🔄 Trying fallback with requests + BeautifulSoup...")
        try:
            r = requests.get(url, headers={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0")}, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            st.write(f"✅ Fallback succeeded: {len(text)} characters")
        except Exception as e:
            st.write(f"❌ Fallback also failed: {str(e)}")

    return text


def split_jp_en(email_text: str):
    """Split the composite email into JP / EN sections."""
    jp, en = "", email_text or ""
    if not en:
        return "", ""
    if "--- JAPANESE VERSION ---" in en and "--- ENGLISH VERSION ---" in en:
        parts = en.split("--- JAPANESE VERSION ---", 1)
        if len(parts) > 1:
            tail = parts[1]
            if "--- ENGLISH VERSION ---" in tail:
                jp, en = tail.split("--- ENGLISH VERSION ---", 1)
                return jp.strip(), en.strip()
    return "", (email_text or "").strip()


def why_fit_bullets(required_skills, techstack_hits, limit=6):
    bullets = []
    req = (required_skills or [])[:limit]
    if techstack_hits:
        for s in req:
            hit = next((h for h in techstack_hits if s and s.lower() in (h or "").lower()), None)
            if hit:
                bullets.append(f"- **{s}** → portfolio evidence: {hit}")
    if not bullets and techstack_hits:
        bullets.append(f"- Portfolio coverage: {', '.join(techstack_hits[:5])}")
    if not bullets and req:
        bullets.append("- Skills recognized, but no direct portfolio match found (demo).")
    return bullets


def create_streamlit_app(llm, portfolio, clean_text_fn):
    st.title("📧 AIジョブサーチ")

    # --- KPI Cockpit (Sidebar) ---
    with st.sidebar:
        st.header("📊 Outreach KPIs")
        ctr = st.number_input("CTR % (demo)", min_value=0.0, max_value=100.0, value=5.0, step=0.1)
        apply_rate = st.number_input("Apply-rate % (demo)", min_value=0.0, max_value=100.0, value=2.0, step=0.1)
        p95_placeholder = st.empty()
        halluc_pct = st.number_input("Hallucination % (demo)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        st.caption("Note: CTR/Apply/Halluc% are demo inputs. P95 computed from this run.")

    # URL Input
    url_input = st.text_input(
        "URLを入力してください:",
        value="https://www.green-japan.com/company/9772/job/287587"
    )

    # Auto-extract company
    auto_company = extract_company_from_url(url_input) if url_input else "Company, Inc."

    # Layout
    col1, col2 = st.columns(2)
    with col1:
        company = st.text_input("会社名 (Company Name)", value=auto_company)
        recipient = st.text_input("宛先 (Recipient Name)", value="採用担当者様")
    with col2:
        role = st.text_input("役職 (Role Title)", value="AI/ML Engineer",
                             help="This will be updated automatically when job is extracted")
        use_raw = st.checkbox("Debug: use RAW text (skip clean_text)", value=False)

    auto_update_role = st.checkbox("✅ Auto-update role title from job posting", value=True)

    if st.button("送信", type="primary"):
        try:
            st.write("=" * 50)
            st.write("🚀 **DEBUG: Starting processing...**")
            st.caption(f"Prompt registry: {getattr(Chain, 'PROMPT_VERSION', 'N/A')}")  # show prompt version

            # ---------------- Agent Orchestration ----------------
            st.write("### 🧠 Agent Orchestration")
            phase_times = {}

            with st.status("Research: fetching job page...", expanded=True) as status:
                t0 = time.time()
                raw = fetch_text(url_input)
                phase_times["Research"] = time.time() - t0
                if not raw or len(raw) < 200:
                    st.warning("取得できたテキストが非常に少ないため、このページは JS レンダリング/ボットブロックの可能性があります。")
                    st.text_area("Debug preview (raw)", raw[:2000], height=160)
                    status.update(label="Research failed", state="error")
                    return
                status.update(label="Research done", state="complete")

            with st.status("Analysis: cleaning + preview...", expanded=False) as status:
                t0 = time.time()
                data = raw if use_raw else clean_text_fn(raw)
                phase_times["Analysis"] = time.time() - t0
                with st.expander("Processed text (first 1000 chars)"):
                    st.text(data[:1000])
                status.update(label="Analysis done", state="complete")

                # Step 2: Clean text
                st.write("**Step 2: Processing text**")
                data = raw if use_raw else clean_text_fn(raw)
                st.write(f"📊 Processed text length: {len(data)}")
                with st.expander("View processed text (first 1000 chars)"):
                    st.text(data[:1000])


            # Load portfolio
            try:
                portfolio.load_portfolio()
                st.write("✅Step 3: Portfolio loaded successfully")
            except Exception as e:
                st.error(f"❌ Portfolio loading failed: {str(e)}")
                st.write(traceback.format_exc())
                return

            with st.status("Strategy: extracting job specs...", expanded=False) as status:
                t0 = time.time()
                jobs = llm.extract_jobs(data)
                phase_times["Strategy"] = time.time() - t0
                st.write(f"📊 Jobs extracted: {len(jobs) if jobs else 0}")
                if jobs:
                    st.write("**Extracted jobs preview:**")
                    for i, job in enumerate(jobs):
                        with st.expander(f"Job {i + 1}: {job.get('role', 'Unknown role')}"):
                            st.json(job)
                else:
                    st.write("⚠️ No jobs found")
                    status.update(label="Strategy found no jobs", state="error")
                    return
                if not jobs:
                    st.warning("ページに求人が見つかりませんでした。")
                    st.text_area("Debug preview (processed)", data[:2000], height=200)
                    return

                status.update(label="Strategy done", state="complete")

            # -------- Writer & Quality per job --------
            st.write("**Step 5: Generating personalized emails**")
            latencies = []
            for i, job in enumerate(jobs):
                st.write(f"**Processing job {i + 1}:**")

                # Role update
                current_role = role
                if auto_update_role and job.get('role'):
                    current_role = job.get('role')
                    st.info(f"🔄 Auto-updated role to: **{current_role}**")

                # JD block
                jd_block = (
                    f"Role: {job.get('role', 'N/A')}\n"
                    f"Experience: {job.get('experience', 'N/A')}\n"
                    f"Skills: {', '.join(job.get('skills', []))}\n"
                    f"Description: {job.get('description', 'N/A')}"
                )
                st.write("**求人情報ブロック:**")
                st.text(jd_block)

                # Techstack match
                st.write("**Querying portfolio for relevant techstack...**")
                try:
                    cues = (job.get("skills") or [])[:8]
                    st.write(f"Skills cues: {cues}")
                    techstack_hits = portfolio.query_techstack(skills=cues, n_results=8)
                    st.write(f"Techstack hits found: {len(techstack_hits) if techstack_hits else 0}")
                    if techstack_hits:
                        with st.expander("View matched techstack"):
                            for hit in techstack_hits:
                                st.write(f"- {hit}")
                except Exception as e:

                    st.error(f"❌ Techstack query failed: {str(e)}")
                    st.write(traceback.format_exc())
                    techstack_hits = []

                    # Generate email with actual job data
                    st.write("**Generating personalized email...**")
                    try:
                        email = llm.write_mail(
                            job_description=jd_block,
                            company_name=company,
                            recipient_name=recipient,
                            role_title=current_role,
                            techstack_list=techstack_hits or [],
                            extracted_job_data=job  # Pass the actual job data
                        )

                        st.write("**Generated Email:**")
                        st.write(f"Email length: {len(email) if email else 0} characters")

                        if email:
                            st.subheader(f"📧 Email for {job.get('role', 'Unknown role')}")
                            with st.container():

                                st.markdown("### Generated Email Content")
                                st.code(email, language="markdown")

                                # Add copy button functionality
                                st.download_button(
                                    label="💾 Download Email as Text",
                                    data=email,
                                    file_name=f"cold_email_{company}_{current_role.replace('/', '_')}.txt",
                                    mime="text/plain"
                                )
                        else:
                            st.error("❌ Empty email generated!")

                    except Exception as e:
                        st.error(f"❌ Email generation failed: {str(e)}")
                        st.write(traceback.format_exc())

                    st.write("---")  # Separator between jobs

                except Exception as e:
                    st.error(f"❌ Unexpected error: {str(e)}")
                    st.write("**Full traceback:**")
                    st.code(traceback.format_exc())

                # Why-fit panel
                st.subheader("🔎(フィット理由（エビデンス）")
                st.markdown("\n".join(why_fit_bullets(job.get("skills"), techstack_hits)))

                # Writer + Quality
                with st.status("Writer→Quality: generating JP/EN emails...", expanded=False) as status:
                    t0 = time.time()
                    email = llm.write_mail(
                        job_description=jd_block,
                        company_name=company,
                        recipient_name=recipient,
                        role_title=current_role,
                        techstack_list=techstack_hits or [],
                        extracted_job_data=job
                    )
                    latency = time.time() - t0
                    latencies.append(latency)
                    st.write(f"Email length: {len(email) if email else 0} characters")
                    jp, en = split_jp_en(email or "")
                    if not (jp or en):
                        st.error("❌ Could not split JP/EN sections.")
                        status.update(label="Writer/Quality failed", state="error")
                    else:
                        tabs = st.tabs(["🇯🇵 JP", "🇺🇸 EN"])
                        with tabs[0]:
                            st.code(jp, language="markdown")
                            st.download_button(
                                "💾 Copy Recruiter Email (JP)",
                                data=jp,
                                file_name=f"jp_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain"
                            )
                            st.download_button(
                                "💾 Copy Manager Email (JP)",
                                data=jp,
                                file_name=f"jp_mgr_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain"
                            )
                        with tabs[1]:
                            st.code(en, language="markdown")
                            st.download_button(
                                "💾 Copy Recruiter Email (EN)",
                                data=en,
                                file_name=f"en_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain"
                            )
                            st.download_button(
                                "💾 Copy Manager Email (EN)",
                                data=en,
                                file_name=f"en_mgr_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain"
                            )
                        status.update(label="メール済み", state="complete")

                # Follow-up plan
                with st.expander("📅 Follow-up plan (3d / 7d / 14d)", expanded=False):
                    st.markdown("""
- **Day 3:** Short nudge, reference one portfolio win tied to JD.
- **Day 7:** New angle: outcomes/KPIs (scalability, latency, cost).
- **Day 14:** Final check-in + small tailored code/demo for their JD.
""")
                st.write("---")

            # P95 latency
            if latencies:
                latencies_sorted = sorted(latencies)
                p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
                p95 = latencies_sorted[p95_idx]
                p95_placeholder.metric("P95 Latency (s)", f"{p95:.2f}")

            st.caption("🔐 Privacy: No third-party data exfiltration; PII is redacted in logs.")

        except Exception as e:
            st.error(f"❌ Unexpected error: {str(e)}")
            st.write("**Full traceback:**")
            st.code(traceback.format_exc())


if __name__ == "__main__":
    try:
        st.write("🔧 **Initializing components...**")
        st.write("Creating Chain...")
        chain = Chain()
        st.write("✅ Chain created")

        st.write("Creating Portfolio...")
        portfolio = Portfolio()
        st.write("✅ Portfolio created")

        create_streamlit_app(chain, portfolio, clean_text)

    except Exception as e:
        st.error(f"❌ Initialization failed: {str(e)}")
        st.code(traceback.format_exc())
