from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func
from .db import Base

class City(Base):
    __tablename__ = 'cities'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    rp5_url = Column(Text, nullable=False)
    sheet_name = Column(String(31), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class RunLog(Base):
    __tablename__ = 'run_logs'
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(50), nullable=False, default='idle')
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    output_file = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
