from cryptography.fernet import Fernet

from services.utils import get_env


class Configuration:
    DATABASE_URL = get_env("DATABASE_URL", None)
    CRYPT_SECRET_KEY = get_env("CRYPT_SECRET_KEY", None)
    REDIS_URL = get_env("REDIS_URL", None)
    CONVERSATION_GRACE_PERIOD = int(get_env("CONVERSATION_GRACE_PERIOD_SECONDS", 120))
    CONVERSATION_TTL_HOURS = int(get_env("CONVERSATION_TTL_HOURS", 1))
    CREATE_CHAT_RATE_LIMIT = int(get_env("CREATE_CHAT_RATE_LIMIT", 5))
    CREATE_CHAT_RATE_WINDOW_SECONDS = int(get_env("CREATE_CHAT_RATE_WINDOW_SECONDS", 60))
    JOIN_RATE_LIMIT = int(get_env("JOIN_RATE_LIMIT", 8))
    JOIN_RATE_WINDOW_SECONDS = int(get_env("JOIN_RATE_WINDOW_SECONDS", 60))
    MESSAGE_RATE_LIMIT = int(get_env("MESSAGE_RATE_LIMIT", 30))
    MESSAGE_RATE_WINDOW_SECONDS = int(get_env("MESSAGE_RATE_WINDOW_SECONDS", 10))
    MAX_PARTICIPANTS_PER_CONVERSATION = int(get_env("MAX_PARTICIPANTS_PER_CONVERSATION", 2))
    PRESENCE_TTL_SECONDS = int(get_env("PRESENCE_TTL_SECONDS", 45))
    HEARTBEAT_INTERVAL_SECONDS = int(get_env("HEARTBEAT_INTERVAL_SECONDS", 15))
    WS_SEND_QUEUE_SIZE = int(get_env("WS_SEND_QUEUE_SIZE", 64))
    WS_SEND_TIMEOUT_SECONDS = float(get_env("WS_SEND_TIMEOUT_SECONDS", 5))
    DB_POOL_SIZE = int(get_env("DB_POOL_SIZE", 10))
    DB_MAX_OVERFLOW = int(get_env("DB_MAX_OVERFLOW", 10))
    REDIS_MAX_CONNECTIONS = int(get_env("REDIS_MAX_CONNECTIONS", 100))
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in get_env(
            "CORS_ALLOWED_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000",
        ).split(",")
        if origin.strip()
    ]

    def validate(self):
        missing = []
        
        if not self.DATABASE_URL:
            missing.append("DATABASE URL")
        if not self.CRYPT_SECRET_KEY:
            missing.append("CRYPT SECRET KEY")
        if not self.REDIS_URL:
            missing.append("REDIS URL")

        if missing:
            raise RuntimeError(f"Missing required env variables: {', '.join(missing)}")
        
        try:
            Fernet(self.CRYPT_SECRET_KEY.encode())
        except Exception as exc:
            raise RuntimeError("CRYPT SECRET KEY must be a valid Fernet key.") from exc

        positive_settings = {
            "CREATE_CHAT_RATE_LIMIT": self.CREATE_CHAT_RATE_LIMIT,
            "CREATE_CHAT_RATE_WINDOW_SECONDS": self.CREATE_CHAT_RATE_WINDOW_SECONDS,
            "JOIN_RATE_LIMIT": self.JOIN_RATE_LIMIT,
            "JOIN_RATE_WINDOW_SECONDS": self.JOIN_RATE_WINDOW_SECONDS,
            "MESSAGE_RATE_LIMIT": self.MESSAGE_RATE_LIMIT,
            "MESSAGE_RATE_WINDOW_SECONDS": self.MESSAGE_RATE_WINDOW_SECONDS,
            "CONVERSATION_TTL_HOURS": self.CONVERSATION_TTL_HOURS,
            "PRESENCE_TTL_SECONDS": self.PRESENCE_TTL_SECONDS,
            "HEARTBEAT_INTERVAL_SECONDS": self.HEARTBEAT_INTERVAL_SECONDS,
            "WS_SEND_QUEUE_SIZE": self.WS_SEND_QUEUE_SIZE,
            "WS_SEND_TIMEOUT_SECONDS": self.WS_SEND_TIMEOUT_SECONDS,
            "MAX_PARTICIPANTS_PER_CONVERSATION": self.MAX_PARTICIPANTS_PER_CONVERSATION,
            "DB_POOL_SIZE": self.DB_POOL_SIZE,
            "REDIS_MAX_CONNECTIONS": self.REDIS_MAX_CONNECTIONS,
        }
        for name, value in positive_settings.items():
            if value <= 0:
                raise RuntimeError(f"{name} must be greater than 0.")

        if self.DB_MAX_OVERFLOW < 0:
            raise RuntimeError("DB_MAX_OVERFLOW cannot be negative.")

        if self.MAX_PARTICIPANTS_PER_CONVERSATION < 2:
            raise RuntimeError("MAX_PARTICIPANTS_PER_CONVERSATION must be at least 2.")

        if self.PRESENCE_TTL_SECONDS <= self.HEARTBEAT_INTERVAL_SECONDS * 2:
            raise RuntimeError("PRESENCE_TTL_SECONDS must exceed two heartbeat intervals.")
        

