import logging
import os
import time

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import MetaData

from config import Configuration

config = Configuration()
config.validate()

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = declarative_base(metadata=metadata)
engine = create_engine(
    url=config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,
    pool_timeout=30,
)
session_local = sessionmaker(
    autocommit=False,
    expire_on_commit=False,
    autoflush=True,
    bind=engine,
)
logger = logging.getLogger(__name__)
_pool_metrics = {
    "checkouts": 0,
    "wait_seconds_total": 0.0,
    "wait_seconds_max": 0.0,
}


@contextmanager
def db_session():
    db = session_local()
    try:
        started = time.perf_counter()
        db.connection()
        elapsed = time.perf_counter() - started
        _pool_metrics["checkouts"] += 1
        _pool_metrics["wait_seconds_total"] += elapsed
        _pool_metrics["wait_seconds_max"] = max(
            _pool_metrics["wait_seconds_max"], elapsed
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        logger.error("Database session failed")
        raise
    finally:
        db.close()


def database_pool_metrics():
    return {
        **_pool_metrics,
        "checked_out": engine.pool.checkedout(),
        "pool_size": engine.pool.size(),
        "overflow": engine.pool.overflow(),
        "process_id": os.getpid(),
    }
