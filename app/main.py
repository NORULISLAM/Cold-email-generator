# Force writable caches BEFORE any other imports
import os
import pathlib
import requests
import streamlit as st
from bs4 import BeautifulSoup
from chains import Chain
from langchain_community.document_loaders import WebBaseLoader
from portfolio import Portfolio
from utils import clean_text
import traceback
import json
import re

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

st.set_page_config(layout="wide", page_title="コールドメールジェネレーター", page_icon="📧")


def extract_company_from_url(url):
    """Extract likely company name from URL"""
    try:
        # Extract domain and path patterns
        if "greenhouse.io" in url:
            # Pattern: job-boards.greenhouse.io/COMPANY/jobs/
            match = re.search(r'greenhouse\.io/([^/]+)', url)
            if match:
                company = match.group(1).replace('-', ' ').title()
                return company
        elif "lever.co" in url:
            # Pattern: jobs.lever.co/COMPANY/
            match = re.search(r'lever\.co/([^/]+)', url)
            if match:
                company = match.group(1).replace('-', ' ').title()
                return company
        else:
            # Try to extract from general URL patterns
            match = re.search(r'://(?:www\.)?([^./]+)', url)
            if match:
                company = match.group(1).replace('-', ' ').title()
                return company
    except:
        pass
    return "Company, Inc."


def fetch_text(url: str) -> str:
    """Try LangChain loader first; if short/empty, fallback to requests+bs4."""
    text = ""
    st.write(f"🔍 Fetching text from: {url}")

    try:
        st.write("📥 Trying WebBaseLoader...")
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

    # Fallback for JS-heavy/blocked pages
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


def create_streamlit_app(llm, portfolio, clean_text_fn):
    st.title("📧 コールドメールジェネレーター")

    # URL Input
    url_input = st.text_input(
        "URLを入力してください:",
        value="https://job-boards.greenhouse.io/zeals/jobs/5572548004"
    )

    # Auto-extract company name when URL changes
    if url_input:
        auto_company = extract_company_from_url(url_input)
    else:
        auto_company = "Company, Inc."

    # Create two columns for better layout
    col1, col2 = st.columns(2)

    with col1:
        company = st.text_input("会社名 (Company Name)", value=auto_company)
        recipient = st.text_input("宛先 (Recipient Name)", value="採用担当者様")

    with col2:
        role = st.text_input("役職 (Role Title)", value="AI/ML Engineer",
                             help="This will be updated automatically when job is extracted")
        use_raw = st.checkbox("Debug: use RAW text (skip clean_text)", value=False)

    # Add option to auto-update role from job posting
    auto_update_role = st.checkbox("✅ Auto-update role title from job posting", value=True)

    if st.button("送信", type="primary"):
        try:
            st.write("=" * 50)
            st.write("🚀 **DEBUG: Starting processing...**")

            # Step 1: Fetch text
            st.write("**Step 1: Fetching text**")
            raw = fetch_text(url_input)
            st.write(f"📊 Raw text length: {len(raw)}")

            if not raw or len(raw) < 200:
                st.warning(
                    "取得できたテキストが非常に少ないため、このページは JavaScript でレンダリングされているか、ボットをブロックしている可能性があります。")
                st.text_area("Debug preview (raw)", raw[:2000], height=160)
                return

            # Step 2: Clean text
            st.write("**Step 2: Processing text**")
            data = raw if use_raw else clean_text_fn(raw)
            st.write(f"📊 Processed text length: {len(data)}")

            with st.expander("View processed text (first 1000 chars)"):
                st.text(data[:1000])

            # Step 3: Load portfolio
            st.write("**Step 3: Loading portfolio**")
            try:
                portfolio.load_portfolio()
                st.write("✅ Portfolio loaded successfully")
            except Exception as e:
                st.error(f"❌ Portfolio loading failed: {str(e)}")
                st.write(traceback.format_exc())
                return

            # Step 4: Extract jobs
            st.write("**Step 4: Extracting jobs**")
            try:
                jobs = llm.extract_jobs(data)
                st.write(f"📊 Jobs extracted: {len(jobs) if jobs else 0}")

                if jobs:
                    st.write("**Extracted jobs preview:**")
                    for i, job in enumerate(jobs):
                        with st.expander(f"Job {i + 1}: {job.get('role', 'Unknown role')}"):
                            st.json(job)
                else:
                    st.write("⚠️ No jobs found")
            except Exception as e:
                st.error(f"❌ Job extraction failed: {str(e)}")
                st.write(traceback.format_exc())
                return

            if not jobs:
                st.warning("ページに求人が見つかりませんでした。")
                st.text_area("Debug preview (processed)", data[:2000], height=200)
                return

            # Step 5: Generate emails for each job
            st.write("**Step 5: Generating personalized emails**")
            for i, job in enumerate(jobs):
                st.write(f"**Processing job {i + 1}:**")

                # Dynamic role update
                current_role = role
                if auto_update_role and job.get('role'):
                    current_role = job.get('role')
                    st.info(f"🔄 Auto-updated role to: **{current_role}**")

                # Build a rich JD block for the prompt
                jd_block = (
                    f"Role: {job.get('role', 'N/A')}\n"
                    f"Experience: {job.get('experience', 'N/A')}\n"
                    f"Skills: {', '.join(job.get('skills', []))}\n"
                    f"Description: {job.get('description', 'N/A')}"
                )

                st.write("**Job Description Block:**")
                st.text(jd_block)

                # Use Techstack matcher
                st.write("**Querying portfolio for relevant techstack...**")
                try:
                    cues = (job.get("skills") or [])[:8]  # use top skills as cues
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
                        # Create expandable sections for better readability
                        with st.expander(f"📧 Email for {job.get('role', 'Unknown role')} (Click to expand)",
                                         expanded=True):
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