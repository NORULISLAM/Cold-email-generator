# set writable caches BEFORE other imports (fix PermissionError: '/.cache')
import os
import pathlib

os.environ.setdefault("XDG_CACHE_HOME", "/tmp/.cache")
os.environ.setdefault("HF_HOME", "/tmp/hf")
os.environ.setdefault("TRANSFORMERS_CACHE", "/tmp/hf/transformers")
os.environ.setdefault("HF_HUB_CACHE", "/tmp/hf/hub")
os.environ.setdefault("USER_AGENT", "Mozilla/5.0")
for p in ("/tmp/.cache", "/tmp/hf", "/tmp/hf/transformers", "/tmp/hf/hub"):
    pathlib.Path(p).mkdir(parents=True, exist_ok=True)

import requests  # needs: requests
import streamlit as st
from bs4 import BeautifulSoup  # needs: beautifulsoup4
from chains import Chain
from langchain_community.document_loaders import WebBaseLoader
from portfolio import Portfolio
from utils import clean_text

st.set_page_config(layout="wide", page_title="Cold Email Generator", page_icon="📧")


def fetch_text(url: str) -> str:
    """Try LangChain loader first; if short/empty, fallback to requests+bs4."""
    text = ""
    try:
        loader = WebBaseLoader(
            [url],
            header_template={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0")},
        )
        docs = loader.load()
        if docs:
            text = docs[0].page_content or ""
    except Exception:
        text = ""

    # Fallback for JS-heavy/blocked pages
    if len(text) < 800:
        try:
            r = requests.get(url, headers={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0")}, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)
        except Exception:
            pass

    return text


def create_streamlit_app(llm, portfolio, clean_text_fn):
    st.title("📧 Cold Mail Generator")
    url_input = st.text_input(
        "Enter a URL:",
        value="https://careers.nike.com/software-engineer-ii-o9-itc/job/R-68436"
    )
    use_raw = st.checkbox("Debug: use RAW text (skip clean_text)", value=False)

    if st.button("Submit"):
        try:
            raw = fetch_text(url_input)
            st.caption(f"Fetched characters: {len(raw)}")

            if not raw or len(raw) < 200:
                st.warning("Very little text fetched. The page might be JS-rendered or blocking bots.")
                st.text_area("Debug preview (raw)", raw[:2000], height=160)
                return

            data = raw if use_raw else clean_text_fn(raw)

            portfolio.load_portfolio()
            jobs = llm.extract_jobs(data) or []

            if not jobs:
                st.warning("No jobs found on the page.")
                st.text_area("Debug preview (processed)", data[:2000], height=200)
                return

            for job in jobs:
                skills = job.get("skills", []) or []
                links = portfolio.query_links(skills)
                email = llm.write_mail(job, links)
                st.code(email, language="markdown")

        except Exception as e:
            st.error(f"An Error Occurred: {e}")


if __name__ == "__main__":
    chain = Chain()
    portfolio = Portfolio()
    create_streamlit_app(chain, portfolio, clean_text)
