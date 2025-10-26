# app/services/readiness.py
import re
import math
import datetime as dt
from app.services.database import db
from prisma import Json

ASPECTS = [
    "ABOUT", "VALUE_PROP", "FEATURES", "PRICING", "INTEGRATIONS",
    "ONBOARDING", "SECURITY", "SUPPORT", "CASE_STUDIES", "IMPLEMENTATION", "LEGAL"
]

ASPECT_KEYWORDS = {
    "ABOUT":        [r"\bmission\b", r"\bvision\b", r"\bvalues?\b", r"\babout (us|company)\b"],
    "VALUE_PROP":   [r"\busp\b", r"\bvalue prop", r"\bdifferentiator", r"\bwhy (us|choose)\b", r"\bICP\b"],
    "FEATURES":     [r"\bfeature(s)?\b", r"\bcapabilit(y|ies)\b", r"\bmodule(s)?\b"],
    "PRICING":      [r"\bpricing\b", r"\bplan(s)?\b", r"₹|\$|€|USD|INR", r"\bper (month|year)"],
    "INTEGRATIONS": [r"\bintegration(s)?\b", r"\bAPI\b", r"\bwebhook(s)?\b"],
    "ONBOARDING":   [r"\bonboarding\b", r"\bgetting started\b", r"\bsetup\b", r"\bchecklist\b"],
    "SECURITY":     [r"\bsecurity\b", r"\bprivacy\b", r"\bSOC 2\b", r"\bISO 27001\b", r"\bGDPR\b", r"\bSLA\b"],
    "SUPPORT":      [r"\bFAQ\b", r"\btroubleshoot", r"\bhelp\b", r"\bsupport\b"],
    "CASE_STUDIES": [r"\bcase stud(y|ies)\b", r"\btestimonial(s)?\b", r"\bsuccess stor(y|ies)\b"],
    "IMPLEMENTATION":[r"\bdeploy(ment)?\b", r"\bmigration\b", r"\bimport\b"],
    "LEGAL":        [r"\bterms\b", r"\bprivacy policy\b", r"\bDPA\b", r"\bEULA\b"]
}

class GenericReadiness:
    def __init__(self):
        self.db = db

