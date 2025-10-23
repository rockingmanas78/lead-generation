import os
import logging
import asyncio
import aiohttp
import tempfile
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.services.database import db
from app.schemas import IngestionSourcesEnum
from app.config import OPENAI_EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class MultiTenantRAG:
    def __init__(self):
        self.db = db
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY, model=OPENAI_MODEL, temperature=0.7
        )
        self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200, length_function=len
        )

    async def get_context(
        self, question: str, tenant_id: str, sources: list[IngestionSourcesEnum] | None
    ) -> str:
        final_context = ""
        contexts: list[str] = []
        try:
            similar_chunks = await self._get_similar_chunks(
                question, tenant_id, sources
            )

            for chunk in similar_chunks:
                source_id, index = chunk["sourceId"].split("_")
                index = int(index)
                context = ""
                if chunk["source"] == "bulk_snippets":
                    context = await self.retrieve_bulk_snippets(
                        tenant_id, source_id, index
                    )
                elif chunk["source"] == "company_profile":
                    context = await self.retrieve_company_profile(
                        tenant_id, source_id, index
                    )
                elif chunk["source"] == "company_qa":
                    context = await self.retrieve_company_qa(source_id, index)
                elif chunk["source"] == "knowledge_documents":
                    context = await self.retrieve_knowledge_documents(
                        tenant_id, source_id, index
                    )
                elif chunk["source"] == "product":
                    context = await self.retrieve_products(source_id, index)
                elif chunk["source"] == "product_qa":
                    context = await self.retrieve_product_qa(source_id, index)
                elif chunk["source"] == "website_content":
                    context = await self.retrieve_website_content(
                        tenant_id, source_id, index
                    )

                contexts.append(context)

            final_context = "\n\n".join(contexts)
            print(f"The final context retrieved is\n{final_context}")
            return final_context
        except Exception as e:
            logger.error(f"cannot get similar chunks: {e}")
            raise

    async def query_llm(
        self, question: str, tenant_id: str, sources: list[IngestionSourcesEnum] | None
    ) -> str:
        context = await self.get_context(question, tenant_id, sources)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful assistant that answers questions based on the provided context. Be concise and accurate.",
                ),
                ("human", "Context: {context}\n\nQuestion: {question}"),
            ]
        )

        chain = prompt | self.llm

        try:
            response = await chain.ainvoke({"context": context, "question": question})
        except Exception as e:
            logger.error(f"Cannot get response from llm: {e}")
            raise

        return response.content

    async def retrieve_bulk_snippets(
        self, tenant_id: str, source_id: str, index: int
    ) -> str:
        snippet = await self.db.bulksnippet.find_unique(
            where={"tenant_id": tenant_id, "id": source_id}
        )

        if snippet:
            docs = self.text_splitter.create_documents([snippet.text])
            if index < len(docs):
                return docs[index].page_content
            else:
                raise IndexError(
                    f"Index {index} out of range for {len(docs)} documents"
                )

        return ""

    async def retrieve_company_profile(
        self, tenant_id: str, source_id: str, index: int
    ) -> str:
        profile = await self.db.companyprofile.find_unique(
            where={"tenant_id": tenant_id, "id": source_id}
        )

        if profile:
            profile_text = self._combine_company_profile_text(profile)

            if profile_text:
                docs = self.text_splitter.create_documents([profile_text])
                if index < len(docs):
                    return docs[index].page_content
                else:
                    raise IndexError(
                        f"Index {index} out of range for {len(docs)} documents"
                    )

        return ""

    async def retrieve_company_qa(self, source_id: str, index: int) -> str:
        qa = await self.db.companyqa.find_unique(where={"id": source_id})

        if not qa:
            return ""

        qa_text = f"Question: {qa.question}\nAnswer: {qa.answer}"
        if qa.category:
            qa_text = f"Category: {qa.category}\n{qa_text}"

        docs = self.text_splitter.create_documents([qa_text])
        if index < len(docs):
            return docs[index].page_content
        else:
            raise IndexError(f"Index {index} out of range for {len(docs)} documents")

    async def retrieve_knowledge_documents(
        self, tenant_id: str, source_id: str, index: int
    ) -> str:
        doc = await self.db.knowledgedocument.find_unique(
            where={"tenant_id": tenant_id, "id": source_id}
        )

        if not doc:
            return ""

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
                loaded_docs = self.text_splitter.create_documents([doc.extracted_text])

            if index < len(loaded_docs):
                return loaded_docs[index].page_content
            else:
                raise IndexError(
                    f"Index {index} out of range for {len(loaded_docs)} documents"
                )

        except Exception as e:
            print(f"Error processing {doc.filename} from {doc.uploaded_url}: {e}")
            raise

    async def retrieve_products(self, source_id: str, index: int) -> str:
        product = await self.db.product.find_unique(where={"id": source_id})

        if not product:
            return ""

        product_text = self._combine_product_text(product)
        if product_text:
            docs = self.text_splitter.create_documents([product_text])
            if index < len(docs):
                return docs[index].page_content
            else:
                raise IndexError(
                    f"Index {index} out of range for {len(docs)} documents"
                )

    async def retrieve_product_qa(self, source_id: str, index: int) -> str:
        qa = await self.db.productqa.find_unique(
            where={"id": source_id}, include={"Product": True}
        )

        if not qa:
            return ""

        qa_text = (
            f"Product: {qa.Product.name}\nQuestion: {qa.question}\nAnswer: {qa.answer}"
        )
        docs = self.text_splitter.create_documents([qa_text])
        if index < len(docs):
            return docs[index].page_content
        else:
            raise IndexError(f"Index {index} out of range for {len(docs)} documents")

    async def retrieve_website_content(
        self, tenant_id: str, source_id: str, index: int
    ) -> str:
        website = await self.db.websitecontent.find_unique(
            where={"tenant_id": tenant_id, "status": "COMPLETED", "id": source_id}
            if tenant_id
            else {"status": "COMPLETED"},
        )

        if (
            not website
            or not website.crawl_summary
            or len(website.crawl_summary.strip()) == 0
        ):
            return ""

        docs = self.text_splitter.create_documents([website.crawl_summary])
        if index < len(docs):
            return docs[index].page_content
        else:
            raise IndexError(f"Index {index} out of range for {len(docs)} documents")

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

    async def _get_similar_chunks(
        self,
        question: str,
        tenant_id: str,
        sources: list[IngestionSourcesEnum] | None = None,
    ) -> list[dict[str, str]]:
        try:
            question_embedding = await self._generate_embedding(question)
            base_query = """
            SELECT source, "sourceId"
            FROM "TenantRAG"
            WHERE tenant_id = $1
            """
            params = [tenant_id]

            if sources:
                source_placeholders = ", ".join(
                    f"${i + 2}" for i in range(len(sources))
                )
                base_query += f" AND source IN ({source_placeholders})"
                params.extend([source.value for source in sources])
            else:
                available_sources_query = """
                SELECT DISTINCT source
                FROM "TenantRAG"
                WHERE tenant_id = $1
                """
                available_result = await db.query_raw(
                    available_sources_query, tenant_id
                )
                available_sources = [row["source"] for row in available_result]

                if available_sources:
                    source_placeholders = ", ".join(
                        f"${i + 2}" for i in range(len(available_sources))
                    )
                    base_query += f" AND source IN ({source_placeholders})"
                    params.extend(available_sources)
                else:
                    return []

            embedding_param_index = len(params) + 1
            base_query += f"""
            ORDER BY embedding <=> ${embedding_param_index}::vector
            LIMIT 5;
            """
            params.append(question_embedding)

            result = await db.query_raw(base_query, *params)
            return result

        except Exception as e:
            logger.error(f"Error retrieving similar chunks: {str(e)}")
            raise

    async def _generate_embedding(self, text: str) -> list[float]:
        try:
            embedding = await asyncio.to_thread(self.embeddings.embed_query, text)
            return embedding
        except Exception as e:
            logger.error(f"Error generating embedding: {str(e)}")
            raise

    async def compute_confidence(
        self, lead_text: str, tenant_id: str, sources: list[IngestionSourcesEnum] | None
    ) -> str:
        context = await self.get_context(lead_text, tenant_id, sources)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful assistant that computes confidence, that is, how much a lead is probable to match the service provider based on the lead description provided as lead text. You have context as the data of service provider. Give the value as an decimal ranging from 0 to 1, 0 depicting no chances of lead closing and 1 depicting high chances of lead closing.",
                ),
                ("human", "Context: {context}\n\nQuestion: {lead_text}"),
            ]
        )

        chain = prompt | self.llm

        try:
            response = await chain.ainvoke({"context": context, "lead_text": lead_text})
            print(f"Confidence computation response: {response.content}")
        except Exception as e:
            logger.error(f"Cannot get response from llm: {e}")
            raise

        return response.content

