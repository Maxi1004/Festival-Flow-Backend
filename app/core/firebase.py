import json
import os

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()

firebase_service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
firebase_key_path = os.getenv("FIREBASE_KEY_PATH")

if not firebase_admin._apps:
    if firebase_service_account_json:
        service_account_dict = json.loads(firebase_service_account_json)
        private_key = service_account_dict.get("private_key")
        if private_key:
            service_account_dict["private_key"] = private_key.replace("\\n", "\n")
        cred = credentials.Certificate(service_account_dict)
    else:
        if not firebase_key_path:
            raise ValueError("FIREBASE_KEY_PATH no esta definido en el .env")
        cred = credentials.Certificate(firebase_key_path)

    firebase_admin.initialize_app(cred)

db = firestore.client()
