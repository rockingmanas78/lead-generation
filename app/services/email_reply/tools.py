from datetime import datetime
import dateparser
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from app.services.rag import MultiTenantRAG

rag = MultiTenantRAG()


@tool(parse_docstring=True)
async def get_relevant_information(query: str, config: RunnableConfig) -> str:
    """Get the relevant information of our company from the vector database.

    Args:
        query: query to ask the vector database.
        config: Contains the tenantID to retrieve from the database.
    """

    tenant_id = config["configurable"].get("tenant_id")
    context = await rag.get_context(query, tenant_id, None)
    return f"-------------------[REFERENCE KNOWLEDGE BASE CONTEXT FROM THE VECTOR DATABASE]--------------------\n{context}\n-----------------"


@tool(parse_docstring=True)
def calculate_future_datetime(reference: str) -> str:
    """Calculate the future date and time from a natural language reference.

    Args:
        reference: A natural language time expression (e.g., "next Tuesday at 10am", "in 3 hours", "tomorrow afternoon").

    Returns:
        An ISO 8601 datetime string (YYYY-MM-DDTHH:MM:SS) or an error message if parsing fails.
    """

    dt = dateparser.parse(reference, settings={"PREFER_DATES_FROM": "future"})
    if not dt:
        return "Could not parse date/time reference."
    return dt.isoformat(sep="T", timespec="seconds")


@tool(parse_docstring=True)
def get_current_datetime() -> str:
    """Gets immediate or current date and time in ISO format (YYYY-MM-DDTHH:MM:SS)"""
    return str(datetime.now().isoformat())