# app/services/readiness.py

    async def collect_texts(self, tenant_id: str) -> list[str]:
        texts: list[str] = []

        # 1) KnowledgeDocument (READY)
        documents = await self.db.knowledgedocument.find_many(
            where={"tenant_id": tenant_id, "status": "READY"},
        )
        for d in documents:
            if d and getattr(d, "extracted_text", None):
                texts.append(str(d.extracted_text))

        # 2) WebsiteContent (READY)
        websites = await self.db.websitecontent.find_many(
            where={"tenant_id": tenant_id, "status": "READY"},
        )
        for w in websites:
            if w and getattr(w, "crawl_summary", None):
                texts.append(str(w.crawl_summary))

        # 3) CompanyProfile (explicit field list, no .values())
        profile_fields = [
            "description", "mission", "values", "usp",
            "history", "key_personnel", "offering_description", "target_market"
        ]
        profiles = await self.db.companyprofile.find_many(
            where={"tenant_id": tenant_id},
        )
        company_ids: list[str] = []
        for p in profiles:
            company_ids.append(p.id)
            for f in profile_fields:
                v = getattr(p, f, None)
                if v:
                    texts.append(str(v))

        # 4) CompanyQA (for the tenant’s companies)
        if company_ids:
            company_qas = await self.db.companyqa.find_many(
                where={"company_id": {"in": company_ids}}
            )
            for qa in company_qas:
                q = getattr(qa, "question", None)
                a = getattr(qa, "answer", None)
                if q and a:
                    texts.append(f"Q: {q}\nA: {a}")
                elif q:
                    texts.append(f"Q: {q}")
                elif a:
                    texts.append(f"A: {a}")

        # 5) Products for those companies (single query)
        if company_ids:
            products = await self.db.product.find_many(
                where={"company_id": {"in": company_ids}}
            )
            product_ids: list[str] = []
            for prod in products:
                product_ids.append(prod.id)
                # Add each field explicitly (no .values())
                for f in ["name","category","description","features","benefits","pricing","target_audience","use_cases"]:
                    v = getattr(prod, f, None)
                    if v:
                        texts.append(str(v))

            # 6) ProductQA for those products
            if product_ids:
                product_qas = await self.db.productqa.find_many(
                    where={"product_id": {"in": product_ids}},
                    include={"Product": True}
                )
                for qa in product_qas:
                    prod_name = getattr(getattr(qa, "Product", None), "name", None)
                    question = getattr(qa, "question", None)
                    answer = getattr(qa, "answer", None)
                    prefix = f"Product: {prod_name}\n" if prod_name else ""
                    if question and answer:
                        texts.append(f"{prefix}Q: {question}\nA: {answer}")
                    elif question:
                        texts.append(f"{prefix}Q: {question}")
                    elif answer:
                        texts.append(f"{prefix}A: {answer}")

        # 7) BulkSnippet
        snippets = await self.db.bulksnippet.find_many(
            where={"tenant_id": tenant_id}
        )
        for s in snippets:
            if s and getattr(s, "text", None):
                texts.append(str(s.text))

        # 8) Final sanitize: coerce to str, strip, drop empties
        final_texts: list[str] = []
        for t in texts:
            if t is None:
                continue
            s = t if isinstance(t, str) else str(t)
            s = s.strip()
            if s:
                final_texts.append(s)

        return final_texts


    def aspect_scores(self, texts: list[str]) -> dict:
        aspect_texts = {a: [] for a in ASPECTS}
        for text in texts:
            text_lower = text.lower()
            matched = False
            for aspect, patterns in ASPECT_KEYWORDS.items():
                if any(re.search(pattern, text_lower) for pattern in patterns):
                    aspect_texts[aspect].append(text)
                    matched = True
            if not matched:
                aspect_texts["ABOUT"].append(text)

        scored = {}
        for aspect, aspect_text_list in aspect_texts.items():
            if not aspect_text_list:
                scored[aspect] = {"present": False, "detail": 0, "signals": {"wordcount": 0}}
                continue
            joined = "\n".join(aspect_text_list)
            words = len(re.findall(r"\w+", joined))
            headings = len(re.findall(r"(^|\n)#{1,6}\s|\n[A-Z][A-Za-z ]{3,}\n[-=]{3,}", joined))
            qas = len(re.findall(r"\b(Q:|Question:).+?\b(A:|Answer:)", joined, flags=re.I | re.S))
            numerics = len(re.findall(r"\b\d[\d.,%]*\b", joined))
            currency = len(re.findall(r"(₹|\$|€|USD|INR)", joined))
            links = len(re.findall(r"https?://", joined))

            size_score = min(5, int(max(0, math.log10(max(10, words)) - 0.5)))
            structure_score = min(5, (headings > 0) + (qas > 0) + (links > 0) + (numerics > 3) + (currency > 0))
            specificity_score = min(5, (numerics > 5) + (currency > 0) + (links > 1) + (words > 400) + (words > 800))
            detail = int(max(0, min(5, round((size_score + structure_score + specificity_score) / 3))))

            scored[aspect] = {
                "present": True,
                "detail": detail,
                "signals": {
                    "wordcount": words,
                    "headings": headings,
                    "qas": qas,
                    "numerics": numerics,
                    "currency_hits": currency,
                    "links": links,
                },
            }
        return scored

    async def hygiene_signals(self, tenant_id: str) -> dict:
        now = dt.datetime.utcnow().replace(tzinfo=None)
        ages_days: list[int] = []

        # KnowledgeDocument recency
        docs = await self.db.knowledgedocument.find_many(
            where={"tenant_id": tenant_id, "status": "READY"},
            order={"created_at": "desc"}
        )
        if docs:
            ages_days.append((now - docs[0].created_at.replace(tzinfo=None)).days)

        # WebsiteContent recency
        websites = await self.db.websitecontent.find_many(
            where={"tenant_id": tenant_id, "status": "READY"},
            order={"finished_at": "desc"}
        )
        if websites and websites[0].finished_at:
            ages_days.append((now - websites[0].finished_at.replace(tzinfo=None)).days)

        # Active RAG chunks + uniqueness
        rag_counts = await self.db.query_raw(
            'SELECT COUNT(*)::int AS chunks, COUNT(DISTINCT split_part("sourceId", \':\', 1) || \':\' || split_part("sourceId", \':\', 2))::int AS roots FROM "TenantRAG" WHERE tenant_id = $1 AND is_active = true',
            tenant_id
        )
        chunks = int(rag_counts[0]["chunks"]) if rag_counts else 0
        roots = int(rag_counts[0]["roots"]) if rag_counts else 0
        unique_ratio = (roots / chunks) if chunks else 0.0

        freshness = 0 if not ages_days else max(0, min(100, int(100 * (1 - (sorted(ages_days)[len(ages_days)//2] / 180)))))
        volume = int(min(100, (math.log10(max(1, chunks)) / math.log10(100)) * 100)) if chunks else 0
        dedupe = int(max(0, min(100, unique_ratio * 100))) if chunks else 0

        return {"freshness": freshness, "volume": volume, "dedupe": dedupe, "chunks": chunks, "roots": roots}

    def combine(self, aspect: dict, hygiene: dict) -> tuple[int, dict]:
        coverage = sum(1 for v in aspect.values() if v["present"]) / len(ASPECTS)
        avg_detail = (sum(v["detail"] for v in aspect.values()) / (5 * len(ASPECTS))) if ASPECTS else 0.0

        # Conservative weights; easy to change later
        score = int(round(
            0.35 * (coverage * 100) +
            0.25 * (avg_detail * 100) +
            0.20 * hygiene["freshness"] +
            0.10 * hygiene["volume"] +
            0.10 * hygiene["dedupe"]
        ))
        components = {
            "aspects": aspect,
            "signals": hygiene,
            "weights_info": "coverage35, detail25, freshness20, volume10, dedupe10"
        }
        return score, components

    async def compute_and_store(self, tenant_id: str) -> dict:
        texts = await self.collect_texts(tenant_id)
        print(f"Collected {len(texts)} texts for tenant {tenant_id} readiness computation.")
        aspects = self.aspect_scores(texts)
        print(f"Aspect scores for tenant {tenant_id}: {aspects}")
        hygiene = await self.hygiene_signals(tenant_id)
        print(f"Hygiene signals for tenant {tenant_id}: {hygiene}")
        score, components = self.combine(aspects, hygiene)
        print(f"Computed readiness score {score} for tenant {tenant_id}.")

        await self.db.ragreadiness.upsert(
            where={"tenant_id": tenant_id},
            data={
                "create": {
                    "score": score,
                    "components": Json(components),  # <- wrap JSON
                    "Tenant": {"connect": {"id": tenant_id}},  # <- satisfy required relation
                },
                "update": {
                    "score": score,
                    "components": Json(components),  # <- wrap JSON
                },
            },
        )
        return {"score": score}
