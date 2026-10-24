"""Database model definitions and table references (Neon Postgres)."""

# Model schema documentation aligned with TechSpec Section 4:
#
# users:
#   id: UUID PK
#   auth_subject: str UNIQUE
#   email: Optional[str]
#   created_at: datetime
#
# projects:
#   id: UUID PK
#   user_id: UUID FK (nullable for local prototype)
#   title: str
#   status: str (draft, upload_pending, uploaded, processing, ready_for_review, rendering, completed, failed, deleting, deleted)
#   source_asset_id: Optional[UUID]
#   created_at: datetime
#   updated_at: datetime
#   deleted_at: Optional[datetime]
#
# assets:
#   id: UUID PK
#   project_id: UUID FK
#   kind: str (source, output, subtitle, thumbnail)
#   object_key: str UNIQUE
#   mime_type: str
#   size_bytes: int
#   duration_seconds: float
#   width: int
#   height: int
#   status: str (pending_upload, uploaded, processing, ready, failed, deleting, deleted)
#   checksum: Optional[str]
#   created_at: datetime
#
# jobs:
#   id: UUID PK
#   project_id: UUID FK
#   type: str
#   status: str (queued, running, retry_queued, completed, failed, cancel_requested, cancelled)
#   current_stage: Optional[str]
#   progress: float
#   attempts: int
#   max_attempts: int
#   idempotency_key: Optional[str]
#   input_config: dict (JSONB)
#   error_code: Optional[str]
#   safe_error_message: Optional[str]
#   created_at: datetime
#   started_at: Optional[datetime]
#   finished_at: Optional[datetime]
#   heartbeat_at: Optional[datetime]
#
# clip_candidates:
#   id: UUID PK
#   project_id: UUID FK
#   generation_job_id: UUID FK
#   start_seconds: float
#   end_seconds: float
#   hook: str
#   transcript_excerpt: str
#   editorial_goal: str
#   overall_score: int (0..100)
#   score_breakdown: dict (JSONB)
#   rationale: str
#   evidence: list (JSONB)
#   confidence_label: str
#   validation_status: str
#   selected: bool
#   status: str
#   user_edited: bool
