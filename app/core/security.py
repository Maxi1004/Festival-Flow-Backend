from collections.abc import Callable
import os
import time

from fastapi import Depends, Header, HTTPException
from firebase_admin import auth

from app.core.firebase import db
from app.schemas.auth_schema import CurrentUser, UserRole

_AUTH_CACHE_TTL_SECONDS = 300
_auth_user_cache: dict[str, tuple[float, CurrentUser]] = {}


def _dev_auth_fallback_enabled() -> bool:
    return os.getenv("DEV_AUTH_FALLBACK", "").strip().lower() == "true"


def _is_quota_exceeded_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "resourceexhausted" in text
        or "resource exhausted" in text
        or "quota exceeded" in text
        or "429" in text
    )


def _cache_get(uid: str) -> "tuple[CurrentUser | None, bool]":
    cached = _auth_user_cache.get(uid)
    if not cached:
        print("[Auth Cache] MISS")
        return None, False

    cached_at, current_user = cached
    is_fresh = (time.time() - cached_at) < _AUTH_CACHE_TTL_SECONDS
    if is_fresh:
        print("[Auth Cache] HIT")
    return current_user, is_fresh


def _cache_set(uid: str, current_user: CurrentUser) -> None:
    _auth_user_cache[uid] = (time.time(), current_user)


def _current_user_from_token(decoded_token: dict) -> CurrentUser:
    return CurrentUser(
        uid=decoded_token.get("uid") or "",
        email=decoded_token.get("email") or "",
        name="Dev User",
        role=UserRole.PRODUCER,
        provider=decoded_token.get("firebase", {}).get("sign_in_provider"),
        picture=decoded_token.get("picture"),
        photo_url=decoded_token.get("picture"),
        created_at=None,
    )


def verify_firebase_token(authorization: str = Header(None)):
    start = time.perf_counter()
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header faltante")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token mal formado")

    token = authorization.replace("Bearer ", "").strip()

    try:
        decoded_token = auth.verify_id_token(token, clock_skew_seconds=30)
        print(f"[PERF] auth.verify_id_token: {(time.perf_counter() - start) * 1000:.2f} ms")
        return decoded_token
    except Exception as e:
        print("ERROR VERIFY TOKEN:", e)
        raise HTTPException(status_code=401, detail=f"Token invalido o expirado: {str(e)}")


def get_current_user(decoded_token: dict = Depends(verify_firebase_token)) -> CurrentUser:
    start = time.perf_counter()
    uid = decoded_token.get("uid")

    if not uid:
        raise HTTPException(status_code=401, detail="Token invalido")

    cached_user, cache_is_fresh = _cache_get(uid)
    if cached_user and cache_is_fresh:
        return cached_user

    firestore_start = time.perf_counter()
    try:
        user_doc = db.collection("users").document(uid).get()
        print(
            "[PERF] get_current_user Firestore users/{uid}.get "
            f"(reads=1): {(time.perf_counter() - firestore_start) * 1000:.2f} ms"
        )
    except Exception as exc:
        if _is_quota_exceeded_error(exc):
            print("[Auth Cache] QUOTA_EXCEEDED")
            if cached_user:
                print("[Auth Cache] STALE_USED")
                return cached_user
            if _dev_auth_fallback_enabled():
                print("[Auth Dev Fallback] Firestore quota exceeded, using token user")
                current_user = _current_user_from_token(decoded_token)
                _cache_set(uid, current_user)
                return current_user
        raise

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="Usuario autenticado no encontrado")

    user_data = user_doc.to_dict() or {}
    raw_role = user_data.get("role")
    parsed_role = None
    if raw_role:
        try:
            parsed_role = UserRole(str(raw_role).strip().upper())
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail="El rol del usuario autenticado no es valido",
            )

    response_start = time.perf_counter()
    current_user = CurrentUser(
        uid=uid,
        email=user_data.get("email") or decoded_token.get("email") or "",
        name=user_data.get("name") or decoded_token.get("name") or "",
        role=parsed_role,
        provider=user_data.get("provider"),
        picture=user_data.get("picture") or decoded_token.get("picture"),
        photo_url=user_data.get("photo_url"),
        created_at=user_data.get("created_at"),
    )
    print(f"[PERF] get_current_user build CurrentUser: {(time.perf_counter() - response_start) * 1000:.2f} ms")
    print(f"[PERF] get_current_user total: {(time.perf_counter() - start) * 1000:.2f} ms")
    _cache_set(uid, current_user)
    return current_user


def require_role(role: UserRole | str) -> Callable:
    required_role = role if isinstance(role, UserRole) else UserRole(role)

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role != required_role:
            raise HTTPException(status_code=403, detail="Rol no autorizado para este recurso")

        return current_user

    return dependency
