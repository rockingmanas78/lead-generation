from datetime import datetime
import logging
from prisma import Prisma
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.services.database import db
from app.services.shared_processing import process_urls_batch

logger = logging.getLogger(__name__)


async def process():
    await db.connect()

    try:
        processing_jobs = await db.leadgenerationjob.find_many(
            where={"status": "PROCESSING"}
        )

        for job in processing_jobs:
            job_id = job.id
            tenant_id = job.tenantId
            generated_count = job.generatedCount
            remaining_leads = job.totalRequested - generated_count
            urls = job.urls[-remaining_leads:]

            results = await process_urls_batch(urls, tenant_id, job_id, generated_count)

            await db.leadgenerationjob.update(
                where={"id": job_id},
                data={"status": "COMPLETED", "completedAt": datetime.utcnow()},
            )
    except Exception as e:
        logger.error(f"lifespan function failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await process()
    yield
    await db.disconnect()
