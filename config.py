import os
from firebase_admin import credentials, initialize_app, firestore, storage

FIREBASE_CREDENTIALS = "./firebase-adminsdk.json"
FIREBASE_STORAGE_BUCKET = "prototype-finkraft.appspot.com"  # Your bucket name

def initialize_firebase():
    cred = credentials.Certificate(FIREBASE_CREDENTIALS)
    initialize_app(cred, {
        'storageBucket': FIREBASE_STORAGE_BUCKET
    })
    return firestore.client(), storage.bucket()
