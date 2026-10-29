from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

# pool_pre_ping drops dead connections instead of failing on the next request
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)