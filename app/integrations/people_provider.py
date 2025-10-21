from abc import ABC, abstractmethod
from typing import Optional, Dict

class PeopleProvider(ABC):
    @abstractmethod
    async def get_person_by_linkedin_url(self, url: str) -> Optional[Dict]: ...
    @abstractmethod
    async def get_company_by_linkedin_url(self, url: str) -> Optional[Dict]: ...
