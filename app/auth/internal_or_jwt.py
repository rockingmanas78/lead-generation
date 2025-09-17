# app/auth/internal_or_jwt.py
import hmac
import time
import jwt
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import JWT_SECRET, JWT_ALGORITHM, WEBHOOK_SECRET

class InternalOrJWTBearer(HTTPBearer):
    """
    For specific paths, allow internal calls with x-internal-secret == WEBHOOK_SECRET.
    Otherwise, behave exactly like JWTBearer.
    """
    def __init__(self, allowed_internal_paths: set[str], auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        print(allowed_internal_paths)
        self.allowed_internal_paths = allowed_internal_paths

    async def __call__(self, request: Request):
        # 1) Internal secret path bypass
        print("Request URL Path:", request.url.path)
        path = request.url.path
        internal_secret = request.headers.get("x-internal-secret")
        print("Internal Secret Header:", internal_secret)

        if path in self.allowed_internal_paths and internal_secret and WEBHOOK_SECRET:
            # Constant-time compare
            if hmac.compare_digest(internal_secret, WEBHOOK_SECRET):
                request.state.auth = {"mode": "internal"}  # mark it for downstream
                return None  # no JWT token returned (and not needed)
            # wrong secret on an internal-allowed path
            raise HTTPException(status_code=403, detail="Invalid internal secret.")

        # 2) Otherwise do normal JWT auth (same behavior as your JWTBearer)
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials or credentials.scheme != "Bearer":
            raise HTTPException(status_code=403, detail="Invalid authentication scheme.")

        token = credentials.credentials
        payload = self._decode_jwt(token)
        if not payload:
            raise HTTPException(status_code=403, detail="Invalid token or expired token.")

        request.state.auth = {"mode": "jwt", "token": token, "payload": payload}
        return token

    def _decode_jwt(self, token: str) -> dict | None:
        try:
            decoded = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return decoded if decoded.get("exp", 0) >= time.time() else None
        except Exception:
            return None
