import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    MAX_QID: int = int(os.getenv("MAX_QID", "33408830"))
    MIN_QID: int = int(os.getenv("MIN_QID", "1"))
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "25000"))
    
    CONCURRENCY: int = int(os.getenv("CONCURRENCY", "3"))
    REQUESTS_PER_SECOND: float = float(os.getenv("REQUESTS_PER_SECOND", "4.0"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "12"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    BACKOFF_ON_429: int = int(os.getenv("BACKOFF_ON_429", "15"))
    
    DOWNLOAD_IMAGES: bool = os.getenv("DOWNLOAD_IMAGES", "true").lower() in ("true", "1", "yes")
    FOLLOW_PAGINATION: bool = os.getenv("FOLLOW_PAGINATION", "true").lower() in ("true", "1", "yes")
    
    COORDINATOR_URL: str = os.getenv("COORDINATOR_URL", "http://norbert232.mikrus.xyz:20232")
    VOLUNTEER_NAME: str = os.getenv("VOLUNTEER_NAME", "anonymous_volunteer")
    HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
    LEASE_TIMEOUT_MINUTES: int = int(os.getenv("LEASE_TIMEOUT_MINUTES", "60"))
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/coordinator.db")
    
    WARCS_DIR: str = os.getenv("WARCS_DIR", "./warcs")
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    
    IA_ACCESS_KEY: str = os.getenv("IA_ACCESS_KEY", "")
    IA_SECRET_KEY: str = os.getenv("IA_SECRET_KEY", "")
    AUTO_UPLOAD: bool = os.getenv("AUTO_UPLOAD", "true").lower() in ("true", "1", "yes")

settings = Settings()
