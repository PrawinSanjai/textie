import os, random, secrets, hashlib
from dotenv import load_dotenv

load_dotenv()


def get_env(var: str, default = None):
    val = os.getenv(var.upper())
    if val is None:
        return default
    return val

def generate_code() -> str:
    return str(random.randint(100000, 999999))

def generate_token() -> str:
    return secrets.token_urlsafe(32)

def generate_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()