from fastapi import Header, HTTPException
from firebase_admin import auth

def verify_firebase_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header faltante")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token mal formado")

    token = authorization.replace("Bearer ", "").strip()

    try:
        decoded_token = auth.verify_id_token(token, clock_skew_seconds=30)
        return decoded_token
    except Exception as e:
        print("ERROR VERIFY TOKEN:", e)
        raise HTTPException(status_code=401, detail=f"Token inválido o expirado: {str(e)}")