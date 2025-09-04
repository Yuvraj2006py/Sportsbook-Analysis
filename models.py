from sqlalchemy import Column, Integer, String, Float, DateTime, Date
from db import Base
from datetime import datetime, timezone

class Odds(Base):
    __tablename__ = "odds"

    id = Column(Integer, primary_key=True, index=True)
    sportsbook = Column(String, index=True)
    league = Column(String)
    event = Column(String, index=True)
    market = Column(String)
    outcome = Column(String)
    line = Column(String, nullable=True)  
    odds_decimal = Column(Float)
    odds_american = Column(String, nullable=True)  # American odds (e.g., +200 / -110)
    event_date = Column(Date, nullable=True)
    last_updated = Column(
        DateTime,   
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    commence_time = Column(DateTime, nullable=True)

