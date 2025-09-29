# app/main.py
# キャッシュ系を先に設定（HF/Transformers が書き込み可能な場所を使用）
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

# キャッシュ/UA設定（必ず上書き）
os.environ["XDG_CACHE_HOME"] = "/tmp/.cache"
os.environ["HF_HOME"] = "/tmp/hf"
os.environ["TRANSFORMERS_CACHE"] = "/tmp/hf/transformers"
os.environ["HF_HUB_CACHE"] = "/tmp/hf/hub"
os.environ["USER_AGENT"] = "Mozilla/5.0"

# Chroma等のテレメトリ抑制（任意）
os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["CHROMA_TELEMETRY_IMPLEMENTATION"] = "none"

for p in ("/tmp/.cache", "/tmp/hf", "/tmp/hf/transformers", "/tmp/hf/hub"):
    pathlib.Path(p).mkdir(parents=True, exist_ok=True)

st.set_page_config(layout="wide", page_title="AIジョブサーチ", page_icon="📧")


def extract_company_from_url(url: str) -> str:
    """URLから会社名らしきものを推定"""
    try:
        if "greenhouse.io" in url:
            m = re.search(r"greenhouse\.io/([^/]+)", url)
            if m:
                return m.group(1).replace("-", " ").title()
        elif "lever.co" in url:
            m = re.search(r"lever\.co/([^/]+)", url)
            if m:
                return m.group(1).replace("-", " ").title()
        else:
            m = re.search(r"://(?:www\.)?([^./]+)", url)
            if m:
                return m.group(1).replace("-", " ").title()
    except:
        pass
    return "Company, Inc."


