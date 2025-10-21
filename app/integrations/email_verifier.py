from abc import ABC, abstractmethod
from typing import List, Dict, Literal

Verification = Literal["valid","invalid","disposable","catchall","unknown"]

class EmailVerifier(ABC):
    @abstractmethod
    async def check_single(self, email: str) -> Verification: ...
    @abstractmethod
    async def bulk_verify(self, emails: List[str]) -> Dict[str, Verification]: ...
