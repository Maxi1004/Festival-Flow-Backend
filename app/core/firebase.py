import os

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()

firebase_key_path = os.getenv("FIREBASE_KEY_PATH")

if not firebase_key_path:
    raise ValueError("FIREBASE_KEY_PATH no está definido en el .env")

if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_key_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()