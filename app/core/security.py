from collections.abc import Callable
import time

from fastapi import Depends, Header, HTTPException
from firebase_admin import auth

from app.core.firebase import db
from app.schemas.auth_schema import CurrentUser, UserRole


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

    firestore_start = time.perf_counter()
    user_doc = db.collection("users").document(uid).get()
    print(
        "[PERF] get_current_user Firestore users/{uid}.get "
        f"(reads=1): {(time.perf_counter() - firestore_start) * 1000:.2f} ms"
    )

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="Usuario autenticado no encontrado")

    user_data = user_doc.to_dict() or {}
    raw_role = user_data.get("role")

    if not raw_role:
        raise HTTPException(status_code=403, detail="El usuario autenticado no tiene un rol configurado")

    try:
        parsed_role = UserRole(raw_role)
    except ValueError:
        raise HTTPException(status_code=403, detail="El rol del usuario autenticado no es valido")

    response_start = time.perf_counter()
    current_user = CurrentUser(
        uid=uid,
        email=user_data.get("email") or decoded_token.get("email") or "",
        name=user_data.get("name") or decoded_token.get("name") or "",
        role=parsed_role,
        provider=user_data.get("provider"),
        picture=user_data.get("picture") or decoded_token.get("picture"),
        created_at=user_data.get("created_at"),
    )
    print(f"[PERF] get_current_user build CurrentUser: {(time.perf_counter() - response_start) * 1000:.2f} ms")
    print(f"[PERF] get_current_user total: {(time.perf_counter() - start) * 1000:.2f} ms")
    return current_user


def require_role(role: UserRole | str) -> Callable:
    required_role = role if isinstance(role, UserRole) else UserRole(role)

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role != required_role:
            raise HTTPException(status_code=403, detail="Rol no autorizado para este recurso")

        return current_user

    return dependency
