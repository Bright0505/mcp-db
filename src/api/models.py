"""Shared Pydantic models for the REST API layer."""

from typing import Any, List, Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    params: Optional[List[Any]] = None


class CacheInvalidateRequest(BaseModel):
    table_name: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    database_connected: bool