def fetch_text(url: str) -> str:
    """まず LangChain Loader、短ければ requests+BS4 にフォールバック"""
    text = ""
    st.write(f"🔍 取得先URL: {url}")

    try:
        loader = WebBaseLoader(
            [url],
            header_template={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0")},
        )
        docs = loader.load()
        if docs:
            text = docs[0].page_content or ""
            st.write(f"✅ WebBaseLoader 成功: {len(text)} 文字")
    except Exception as e:
        st.write(f"❌ WebBaseLoader 失敗: {str(e)}")
        text = ""

    if len(text) < 800:
        st.write("🔄 フォールバック実行（requests + BeautifulSoup）...")
        try:
            r = requests.get(
                url,
                headers={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0")},
                timeout=20,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            st.write(f"✅ フォールバック成功: {len(text)} 文字")
        except Exception as e:
            st.write(f"❌ フォールバックも失敗: {str(e)}")

    return text


def split_jp_en(email_text: str):
    """メール本文から JP / EN を分離（区切りが無い場合は全体をENとして返す）"""
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
    """適合理由（エビデンス）を簡易生成"""
    bullets = []
    req = (required_skills or [])[:limit]
    if techstack_hits:
        for s in req:
            hit = next((h for h in techstack_hits if s and s.lower() in (h or "").lower()), None)
            if hit:
                bullets.append(f"- **{s}** → ポートフォリオ裏付け: {hit}")
    if not bullets and techstack_hits:
        bullets.append(f"- ポートフォリオ対応領域: {', '.join(techstack_hits[:5])}")
    if not bullets and req:
        bullets.append("- スキル認識済み（デモ）/ 直接のポートフォリオ一致は見つかりませんでした。")
    return bullets


def create_streamlit_app(llm, portfolio, clean_text_fn):
    st.title("📧 AIジョブサーチ（コールドメール自動生成）")

    # --- KPI（サイドバー） ---
    with st.sidebar:
        st.header("📊 アウトリーチKPI（デモ）")
        ctr = st.number_input("CTR（クリック率）%（デモ）", min_value=0.0, max_value=100.0, value=5.0, step=0.1)
        apply_rate = st.number_input("応募率 %（デモ）", min_value=0.0, max_value=100.0, value=2.0, step=0.1)
        p95_placeholder = st.empty()
        halluc_pct = st.number_input("ハルシネーション率 %（デモ）", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
        st.caption("注: CTR/応募率/ハルシネ率は入力用デモ値。P95は実行結果から算出。")

    # URL入力
    url_input = st.text_input(
        "求人ページURLを入力してください：",
        value="https://www.green-japan.com/company/9772/job/287587",
    )

    # URLから会社名を推定
    auto_company = extract_company_from_url(url_input) if url_input else "Company, Inc."

    # 入力レイアウト
    col1, col2 = st.columns(2)
    with col1:
        company = st.text_input("会社名", value=auto_company)
        recipient = st.text_input("宛先（担当者）", value="採用ご担当者様")
    with col2:
        role = st.text_input("役職（ロール）", value="AI/MLエンジニア", help="求人抽出後に自動更新されます")
        use_raw = st.checkbox("デバッグ: クレンジングをスキップしてRAWを使用", value=False)

    auto_update_role = st.checkbox("求人抽出で役職名を自動更新する", value=True)

    if st.button("実行", type="primary"):
        try:
            st.write("—" * 40)
            st.write("🚀 **処理開始（デバッグ情報）**")
            st.caption(f"プロンプトバージョン: {getattr(Chain, 'PROMPT_VERSION', 'N/A')}")

            # ---------------- 調査フェーズ ----------------
            with st.status("調査: 求人ページの取得中...", expanded=True) as status:
                t0 = time.time()
                raw = fetch_text(url_input)
                research_time = time.time() - t0
                if not raw or len(raw) < 200:
                    st.warning("取得テキストが極端に少ないため、このページはJSレンダリング/ボット対策の可能性があります。")
                    st.text_area("デバッグ（RAW先頭2000文字）", raw[:2000], height=160)
                    status.update(label="調査失敗", state="error")
                    return
                status.update(label="調査完了", state="complete")

            # ---------------- 分析フェーズ ----------------
            with st.status("分析: テキスト整形 + 簡易プレビュー...", expanded=False) as status:
                t0 = time.time()
                data = raw if use_raw else clean_text_fn(raw)
                analysis_time = time.time() - t0

                # 非エクスパンダ（安全）プレビュー
                st.markdown("**テキスト整形プレビュー（先頭1000文字）**")
                st.text(data[:1000])

                status.update(label="分析完了", state="complete")

            # ---------------- ポートフォリオ読込 ----------------
            try:
                portfolio.load_portfolio()
                st.success("ステップ3: ポートフォリオ読込に成功しました。")
            except Exception as e:
                st.error(f"ポートフォリオ読込に失敗しました: {str(e)}")
                st.code(traceback.format_exc())
                return

            # ---------------- 戦略フェーズ（求人抽出） ----------------
            with st.status("戦略: 求人要件を抽出中...", expanded=False) as status:
                t0 = time.time()
                jobs = llm.extract_jobs(data)
                strategy_time = time.time() - t0
                st.write(f"抽出された求人数: {len(jobs) if jobs else 0}")

                if not jobs:
                    st.warning("ページ内に求人が見つかりませんでした。")
                    st.text_area("デバッグ（整形テキスト先頭2000文字）", data[:2000], height=200)
                    status.update(label="戦略: 求人無し", state="error")
                    return

                # 求人プレビュー（非エクスパンダ）
                st.markdown("### 抽出結果プレビュー")
                for i, job in enumerate(jobs):
                    st.markdown(f"**求人 {i+1}: {job.get('role', '役職名不明')}**")
                    st.json(job)

                status.update(label="戦略完了", state="complete")

            # ---------------- Writer & Quality（求人ごと） ----------------
            st.markdown("## ステップ5: パーソナライズドメール生成")
            latencies = []

            for i, job in enumerate(jobs):
                st.markdown(f"### 対象求人 {i+1}")

                # 役職名の自動更新
                current_role = role
                if auto_update_role and job.get("role"):
                    current_role = job.get("role")
                    st.info(f"役職名を自動更新: **{current_role}**")

                # JDブロック表示（日本語UI）
                jd_block = (
                    f"役職: {job.get('role', 'N/A')}\n"
                    f"経験: {job.get('experience', 'N/A')}\n"
                    f"スキル: {', '.join(job.get('skills', []))}\n"
                    f"説明: {job.get('description', 'N/A')}"
                )
                st.markdown("**求人情報ブロック**")
                st.text(jd_block)

                # Techstackマッチ
                st.markdown("**ポートフォリオ技術マッチング**")
                try:
                    cues = (job.get("skills") or [])[:8]
                    st.write(f"スキル候補: {cues}")
                    techstack_hits = portfolio.query_techstack(skills=cues, n_results=8)
                    st.write(f"一致テックスタック数: {len(techstack_hits) if techstack_hits else 0}")
                    if techstack_hits:
                        st.markdown("**一致テックスタック**")
                        st.write("\n".join([f"- {hit}" for hit in techstack_hits]))
                except Exception as e:
                    st.error(f"テックスタック照会に失敗: {str(e)}")
                    st.code(traceback.format_exc())
                    techstack_hits = []

                # 適合理由（エビデンス）
                st.subheader("🔎 適合理由（根拠）")
                st.markdown("\n".join(why_fit_bullets(job.get("skills"), techstack_hits)))

                # Writer→Quality（JP/ENタブ、非エクスパンダ）
                with st.status("Writer→Quality: JP/ENメールを生成中...", expanded=False) as status:
                    t0 = time.time()
                    email = llm.write_mail(
                        job_description=jd_block,
                        company_name=company,
                        recipient_name=recipient,
                        role_title=current_role,
                        techstack_list=techstack_hits or [],
                        extracted_job_data=job,
                    )
                    latency = time.time() - t0
                    latencies.append(latency)
                    st.write(f"メール本文長: {len(email) if email else 0} 文字")

                    jp, en = split_jp_en(email or "")
                    if not (jp or en):
                        st.error("JP/ENの区切り検出に失敗しました。生成テンプレートをご確認ください。")
                        status.update(label="Writer/Quality 失敗", state="error")
                    else:
                        st.subheader(f"📧 生成メール（{current_role}）")
                        tabs = st.tabs(["🇯🇵 日本語", "🇺🇸 英語"])
                        with tabs[0]:
                            st.markdown("#### 日本語版")
                            st.code(jp, language="markdown")
                            st.download_button(
                                "💾 日本語（採用担当向け）を保存",
                                data=jp,
                                file_name=f"jp_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain",
                            )
                            st.download_button(
                                "💾 日本語（マネージャ向け）を保存",
                                data=jp,
                                file_name=f"jp_mgr_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain",
                            )
                        with tabs[1]:
                            st.markdown("#### 英語版")
                            st.code(en, language="markdown")
                            st.download_button(
                                "💾 英語（採用担当向け）を保存",
                                data=en,
                                file_name=f"en_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain",
                            )
                            st.download_button(
                                "💾 英語（マネージャ向け）を保存",
                                data=en,
                                file_name=f"en_mgr_{company}_{current_role.replace('/', '_')}.txt",
                                mime="text/plain",
                            )
                        status.update(label="メール作成完了", state="complete")

                # フォローアップ計画（非エクスパンダ）
                st.markdown("#### 📅 フォローアップ計画（3日／7日／14日）")
                st.markdown(
                    """
- **3日目**: 軽いリマインド。求人に直結するポートフォリオ成果を1つ引用。
- **7日目**: 観点変更（KPI: スケーラビリティ/レイテンシ/コスト）。
- **14日目**: 最終確認＋求人に沿った小さな追加デモ/コードを添付。
                    """.strip()
                )

                st.write("---")

            # P95レイテンシ
            if latencies:
                latencies_sorted = sorted(latencies)
                p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
                p95 = latencies_sorted[p95_idx]
                p95_placeholder.metric("P95レイテンシ（秒）", f"{p95:.2f}")

            st.caption("🔐 プライバシー: 外部への個人情報送出なし。ログ内PIIはマスク処理。")

        except Exception as e:
            st.error(f"予期しないエラーが発生しました: {str(e)}")
            st.markdown("**トレースバック**")
            st.code(traceback.format_exc())


if __name__ == "__main__":
    try:
        st.write("🔧 初期化中...")
        st.write("Chainを作成中...")
        chain = Chain()
        st.success("Chain作成完了")

        st.write("Portfolioを作成中...")
        portfolio = Portfolio()
        st.success("Portfolio作成完了")

        create_streamlit_app(chain, portfolio, clean_text)

    except Exception as e:
        st.error(f"初期化に失敗しました: {str(e)}")
        st.code(traceback.format_exc())
