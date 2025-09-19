import uuid

import chromadb
import pandas as pd
from chromadb.config import Settings


class Portfolio:
    def __init__(self, file_path="app/resource/my_portfolio.csv"):
        self.data = pd.read_csv(file_path)

        # FREE deploy: in-memory DB (no filesystem writes) + no telemetry
        self.chroma_client = chromadb.EphemeralClient(
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.chroma_client.get_or_create_collection(name="portfolio")

    def load_portfolio(self):
        """Index ONLY Techstack strings. No links stored."""
        if self.collection.count() == 0:
            docs, ids = [], []
            for _, row in self.data.iterrows():
                tech = str(row.get("Techstack", "")).strip()
                if not tech:
                    continue
                docs.append(tech)
                ids.append(str(uuid.uuid4()))
            # No metadatas field at all
            self.collection.add(documents=docs, ids=ids)

    def query_techstack(self, skills, n_results=5):
        """Return top-matching Techstack strings (no links)."""
        if not skills:
            return []
        res = self.collection.query(
            query_texts=list(skills),
            n_results=n_results,
            include=["documents"],
        )
        docs_groups = res.get("documents") or []
        out, seen = [], set()
        for group in docs_groups:
            for d in group or []:
                d = (d or "").strip()
                if d and d not in seen:
                    seen.add(d)
                    out.append(d)
        return out