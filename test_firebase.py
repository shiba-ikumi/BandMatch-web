import os
import firebase_admin
from firebase_admin import credentials, firestore

# 自分のPCの鍵の場所(実際のパスに書き換える)
KEY_PATH = r"C:\Users\zibat\Downloads\bandmatch2-f6a16-firebase-adminsdk-fbsvc-e2a688a715.json"

if os.path.exists(KEY_PATH):
    # 自分のPCで動かすとき
    firebase_admin.initialize_app(credentials.Certificate(KEY_PATH))
else:
    # Cloud Run で動かすとき(鍵なしで自動認証)
    firebase_admin.initialize_app()

db = firestore.client()

db.collection("test").document("hello").set({"message": "こんにちは"})
print(db.collection("test").document("hello").get().to_dict())