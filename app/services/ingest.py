# app/services/ingest.py
import os
import re
import math
import json
import boto3
import hashlib
import logging
import asyncio
import aiohttp
import tempfile
from typing import List, Dict
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from app.config import AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_DOCS

from app.services.database import db
from app.config import OPENAI_EMBEDDING_MODEL

logger = logging.getLogger(__name__)

CANONICAL_SOURCES = {
    "bulk_snippet": "bulk_snippet",
    "bulk_snippets": "bulk_snippet",
    "company_profile": "company_profile",
    "company_qa": "company_qa",
    "knowledge_document": "knowledge_document",
    "knowledge_documents": "knowledge_document",
    "product": "product",
    "products": "product",
    "product_qa": "product_qa",
    "website_content": "website_content",
}

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def simhash64(text: str) -> int:
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0
    from collections import Counter
    weights = Counter(tokens)
    bits = [0] * 64
    for token, weight in weights.items():
        # stable hash per token
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        for i in range(64):
            bits[i] += weight if ((h >> i) & 1) else -weight
    out = 0
    for i, v in enumerate(bits):
        if v >= 0:
            out |= 1 << i
    return out

def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()

class Ingest:
    def __init__(self):
        self.db = db
        self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200, length_function=len
        )
        self.simhash_threshold_bits = 3  # tiny edits are skipped if within this distance

        # S3 client for retrieval (credentials via env/IAM)
        self.s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION or "ap-south-1",
            aws_access_key_id=AWS_ACCESS_KEY_ID or os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY or os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        self.docs_bucket = S3_BUCKET_DOCS or "sale-funnel-knowledge-documents"

    # --------------------
    # PUBLIC: BULK INGEST
    # --------------------
    async def run_ingestion(self, sources: List[str] | None, tenant_id: str) -> int:
        total_inserted = 0
        sources_to_process = [CANONICAL_SOURCES.get(s, s) for s in (sources or [
            "bulk_snippet", "company_profile", "company_qa",
            "knowledge_document", "product", "product_qa", "website_content"
        ])]

        for source in sources_to_process:
            try:
                if source == "bulk_snippet":
                    total_inserted += await self.ingest_bulk_snippets(tenant_id)
                elif source == "company_profile":
                    total_inserted += await self.ingest_company_profile(tenant_id)
                elif source == "company_qa":
                    total_inserted += await self.ingest_company_qa(tenant_id)
                elif source == "knowledge_document":
                    total_inserted += await self.ingest_knowledge_documents(tenant_id)
                elif source == "product":
                    total_inserted += await self.ingest_products(tenant_id)
                elif source == "product_qa":
                    total_inserted += await self.ingest_product_qa(tenant_id)
                elif source == "website_content":
                    total_inserted += await self.ingest_website_content(tenant_id)
                else:
                    logger.warning(f"Unknown source: {source}")
            except Exception as exc:
                logger.error(f"Error processing {source}: {exc}", exc_info=True)

        logger.info(f"Ingestion completed. Total newly embedded chunks: {total_inserted}")
        return total_inserted

    # -------------------------
    # PUBLIC: PER-ENTITY INGEST
    # -------------------------
    async def ingest_company_profile_by_id(self, tenant_id: str, profile_id: str) -> dict:
        profile = await self.db.companyprofile.find_unique(where={"tenant_id": tenant_id, "id": profile_id})
        if not profile:
            return {"inserted": 0, "reused": 0, "deactivated": 0, "skipped_similar": 0}
        text = self._combine_company_profile_text(profile)
        chunks = [d.page_content for d in self.text_splitter.create_documents([text])] if text else []
        return await self._upsert_chunks(tenant_id, "company_profile", f"company_profile:{profile_id}", chunks)

    async def ingest_company_qa_by_id(self, tenant_id: str, qa_id: str) -> dict:
        qa = await self.db.companyqa.find_unique(where={"id": qa_id}, include={"CompanyProfile": True})
        if not qa or qa.CompanyProfile.tenant_id != tenant_id:
            return {"inserted": 0, "reused": 0, "deactivated": 0, "skipped_similar": 0}
        qa_text = f"Question: {qa.question}\nAnswer: {qa.answer}"
        if qa.category:
            qa_text = f"Category: {qa.category}\n{qa_text}"
        chunks = [d.page_content for d in self.text_splitter.create_documents([qa_text])]
        return await self._upsert_chunks(tenant_id, "company_qa", f"company_qa:{qa_id}", chunks)

    async def ingest_product_by_id(self, tenant_id: str, product_id: str) -> dict:
        product = await self.db.product.find_unique(where={"id": product_id}, include={"CompanyProfile": True})
        if not product or product.CompanyProfile.tenant_id != tenant_id:
            return {"inserted": 0, "reused": 0, "deactivated": 0, "skipped_similar": 0}
        text = self._combine_product_text(product)
        chunks = [d.page_content for d in self.text_splitter.create_documents([text])] if text else []
        return await self._upsert_chunks(tenant_id, "product", f"product:{product_id}", chunks)

    async def ingest_product_qa_by_id(self, tenant_id: str, qa_id: str) -> dict:
        qa = await self.db.productqa.find_unique(where={"id": qa_id}, include={"Product": {"include": {"CompanyProfile": True}}})
        if not qa or qa.Product.CompanyProfile.tenant_id != tenant_id:
            return {"inserted": 0, "reused": 0, "deactivated": 0, "skipped_similar": 0}
        text = f"Product: {qa.Product.name}\nQuestion: {qa.question}\nAnswer: {qa.answer}"
        chunks = [d.page_content for d in self.text_splitter.create_documents([text])]
        return await self._upsert_chunks(tenant_id, "product_qa", f"product_qa:{qa_id}", chunks)

    async def ingest_knowledge_document_by_id(self, tenant_id: str, document_id: str) -> dict:
        document = await self.db.knowledgedocument.find_unique(where={"tenant_id": tenant_id, "id": document_id})
        if not document:
            return {"inserted": 0, "reused": 0, "deactivated": 0, "skipped_similar": 0}
        loaded_docs = await self._load_knowledge_document(document)
        chunks = [d.page_content for d in loaded_docs]
        return await self._upsert_chunks(tenant_id, "knowledge_document", f"kd:{document_id}", chunks)

    async def ingest_website_content_by_id(self, tenant_id: str, website_id: str) -> dict:
        website = await self.db.websitecontent.find_unique(where={"tenant_id": tenant_id, "id": website_id, "status": "READY"})
        if not website or not website.crawl_summary:
            return {"inserted": 0, "reused": 0, "deactivated": 0, "skipped_similar": 0}
        chunks = [d.page_content for d in self.text_splitter.create_documents([website.crawl_summary])]
        return await self._upsert_chunks(tenant_id, "website_content", f"wc:{website_id}", chunks)

    # --------------------
    # BULK HELPERS
    # --------------------
    async def ingest_bulk_snippets(self, tenant_id: str) -> int:
        snippets = await self.db.bulksnippet.find_many(where={"tenant_id": tenant_id})
        total = 0
        for snippet in snippets:
            if not snippet.text:
                continue
            chunks = [d.page_content for d in self.text_splitter.create_documents([snippet.text])]
            result = await self._upsert_chunks(tenant_id, "bulk_snippet", f"bulk_snippet:{snippet.id}", chunks)
            total += result["inserted"]
        return total

    async def ingest_company_profile(self, tenant_id: str) -> int:
        profiles = await self.db.companyprofile.find_many(where={"tenant_id": tenant_id})
        total = 0
        for profile in profiles:
            text = self._combine_company_profile_text(profile)
            if not text:
                continue
            chunks = [d.page_content for d in self.text_splitter.create_documents([text])]
            result = await self._upsert_chunks(tenant_id, "company_profile", f"company_profile:{profile.id}", chunks)
            total += result["inserted"]
        return total

    async def ingest_company_qa(self, tenant_id: str) -> int:
        company_ids = [c.id for c in await self.db.companyprofile.find_many(where={"tenant_id": tenant_id}, select={"id": True})]
        if not company_ids:
            return 0
        qas = await self.db.companyqa.find_many(where={"company_id": {"in": company_ids}})
        total = 0
        for qa in qas:
            text = f"Question: {qa.question}\nAnswer: {qa.answer}"
            if qa.category:
                text = f"Category: {qa.category}\n{text}"
            chunks = [d.page_content for d in self.text_splitter.create_documents([text])]
            result = await self._upsert_chunks(tenant_id, "company_qa", f"company_qa:{qa.id}", chunks)
            total += result["inserted"]
        return total

    async def ingest_knowledge_documents(self, tenant_id: str) -> int:
        # status READY per schema
        documents = await self.db.knowledgedocument.find_many(where={"tenant_id": tenant_id, "status": "READY"})
        total = 0
        for document in documents:
            loaded_docs = await self._load_knowledge_document(document)
            chunks = [d.page_content for d in loaded_docs]
            result = await self._upsert_chunks(tenant_id, "knowledge_document", f"kd:{document.id}", chunks)
            total += result["inserted"]
        return total

    async def ingest_products(self, tenant_id: str) -> int:
        company_ids = [c.id for c in await self.db.companyprofile.find_many(where={"tenant_id": tenant_id}, select={"id": True})]
        products = await self.db.product.find_many(where={"company_id": {"in": company_ids}})
        total = 0
        for product in products:
            text = self._combine_product_text(product)
            if not text:
                continue
            chunks = [d.page_content for d in self.text_splitter.create_documents([text])]
            result = await self._upsert_chunks(tenant_id, "product", f"product:{product.id}", chunks)
            total += result["inserted"]
        return total

    async def ingest_product_qa(self, tenant_id: str) -> int:
        profiles = await self.db.companyprofile.find_many(where={"tenant_id": tenant_id}, include={"Product": True})
        product_ids = [p.id for profile in profiles for p in profile.Product]
        if not product_ids:
            return 0
        qas = await self.db.productqa.find_many(
            where={"product_id": {"in": product_ids}},
            include={"Product": {"include": {"CompanyProfile": True}}}
        )
        total = 0
        for qa in qas:
            text = f"Product: {qa.Product.name}\nQuestion: {qa.question}\nAnswer: {qa.answer}"
            chunks = [d.page_content for d in self.text_splitter.create_documents([text])]
            result = await self._upsert_chunks(qa.Product.CompanyProfile.tenant_id, "product_qa", f"product_qa:{qa.id}", chunks)
            total += result["inserted"]
        return total

    async def ingest_website_content(self, tenant_id: str) -> int:
        websites = await self.db.websitecontent.find_many(where={"tenant_id": tenant_id, "status": "READY"})
        total = 0
        for website in websites:
            if not website.crawl_summary:
                continue
            chunks = [d.page_content for d in self.text_splitter.create_documents([website.crawl_summary])]
            result = await self._upsert_chunks(tenant_id, "website_content", f"wc:{website.id}", chunks)
            total += result["inserted"]
        return total

    # --------------------
    # INTERNAL HELPERS
    # --------------------
    def _combine_company_profile_text(self, profile) -> str:
        parts = ["The description of the company"]
        if profile.description: parts.append(f"Description: {profile.description}")
        if profile.mission: parts.append(f"Mission: {profile.mission}")
        if profile.values: parts.append(f"Values: {profile.values}")
        if profile.usp: parts.append(f"Unique Selling Proposition: {profile.usp}")
        if profile.history: parts.append(f"History: {profile.history}")
        if profile.key_personnel: parts.append(f"Key Personnel: {profile.key_personnel}")
        if getattr(profile, "offering_description", None): parts.append(f"Offering: {profile.offering_description}")
        if getattr(profile, "target_market", None): parts.append(f"Target Market: {profile.target_market}")
        return "\n\n".join(parts)

    def _combine_product_text(self, product) -> str:
        parts = [f"Product: {product.name}"]
        if product.category: parts.append(f"Category: {product.category}")
        if product.description: parts.append(f"Description: {product.description}")
        if product.features: parts.append(f"Features: {product.features}")
        if product.benefits: parts.append(f"Benefits: {product.benefits}")
        if product.pricing: parts.append(f"Pricing: {product.pricing}")
        if product.target_audience: parts.append(f"Target Audience: {product.target_audience}")
        if product.use_cases: parts.append(f"Use Cases: {product.use_cases}")
        return "\n\n".join(parts)

    async def _load_knowledge_document(self, document) -> List[Document]:
        """
        Load from S3 when file_key exists (your Node service writes file_key into DB).
        Fallback to extracted_text if present.
        """
        loaded_docs: List[Document] = []

        # Prefer S3 object
        file_key = getattr(document, "file_key", None)
        mime_type = getattr(document, "mime_type", None)
        if file_key:
            temp_path = await self._download_s3_object(file_key)
            try:
                if mime_type == "application/pdf":
                    loader = PyPDFLoader(file_path=temp_path)
                    loaded_docs = loader.load_and_split(self.text_splitter)
                elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or mime_type == "application/msword":
                    loader = Docx2txtLoader(file_path=temp_path)
                    loaded_docs = loader.load_and_split(self.text_splitter)
                elif mime_type in ("text/plain", "text/csv"):
                    # simple text-based
                    with open(temp_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                    loaded_docs = self.text_splitter.create_documents([content])
                else:
                    # other types (xlsx, images) are ignored for RAG unless you add OCR/parsers
                    logger.info(f"Skipping unsupported mime_type for ingestion: {mime_type}")
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

        # Fallback: extracted_text
        if (not loaded_docs) and getattr(document, "extracted_text", None):
            loaded_docs = self.text_splitter.create_documents([document.extracted_text])

        return loaded_docs

    async def _download_s3_object(self, file_key: str) -> str:
        """
        Download an object from S3 to a temporary file and return the local path.
        """
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                self.s3_client.download_fileobj(self.docs_bucket, file_key, tmp)
                return tmp.name
        except Exception as exc:
            logger.error(f"Failed to download S3 object {file_key} from bucket {self.docs_bucket}: {exc}")
            raise

    async def _upsert_chunks(self, tenant_id: str, source: str, entity_key: str, chunks: List[str]) -> Dict[str, int]:
        source = CANONICAL_SOURCES.get(source, source)
        seen_hashes: set[str] = set()
        inserted = reused = skipped_similar = 0

        # Preload existing active chunks (hash + simhash)
        existing_rows = await self.db.query_raw(
            'SELECT chunk_hash, simhash_bigint FROM "TenantRAG" WHERE tenant_id = $1 AND is_active = true',
            tenant_id
        )
        existing_hashes = {row["chunk_hash"] for row in existing_rows}
        existing_simhashes = [int(row["simhash_bigint"]) for row in existing_rows if row["simhash_bigint"] is not None]

        new_texts: list[str] = []
        new_meta: list[tuple[str, int, str]] = []  # (chunk_hash, simhash, sourceId)

        # for raw_text in chunks:
        #     text = normalize_text(raw_text)
        #     if not text:
        #         continue
        #     chunk_hash = sha256_hex(text)
        #     seen_hashes.add(chunk_hash)

        #     if chunk_hash in existing_hashes:
        #         await self.db.query_raw(
        #             'UPDATE "TenantRAG" SET updated_at = now(), is_active = true WHERE tenant_id = $1 AND chunk_hash = $2',
        #             tenant_id, chunk_hash
        #         )
        #         reused += 1
        #         continue

        #     sim = simhash64(text)
        #     if existing_simhashes and any(hamming_distance(sim, es) <= self.simhash_threshold_bits for es in existing_simhashes):
        #         skipped_similar += 1
        #         continue

        #     new_texts.append(text)
        #     new_meta.append((chunk_hash, sim, entity_key))
        for raw_text in chunks:
            text = normalize_text(raw_text)
            if not text:
                continue
            chunk_hash = sha256_hex(text)
            seen_hashes.add(chunk_hash)

            if chunk_hash in existing_hashes:
                await self.db.query_raw(
                    'UPDATE "TenantRAG" SET updated_at = now(), is_active = true WHERE tenant_id = $1 AND chunk_hash = $2',
                    tenant_id, chunk_hash
                )
                reused += 1
                continue

            # compute 64-bit simhash
            sim = simhash64(text)

            # force into signed 64-bit range for Postgres BIGINT
            if sim >= 2**63:
                sim -= 2**64

            if existing_simhashes and any(
                hamming_distance(sim, es) <= self.simhash_threshold_bits
                for es in existing_simhashes
            ):
                skipped_similar += 1
                continue

            new_texts.append(text)
            new_meta.append((chunk_hash, sim, entity_key))


        # Embed and insert new hashes
        for text, (chunk_hash, sim_value, source_id) in zip(new_texts, new_meta):
            embedding = await asyncio.to_thread(self.embeddings.embed_query, text)
            await self.db.query_raw(
                '''
                INSERT INTO "TenantRAG"
                    (tenant_id, source, "sourceId", embedding, chunk_hash, version, is_active, created_at, updated_at, embedding_model, simhash_bigint)
                VALUES
                    ($1, $2, $3, $4, $5, 1, true, now(), now(), $6, $7)
                ON CONFLICT (tenant_id, chunk_hash)
                DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    is_active = true,
                    source = EXCLUDED.source,
                    "sourceId" = EXCLUDED."sourceId",
                    embedding = EXCLUDED.embedding,
                    embedding_model = EXCLUDED.embedding_model,
                    simhash_bigint = EXCLUDED.simhash_bigint
                ''',
                tenant_id, source, source_id, embedding, chunk_hash, getattr(self.embeddings, "model", None) or "openai", sim_value
            )
            inserted += 1

        # Deactivate stale chunks for this entity (those not seen in this run)
        await self.db.query_raw(
            '''
            UPDATE "TenantRAG"
               SET is_active = false, updated_at = now()
             WHERE tenant_id = $1
               AND "sourceId" LIKE $2
               AND is_active = true
               AND (chunk_hash IS NOT NULL)
               AND (chunk_hash <> ALL($3::text[]))
            ''',
            tenant_id, f"{entity_key}%", list(seen_hashes) if seen_hashes else ['__no_hash__']
        )

        return {"inserted": inserted, "reused": reused, "deactivated": 0, "skipped_similar": skipped_similar}

# import os
# import logging
# import asyncio
# import aiohttp
# import tempfile
# from langchain_openai import OpenAIEmbeddings
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain_core.documents import Document
# from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader

# from app.services.database import db
# from app.config import OPENAI_EMBEDDING_MODEL

# logger = logging.getLogger(__name__)


# class Ingest:
#     def __init__(self):
#         self.db = db
#         self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)
#         self.text_splitter = RecursiveCharacterTextSplitter(
#             chunk_size=1000, chunk_overlap=200, length_function=len
#         )

#     async def run_ingestion(self, sources: list[str] | None, tenant_id: str) -> int:
#         total_processed = 0

#         sources_to_process = sources or [
#             "bulk_snippets",
#             "company_profile",
#             "company_qa",
#             "knowledge_documents",
#             "products",
#             "product_qa",
#             "website_content",
#         ]

#         for source in sources_to_process:
#             try:
#                 if source == "bulk_snippets":
#                     count = await self.process_bulk_snippets(tenant_id)
#                 elif source == "company_profile":
#                     count = await self.process_company_profile(tenant_id)
#                 elif source == "company_qa":
#                     count = await self.process_company_qa(tenant_id)
#                 elif source == "knowledge_documents":
#                     count = await self.process_knowledge_documents(tenant_id)
#                 elif source == "products":
#                     count = await self.process_products(tenant_id)
#                 elif source == "product_qa":
#                     count = await self.process_product_qa(tenant_id)
#                 elif source == "website_content":
#                     count = await self.process_website_content(tenant_id)
#                 else:
#                     logger.warning(f"Unknown source: {source}")
#                     continue

#                 total_processed += count
#                 logger.info(f"Processed {count} records from {source}")

#             except Exception as e:
#                 logger.error(f"Error processing {source}: {str(e)}")
#                 continue

#         print(f"Ingestion completed. Total processed: {total_processed}")
#         return total_processed

#     async def process_bulk_snippets(self, tenant_id: str) -> int:
#         snippets = await self.db.bulksnippet.find_many(where={"tenant_id": tenant_id})

#         processed = 0
#         for snippet in snippets:
#             if not snippet.text or len(snippet.text.strip()) == 0:
#                 continue

#             docs = self.text_splitter.create_documents([snippet.text])

#             for i, doc in enumerate(docs):
#                 embedding = await self._generate_embedding(doc.page_content)

#                 await self._store_embedding(
#                     tenant_id=snippet.tenant_id,
#                     source="bulk_snippet",
#                     source_id=f"{snippet.id}_{i}",
#                     embedding=embedding,
#                 )
#                 processed += 1

#         return processed

#     async def process_company_profile(self, tenant_id: str) -> int:
#         profiles = await self.db.companyprofile.find_many(
#             where={"tenant_id": tenant_id}
#         )

#         processed = 0
#         for profile in profiles:
#             profile_text = self._combine_company_profile_text(profile)

#             if profile_text:
#                 docs = self.text_splitter.create_documents([profile_text])

#                 for i, doc in enumerate(docs):
#                     embedding = await self._generate_embedding(doc.page_content)

#                     await self._store_embedding(
#                         tenant_id=profile.tenant_id,
#                         source="company_profile",
#                         source_id=f"{profile.id}_{i}",
#                         embedding=embedding,
#                     )
#                     processed += 1

#         return processed

#     async def process_company_qa(self, tenant_id: str) -> int:
#         profiles = await self.db.companyprofile.find_many(
#             where={"tenant_id": tenant_id}
#         )

#         if not profiles:
#             return 0

#         company_to_tenant = {p.id: p.tenant_id for p in profiles}
#         company_ids = list(company_to_tenant.keys())

#         qa_records = await self.db.companyqa.find_many(
#             where={"company_id": {"in": company_ids}}
#         )

#         processed = 0
#         for qa in qa_records:
#             qa_tenant_id = company_to_tenant[qa.company_id]

#             qa_text = f"Question: {qa.question}\nAnswer: {qa.answer}"
#             if qa.category:
#                 qa_text = f"Category: {qa.category}\n{qa_text}"

#             docs = self.text_splitter.create_documents([qa_text])

#             for i, doc in enumerate(docs):
#                 embedding = await self._generate_embedding(doc.page_content)

#                 await self._store_embedding(
#                     tenant_id=qa_tenant_id,
#                     source="company_qa",
#                     source_id=f"{qa.id}_{i}",
#                     embedding=embedding,
#                 )
#                 processed += 1

#         return processed

#     async def process_knowledge_documents(self, tenant_id: str) -> int:
#         documents = await self.db.knowledgedocument.find_many(
#             where=(
#                 {"tenant_id": tenant_id, "status": "PROCESSED"}
#                 if tenant_id
#                 else {"status": "PROCESSED"}
#             ),
#         )

#         processed = 0
#         for doc in documents:
#             loaded_docs: list[Document] = []

#             try:
#                 if doc.uploaded_url.startswith("https://"):
#                     temp_path = await self.download_file(doc.uploaded_url)

#                     if doc.mime_type == "application/pdf":
#                         loader = PyPDFLoader(file_path=temp_path)
#                         loaded_docs = loader.load_and_split(self.text_splitter)

#                     elif (
#                         doc.mime_type
#                         == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#                     ):
#                         loader = Docx2txtLoader(file_path=temp_path)
#                         loaded_docs = loader.load_and_split(self.text_splitter)

#                     os.remove(temp_path)

#                 if (
#                     not loaded_docs
#                     and doc.extracted_text
#                     and len(doc.extracted_text.strip()) > 0
#                 ):
#                     loaded_docs = self.text_splitter.create_documents(
#                         [doc.extracted_text]
#                     )

#             except Exception as e:
#                 print(f"Error processing {doc.filename} from {doc.uploaded_url}: {e}")
#                 continue

#             for i, chunk in enumerate(loaded_docs):
#                 embedding = await self._generate_embedding(chunk.page_content)
#                 await self._store_embedding(
#                     tenant_id=doc.tenant_id,
#                     source="knowledge_document",
#                     source_id=f"{doc.id}_{i}",
#                     embedding=embedding,
#                 )
#                 processed += 1

#         return processed

#     async def process_products(self, tenant_id: str) -> int:
#         profiles = await self.db.companyprofile.find_many(
#             where={"tenant_id": tenant_id}
#         )

#         if not profiles:
#             return 0

#         company_to_tenant = {p.id: p.tenant_id for p in profiles}
#         company_ids = list(company_to_tenant.keys())

#         products = await self.db.product.find_many(
#             where={"company_id": {"in": company_ids}},
#         )

#         processed = 0
#         for product in products:
#             product_tenant_id = company_to_tenant[product.company_id]
#             product_text = self._combine_product_text(product)

#             if product_text:
#                 docs = self.text_splitter.create_documents([product_text])

#                 for i, doc in enumerate(docs):
#                     embedding = await self._generate_embedding(doc.page_content)

#                     await self._store_embedding(
#                         tenant_id=product_tenant_id,
#                         source="product",
#                         source_id=f"{product.id}_{i}",
#                         embedding=embedding,
#                     )
#                     processed += 1

#         return processed

#     async def process_product_qa(self, tenant_id: str) -> int:
#         profiles = await self.db.companyprofile.find_many(
#             where={"tenant_id": tenant_id},
#             include={"Product": True},
#         )

#         if not profiles:
#             return 0

#         product_ids = []
#         tenant_product_map = {}
#         for profile in profiles:
#             for product in profile.Product:
#                 product_ids.append(product.id)
#                 tenant_product_map[product.id] = profile.tenant_id

#         if not product_ids:
#             return 0

#         qa_records = await self.db.productqa.find_many(
#             where={"product_id": {"in": product_ids}},
#             include={"Product": {"include": {"CompanyProfile": True}}},
#         )

#         processed = 0
#         for qa in qa_records:
#             qa_text = f"Product: {qa.Product.name}\nQuestion: {qa.question}\nAnswer: {qa.answer}"

#             docs = self.text_splitter.create_documents([qa_text])

#             for i, doc in enumerate(docs):
#                 embedding = await self._generate_embedding(doc.page_content)

#                 await self._store_embedding(
#                     tenant_id=qa.Product.CompanyProfile.tenant_id,
#                     source="product_qa",
#                     source_id=f"{qa.id}_{i}",
#                     embedding=embedding,
#                 )
#                 processed += 1

#         return processed

#     async def process_website_content(self, tenant_id: str = None) -> int:
#         websites = await self.db.websitecontent.find_many(
#             where={"tenant_id": tenant_id, "status": "COMPLETED"}
#             if tenant_id
#             else {"status": "COMPLETED"},
#         )

#         processed = 0
#         for website in websites:
#             if not website.crawl_summary or len(website.crawl_summary.strip()) == 0:
#                 continue

#             docs = self.text_splitter.create_documents([website.crawl_summary])

#             for i, doc in enumerate(docs):
#                 embedding = await self._generate_embedding(doc.page_content)

#                 await self._store_embedding(
#                     tenant_id=website.tenant_id,
#                     source="website_content",
#                     source_id=f"{website.id}_{i}",
#                     embedding=embedding,
#                 )
#                 processed += 1

#         return processed

#     async def download_file(self, url: str) -> str:
#         async with aiohttp.ClientSession() as session:
#             async with session.get(url) as resp:
#                 if resp.status != 200:
#                     raise Exception(
#                         f"Failed to download file from {url} (status: {resp.status})"
#                     )

#                 with tempfile.NamedTemporaryFile(delete=False) as tmp:
#                     tmp.write(await resp.read())
#                     return tmp.name

#     def _combine_company_profile_text(self, profile) -> str:
#         parts = ["The description of the company"]
#         if profile.description:
#             parts.append(f"Description: {profile.description}")
#         if profile.mission:
#             parts.append(f"Mission: {profile.mission}")
#         if profile.values:
#             parts.append(f"Values: {profile.values}")
#         if profile.usp:
#             parts.append(f"Unique Selling Proposition: {profile.usp}")
#         if profile.history:
#             parts.append(f"History: {profile.history}")
#         if profile.key_personnel:
#             parts.append(f"Key Personnel: {profile.key_personnel}")

#         return "\n\n".join(parts)

#     def _combine_product_text(self, product) -> str:
#         parts = [f"Product: {product.name}"]

#         if product.category:
#             parts.append(f"Category: {product.category}")
#         if product.description:
#             parts.append(f"Description: {product.description}")
#         if product.features:
#             parts.append(f"Features: {product.features}")
#         if product.benefits:
#             parts.append(f"Benefits: {product.benefits}")
#         if product.pricing:
#             parts.append(f"Pricing: {product.pricing}")
#         if product.target_audience:
#             parts.append(f"Target Audience: {product.target_audience}")
#         if product.use_cases:
#             parts.append(f"Use Cases: {product.use_cases}")

#         return "\n\n".join(parts)

#     async def _generate_embedding(self, text: str) -> list[float]:
#         try:
#             embedding = await asyncio.to_thread(self.embeddings.embed_query, text)
#             return embedding
#         except Exception as e:
#             logger.error(f"Error generating embedding: {str(e)}")
#             raise

#     async def _store_embedding(
#         self, tenant_id: str, source: str, source_id: str, embedding: list[float]
#     ):
#         try:
#             await db.query_raw(
#                 """
#                     INSERT INTO "TenantRAG" (tenant_id, source, "sourceId", embedding, created_at)
#                     VALUES ($1, $2, $3, $4, NOW())
#                     ON CONFLICT (tenant_id, source, "sourceId")
#                     DO UPDATE SET embedding = $4, created_at = NOW()
#                 """,
#                 tenant_id,
#                 source,
#                 source_id,
#                 embedding,
#             )
#         except Exception as e:
#             logger.error(f"Error storing embedding: {str(e)}")
#             raise
