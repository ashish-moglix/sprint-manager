import jwt
import os
import datetime
from bson import ObjectId
from utils.db import get_mongo_db, clear_db_caches
from utils.hash import hash_password

JWT_SECRET = os.environ.get("JWT_SECRET", "EMCockpitSecretKey123!")
JWT_ALGORITHM = "HS256"

def create_token(user_data: dict) -> str:
    """Create a signed JWT token containing user details with a 24-hour expiration."""
    payload = {
        "id": user_data["id"],
        "name": user_data["name"],
        "email": user_data["email"],
        "user_role": user_data["user_role"],
        "team_id": user_data.get("team_id"),
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    """Verify and decode a JWT token. Returns decoded dictionary or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def change_user_password(user_id: str, new_password: str) -> bool:
    """Update a user's password in MongoDB after hashing it."""
    try:
        db = get_mongo_db()
        db['users'].update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"password": hash_password(new_password)}}
        )
        clear_db_caches()
        return True
    except Exception:
        return False
