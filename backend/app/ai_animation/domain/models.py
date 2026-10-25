"""Pydantic data contract schemas for AI Animation Studio.

Reflects the data contracts specified in Section 5 of the Animation Studio PRD:
- script.json
- asset_manifest.json
- scene_plan.json
- coverage_report.json
- animation_run_manifest.json
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# --- 1. Script Contracts ---
class ScriptStatus(str, Enum):
    DRAFT = "draft"
    FINAL = "final"


class ScriptSection(BaseModel):
    id: str = Field(..., description="Unique section identifier (e.g. 'sec_01_hook')")
    title: str = Field(..., description="Section title or narrative phase")
    narration: str = Field(..., description="Spoken narration text for this section")
    target_duration_seconds: Optional[float] = Field(default=None, description="Estimated target duration")


class Script(BaseModel):
    schema_version: str = Field(default="v1.0")
    title: str = Field(..., description="Topic or title of the animation video")
    target_audience: Optional[str] = Field(default=None)
    tone: Optional[str] = Field(default="calm, motivating, clear")
    status: ScriptStatus = Field(default=ScriptStatus.DRAFT, description="Draft vs Finalized gate")
    version: int = Field(default=1, description="Version counter incremented on edits")
    sections: List[ScriptSection] = Field(default_factory=list, description="Ordered script sections")


# --- 2. Asset Manifest Contracts ---
class AssetItem(BaseModel):
    id: str = Field(..., description="Unique asset identifier (e.g. 'bg_office_01', 'pose_point')")
    type: Literal["background", "prop", "character", "pose", "expression", "action", "music"] = Field(...)
    tags: List[str] = Field(default_factory=list, description="Search and categorization tags")
    description: str = Field(..., description="Visual or descriptive specification")
    file_path: Optional[str] = Field(default=None, description="Relative file path within assets directory")


class AssetManifest(BaseModel):
    schema_version: str = Field(default="v1.0")
    version: str = Field(default="1.0.0")
    assets: List[AssetItem] = Field(default_factory=list, description="Registered library assets")


# --- 3. Scene Plan Contracts ---
class CharacterPlacement(BaseModel):
    id: str = Field(..., description="Character identifier (e.g. 'narrator', 'bystander_1')")
    pose: str = Field(default="idle", description="Pose identifier matching asset manifest")
    expression: str = Field(default="neutral", description="Expression identifier matching asset manifest")
    position_x: Optional[float] = Field(default=0.5, description="Normalized horizontal position (0.0 to 1.0)")


class BeatSceneSpec(BaseModel):
    layout: str = Field(default="medium_shot", description="Shot composition (e.g. wide, two_shot, close_up)")
    background: str = Field(..., description="Background asset id matching manifest")
    characters: List[CharacterPlacement] = Field(default_factory=list)
    props: List[str] = Field(default_factory=list, description="Prop asset ids matching manifest")
    action: str = Field(default="none", description="Action sequence identifier")
    camera: str = Field(default="static", description="Camera move (e.g. static, zoom_in, pan_left)")


class Beat(BaseModel):
    id: str = Field(..., description="Unique beat identifier (e.g. 's01_b01')")
    narration: str = Field(..., description="Narration line spoken during this beat")
    scene: BeatSceneSpec = Field(...)


class Scene(BaseModel):
    id: str = Field(..., description="Scene identifier (e.g. 'scene_01')")
    title: Optional[str] = Field(default=None)
    beats: List[Beat] = Field(default_factory=list, description="Ordered sequence of beats in scene")


class ScenePlan(BaseModel):
    schema_version: str = Field(default="v1.0")
    title: str = Field(...)
    script_version: int = Field(..., description="Version of finalized script this plan was built against")
    scenes: List[Scene] = Field(default_factory=list)


# --- 4. Coverage Report Contracts ---
class SceneCoverageItem(BaseModel):
    scene_id: str
    status: Literal["reuse", "substitute", "missing"]
    missing_assets: List[str] = Field(default_factory=list)
    substitutions: Dict[str, str] = Field(default_factory=dict)


class CoverageReport(BaseModel):
    schema_version: str = Field(default="v1.0")
    total_scenes: int = 0
    ready_scenes: int = 0
    scenes: List[SceneCoverageItem] = Field(default_factory=list)
    backlog_missing_assets: List[Dict[str, Any]] = Field(default_factory=list)


# --- 5. Run Manifest Contracts ---
class AnimationRunManifest(BaseModel):
    schema_version: str = Field(default="v1.0")
    run_id: str = Field(...)
    created_at: str = Field(...)
    status: Literal["pending", "scripting", "planning", "voiceover", "rendering", "completed", "failed"] = "pending"
    script_path: Optional[str] = None
    scene_plan_path: Optional[str] = None
    coverage_report_path: Optional[str] = None
    rendered_video_path: Optional[str] = None
    total_duration_seconds: float = 0.0
    errors: List[str] = Field(default_factory=list)
