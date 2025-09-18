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
        # Fill once per process
        if self.collection.count() == 0:
            docs, metas, ids = [], [], []
            for _, row in self.data.iterrows():
                docs.append(str(row["Techstack"]))
                metas.append({"links": str(row["Links"])})
                ids.append(str(uuid.uuid4()))
            self.collection.add(documents=docs, metadatas=metas, ids=ids)

    def query_links(self, skills):
        if not skills:
            return []
        res = self.collection.query(
            query_texts=list(skills),
            n_results=2,
            include=["metadatas"],
        )
        md = res.get("metadatas") or []   # guard None
        links, seen = [], set()
        for group in md or []:
            if not group:
                continue
            for m in group:
                if isinstance(m, dict):
                    link = m.get("links")
                    if link and link not in seen:
                        seen.add(link)
                        links.append(link)
        return links
