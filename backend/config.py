from cryptography.fernet import Fernet

from services.utils import get_env


class Configuration:
    DATABASE_URL = get_env("DATABASE_URL", None)
    TEXTIE_API_KEY = get_env("TEXTIE_API_KEY", None)
    CRYPT_SECRET_KEY = get_env("CRYPT_SECRET_KEY", None)
    REDIS_URL = get_env("REDIS_URL", None)
    CONVERSATION_GRACE_PERIOD = get_env("CONVERSATION_GRACE_PERIOD_SECONDS", 120)

    def validate(self):
        missing = []
        
        if not self.DATABASE_URL:
            missing.append("DATABASE URL")
        if not self.CRYPT_SECRET_KEY:
            missing.append("CRYPT SECRET KEY")

        if missing:
            raise RuntimeError(f"Missing required env variables: {', '.join(missing)}")
        
        try:
            Fernet(self.CRYPT_SECRET_KEY.encode())
        except Exception as e:
            raise RuntimeError("CRYPT SECRET KEY must be a valid Fernet key.")
        

