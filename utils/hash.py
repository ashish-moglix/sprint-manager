import hashlib

def hash_password(password: str) -> str:
    """Hash password using SHA256 with a salt."""
    salt = "EMCockpitSaltKey123!"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
