from cryptography.fernet import Fernet
from config import Configuration

config = Configuration()
config.validate()
fernet = Fernet(key=config.CRYPT_SECRET_KEY)


def _encrypt(text: str) -> bytes:
    encrypted_text = fernet.encrypt(text.encode("utf-8"))
    return encrypted_text

def _decrypt(text: str) -> str:
    decrypted_text = fernet.decrypt(text).decode("utf-8")
    return decrypted_text