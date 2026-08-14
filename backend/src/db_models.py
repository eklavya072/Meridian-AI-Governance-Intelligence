from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Integer,
    Float,
    Boolean,
    ForeignKey,
    JSON,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class WorkspaceStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    GENERATING_REPORT = "generating_report"
    COMPLETE = "complete"
    ERROR = "error"
    # AI Auditor: a document uploaded for chat only — ingested into the vector
    # store but never run through the dimension analysis pipeline. Excluded
    # from the analysis/brief selects (which filter on "complete").
    CHAT_ONLY = "chat_only"


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    country = Column(String(255), nullable=False)
    policy_title = Column(String(500), nullable=False)
    policy_file_path = Column(String(1000), nullable=True)
    policy_file_name = Column(String(500), nullable=True)
    frameworks = Column(JSON, nullable=False, default=list)
    status = Column(SAEnum(WorkspaceStatus), default=WorkspaceStatus.QUEUED, nullable=False)
    status_detail = Column(Text, nullable=True)
    dimension_results = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    analyses = relationship("Analysis", back_populates="workspace", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="workspace", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="workspace", cascade="all, delete-orphan")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    document_name = Column(String(500), nullable=False)
    frameworks_used = Column(JSON, nullable=False, default=list)
    governance_gaps = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    total_retrieved = Column(Integer, default=0)
    retrieval_frameworks = Column(JSON, nullable=True)
    similarity_scores = Column(JSON, nullable=True)
    llm_latency = Column(Float, default=0.0)
    total_processing_time = Column(Float, default=0.0)
    retrieval_count = Column(Integer, default=0)
    citation_pass_count = Column(Integer, default=0)
    citation_fail_count = Column(Integer, default=0)
    ragas_metrics = Column(JSON, nullable=True)
    generated_by = Column(JSON, nullable=True)
    status = Column(String(50), default="complete")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="analyses")


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    type = Column(String(50), nullable=False)  # "executive_brief" or "powerpoint"
    file_path = Column(String(1000), nullable=True)
    # Executive brief (Part 3): content = plain-text/markdown rendering,
    # meta = the full structured brief JSON (single source of truth for the
    # frontend preview and the DOCX/PDF exporters). Columns added via ALTER
    # TABLE in main.py's lifespan for existing installs.
    content = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="reports")


class FrameworkSyncRecord(Base):
    __tablename__ = "framework_sync_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    framework_name = Column(String(500), nullable=False)
    version = Column(String(100), nullable=True)
    checksum = Column(String(128), nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="pending")  # pending, synced, error
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UploadLog(Base):
    __tablename__ = "upload_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    filename = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    validation_passed = Column(Boolean, nullable=False)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    ocr_warning = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable: Mode A (general educational) sessions have no workspace scope.
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    finding_id = Column(String(255), nullable=True)
    mode = Column(String(50), nullable=False, default="advisor")  # "advisor" | "framework_qa"
    title = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(50), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)
    retrieval_count = Column(Integer, default=0)
    citation_pass_count = Column(Integer, default=0)
    citation_fail_count = Column(Integer, default=0)
    llm_latency = Column(Float, default=0.0)
    guardrail_result = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ChatSession", back_populates="messages")
