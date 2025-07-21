import os
import logging
import asyncio
import aiohttp
import tempfile
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader

from app.services.database import db
from app.config import OPENAI_EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class Ingest:
    def __init__(self):
        self.db = db
        self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200, length_function=len
        )

    async def run_ingestion(self, sources: list[str] | None, tenant_id: str) -> int:
        total_processed = 0

        sources_to_process = sources or [
            "bulk_snippets",
            "company_profile",
            "company_qa",
            "knowledge_documents",
            "products",
            "product_qa",
            "website_content",
        ]

        for source in sources_to_process:
            try:
                if source == "bulk_snippets":
                    count = await self.process_bulk_snippets(tenant_id)
                elif source == "company_profile":
                    count = await self.process_company_profile(tenant_id)
                elif source == "company_qa":
                    count = await self.process_company_qa(tenant_id)
                elif source == "knowledge_documents":
                    count = await self.process_knowledge_documents(tenant_id)
                elif source == "products":
                    count = await self.process_products(tenant_id)
                elif source == "product_qa":
                    count = await self.process_product_qa(tenant_id)
                elif source == "website_content":
                    count = await self.process_website_content(tenant_id)
                else:
                    logger.warning(f"Unknown source: {source}")
                    continue

                total_processed += count
                logger.info(f"Processed {count} records from {source}")

            except Exception as e:
                logger.error(f"Error processing {source}: {str(e)}")
                continue

        print(f"Ingestion completed. Total processed: {total_processed}")
        return total_processed

    async def process_bulk_snippets(self, tenant_id: str) -> int:
        snippets = await self.db.bulksnippet.find_many(where={"tenant_id": tenant_id})

        processed = 0
        for snippet in snippets:
            if not snippet.text or len(snippet.text.strip()) == 0:
                continue

            docs = self.text_splitter.create_documents([snippet.text])

            for i, doc in enumerate(docs):
                embedding = await self._generate_embedding(doc.page_content)

                await self._store_embedding(
                    tenant_id=snippet.tenant_id,
                    source="bulk_snippet",
                    source_id=f"{snippet.id}_{i}",
                    embedding=embedding,
                )
                processed += 1

        return processed

    async def process_company_profile(self, tenant_id: str) -> int:
        profiles = await self.db.companyprofile.find_many(
            where={"tenant_id": tenant_id}
        )

        processed = 0
        for profile in profiles:
            profile_text = self._combine_company_profile_text(profile)

            if profile_text:
                docs = self.text_splitter.create_documents([profile_text])

                for i, doc in enumerate(docs):
                    embedding = await self._generate_embedding(doc.page_content)

                    await self._store_embedding(
                        tenant_id=profile.tenant_id,
                        source="company_profile",
                        source_id=f"{profile.id}_{i}",
                        embedding=embedding,
                    )
                    processed += 1

        return processed

    async def process_company_qa(self, tenant_id: str) -> int:
        profiles = await self.db.companyprofile.find_many(
            where={"tenant_id": tenant_id}
        )

        if not profiles:
            return 0

        company_to_tenant = {p.id: p.tenant_id for p in profiles}
        company_ids = list(company_to_tenant.keys())

        qa_records = await self.db.companyqa.find_many(
            where={"company_id": {"in": company_ids}}
        )

        processed = 0
        for qa in qa_records:
            qa_tenant_id = company_to_tenant[qa.company_id]

            qa_text = f"Question: {qa.question}\nAnswer: {qa.answer}"
            if qa.category:
                qa_text = f"Category: {qa.category}\n{qa_text}"

            docs = self.text_splitter.create_documents([qa_text])

            for i, doc in enumerate(docs):
                embedding = await self._generate_embedding(doc.page_content)

                await self._store_embedding(
                    tenant_id=qa_tenant_id,
                    source="company_qa",
                    source_id=f"{qa.id}_{i}",
                    embedding=embedding,
                )
                processed += 1

        return processed

    async def process_knowledge_documents(self, tenant_id: str) -> int:
        documents = await self.db.knowledgedocument.find_many(
            where=(
                {"tenant_id": tenant_id, "status": "PROCESSED"}
                if tenant_id
                else {"status": "PROCESSED"}
            ),
        )

        processed = 0
        for doc in documents:
            loaded_docs: list[Document] = []

            try:
                if doc.uploaded_url.startswith("https://"):
                    temp_path = await self.download_file(doc.uploaded_url)

                    if doc.mime_type == "application/pdf":
                        loader = PyPDFLoader(file_path=temp_path)
                        loaded_docs = loader.load_and_split(self.text_splitter)

                    elif (
                        doc.mime_type
                        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ):
                        loader = Docx2txtLoader(file_path=temp_path)
                        loaded_docs = loader.load_and_split(self.text_splitter)

                    os.remove(temp_path)

                if (
                    not loaded_docs
                    and doc.extracted_text
                    and len(doc.extracted_text.strip()) > 0
                ):
                    loaded_docs = self.text_splitter.create_documents(
                        [doc.extracted_text]
                    )

            except Exception as e:
                print(f"Error processing {doc.filename} from {doc.uploaded_url}: {e}")
                continue

            for i, chunk in enumerate(loaded_docs):
                embedding = await self._generate_embedding(chunk.page_content)
                await self._store_embedding(
                    tenant_id=doc.tenant_id,
                    source="knowledge_document",
                    source_id=f"{doc.id}_{i}",
                    embedding=embedding,
                )
                processed += 1

        return processed

    async def process_products(self, tenant_id: str) -> int:
        profiles = await self.db.companyprofile.find_many(
            where={"tenant_id": tenant_id}
        )

        if not profiles:
            return 0

        company_to_tenant = {p.id: p.tenant_id for p in profiles}
        company_ids = list(company_to_tenant.keys())

        products = await self.db.product.find_many(
            where={"company_id": {"in": company_ids}},
        )

        processed = 0
        for product in products:
            product_tenant_id = company_to_tenant[product.company_id]
            product_text = self._combine_product_text(product)

            if product_text:
                docs = self.text_splitter.create_documents([product_text])

                for i, doc in enumerate(docs):
                    embedding = await self._generate_embedding(doc.page_content)

                    await self._store_embedding(
                        tenant_id=product_tenant_id,
                        source="product",
                        source_id=f"{product.id}_{i}",
                        embedding=embedding,
                    )
                    processed += 1

        return processed

    async def process_product_qa(self, tenant_id: str) -> int:
        profiles = await self.db.companyprofile.find_many(
            where={"tenant_id": tenant_id},
            include={"Product": {"select": {"id": True}}},
        )

        if not profiles:
            return 0

        product_ids = []
        tenant_product_map = {}
        for profile in profiles:
            for product in profile.Product:
                product_ids.append(product.id)
                tenant_product_map[product.id] = profile.tenant_id

        if not product_ids:
            return 0

        qa_records = await self.db.productqa.find_many(
            where={"product_id": {"in": product_ids}},
            include={"Product": {"include": {"CompanyProfile": True}}},
        )

        processed = 0
        for qa in qa_records:
            qa_text = f"Product: {qa.Product.name}\nQuestion: {qa.question}\nAnswer: {qa.answer}"

            docs = self.text_splitter.create_documents([qa_text])

            for i, doc in enumerate(docs):
                embedding = await self._generate_embedding(doc.page_content)

                await self._store_embedding(
                    tenant_id=qa.Product.CompanyProfile.tenant_id,
                    source="product_qa",
                    source_id=f"{qa.id}_{i}",
                    embedding=embedding,
                )
                processed += 1

        return processed

    async def process_website_content(self, tenant_id: str = None) -> int:
        websites = await self.db.websitecontent.find_many(
            where={"tenant_id": tenant_id, "status": "COMPLETED"}
            if tenant_id
            else {"status": "COMPLETED"},
        )

        processed = 0
        for website in websites:
            if not website.crawl_summary or len(website.crawl_summary.strip()) == 0:
                continue

            docs = self.text_splitter.create_documents([website.crawl_summary])

            for i, doc in enumerate(docs):
                embedding = await self._generate_embedding(doc.page_content)

                await self._store_embedding(
                    tenant_id=website.tenant_id,
                    source="website_content",
                    source_id=f"{website.id}_{i}",
                    embedding=embedding,
                )
                processed += 1

        return processed

    async def download_file(self, url: str) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise Exception(
                        f"Failed to download file from {url} (status: {resp.status})"
                    )

                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(await resp.read())
                    return tmp.name

    def _combine_company_profile_text(self, profile) -> str:
        parts = ["The description of the company"]
        if profile.description:
            parts.append(f"Description: {profile.description}")
        if profile.mission:
            parts.append(f"Mission: {profile.mission}")
        if profile.values:
            parts.append(f"Values: {profile.values}")
        if profile.usp:
            parts.append(f"Unique Selling Proposition: {profile.usp}")
        if profile.history:
            parts.append(f"History: {profile.history}")
        if profile.key_personnel:
            parts.append(f"Key Personnel: {profile.key_personnel}")

        return "\n\n".join(parts)

    def _combine_product_text(self, product) -> str:
        parts = [f"Product: {product.name}"]

        if product.category:
            parts.append(f"Category: {product.category}")
        if product.description:
            parts.append(f"Description: {product.description}")
        if product.features:
            parts.append(f"Features: {product.features}")
        if product.benefits:
            parts.append(f"Benefits: {product.benefits}")
        if product.pricing:
            parts.append(f"Pricing: {product.pricing}")
        if product.target_audience:
            parts.append(f"Target Audience: {product.target_audience}")
        if product.use_cases:
            parts.append(f"Use Cases: {product.use_cases}")

        return "\n\n".join(parts)

    async def _generate_embedding(self, text: str) -> list[float]:
        try:
            embedding = await asyncio.to_thread(self.embeddings.embed_query, text)
            return embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {str(e)}")
            raise

    async def _store_embedding(
        self, tenant_id: str, source: str, source_id: str, embedding: list[float]
    ):
        try:
            await db.query_raw(
                """
                    INSERT INTO "TenantRAG" (tenant_id, source, "sourceId", embedding, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (tenant_id, source, "sourceId")
                    DO UPDATE SET embedding = $4, created_at = NOW()
                """,
                tenant_id,
                source,
                source_id,
                embedding,
            )
        except Exception as e:
            logger.error(f"Error storing embedding: {str(e)}")
            raise
