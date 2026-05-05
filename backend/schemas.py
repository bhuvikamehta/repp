from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class TaskType(str, Enum):
    SUMMARY = 'summary'
    REPORT = 'report'

class InputMode(str, Enum):
    TEXT_ONLY = 'text_only'
    DOCUMENT_BASED = 'document_based'

class DocumentMetadata(BaseModel):
    attached: bool
    file_type: str = Field(pattern=r'^(pdf|txt|docx|none)$')
    file_name: Optional[str] = None
    content: Optional[str] = None
    size: Optional[int] = None
    low_signal: Optional[bool] = None

class CustomSection(BaseModel):
    title: str
    content: str
    image_keyword: Optional[str] = None

class Diagram(BaseModel):
    title: str
    mermaid_code: str

class Constraints(BaseModel):
    hallucination_allowed: bool
    output_structure_required: bool

class NormalizedIntent(BaseModel):
    request_id: str
    task_type: TaskType
    input_mode: InputMode
    user_prompt: str
    detected_category: str
    content_scope: str
    confidence_score: float
    is_ambiguous: bool
    is_supported: bool
    rejection_reason: Optional[str] = None
    constraints: Constraints
    timestamp: str
    document_metadata: DocumentMetadata

class ReportContent(BaseModel):
    hero_image_keyword: str
    executive_summary: str
    highlights: List[str]
    risks_and_blockers: List[str]
    actions_required: List[str]
    evidence_links: List[str]
    diagrams: List[Diagram]
    additional_sections: List[CustomSection]

class FinalReportJSON(BaseModel):
    request_id: str
    status: str = Field(pattern=r'^(completed|error|cached)$')
    report: ReportContent
    source_type: str = Field(pattern=r'^(text|document)$')
    confidence_level: str = Field(pattern=r'^(high|medium|low)$')
    generated_at: str

class ValidationError(BaseModel):
    status: str = "error"
    error_type: str  # e.g. UNSUPPORTED_TASK, INVALID_FORMAT, QUOTA_EXCEEDED, API_UNAVAILABLE, etc.
    message: str

class LogEntry(BaseModel):
    id: str
    timestamp: str
    type: str = Field(pattern=r'^(info|warn|error|success|api|db|guardrail)$')
    message: str
    payload: Optional[Any] = None

class OrganizationCreateRequest(BaseModel):
    name: str
    email: str
    password: str

class SignupRequest(BaseModel):
    email: str
    password: str
    org_code: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UpdateRoleRequest(BaseModel):
    role: str = Field(pattern=r'^(admin|member)$')

