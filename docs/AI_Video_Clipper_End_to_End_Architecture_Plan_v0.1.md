# AI Video Clipper --- End-to-End Product & Architecture Plan

**Document status:** Proposed architecture baseline for repository
review\
**Version:** 0.1\
**Date:** 2026-10-24\
**Purpose:** Give the local coding agent and product owner a shared
end-to-end target architecture, implementation sequence, and progress
tracker before production changes begin.

> **Important:** This is the intended architecture based on current
> product decisions. The local coding agent must compare it with the
> actual repository, identify mismatches and implementation constraints,
> and recommend targeted amendments. This document does not authorize
> immediate implementation or override the approved PRD/TechSpec.

------------------------------------------------------------------------

## 1. Executive summary

AI Video Clipper is a local-first application for finding coherent
long-form moments in transcript-heavy videos, producing clean long
clips, and optionally finding shorter standalone moments inside each
accepted long clip.

The core hierarchy is deliberately limited to two levels:

``` text
Original video
├── Transcript + original-video analysis
├── Long clip 01 (clean, reframed master)
│   ├── Transcript/timing + clip-specific analysis
│   ├── Short clip 01 (clean master → final render)
│   └── Short clip 02 (clean master → final render)
├── Long clip 02
│   ├── Transcript/timing + clip-specific analysis
│   └── Short clip 01
└── Long clip 03
    └── No short clips (valid outcome)
```

The long-clip and short-clip workflows are separate and independently
callable. A full end-to-end workflow orchestrates them using the same
underlying services; it must not implement a third, duplicated version
of either pipeline.

The original video is analyzed to discover long clips and, in the
future, to inform visual framing. Each accepted long clip becomes a
reusable, self-contained processing artifact. The short-clip workflow
operates on that long clip and its inherited transcript/analysis
artifacts rather than repeatedly sending the entire original video
through analysis.

The application owns production file paths and writes. Models return
structured candidate data; they do not choose filesystem paths or write
production files.

------------------------------------------------------------------------

## 2. Product goals and non-goals

### 2.1 Goals

1.  Discover coherent, meaningful long clips from transcript-heavy
    source videos.
2.  Improve boundary quality so clips do not routinely begin mid-thought
    or end mid-word/mid-conversation.
3.  Produce clean, reframed master clips before adding our own captions
    or visual effects.
4.  Optionally discover shorter, independently understandable moments
    inside each long clip.
5.  Reuse transcripts, word timestamps, and applicable analysis
    artifacts.
6.  Preserve parent-child lineage from original video → long clip →
    short clip.
7.  Make long-only, short-only, and full-pipeline execution possible.
8.  Store input and output in deterministic, traversable local folders
    now, while keeping metadata portable to future R2/object storage and
    Neon metadata storage.
9.  Support configurable caption styles and future filters without
    baking presentation choices into the clean master.
10. Track progress, failures, re-runs, and artifact versions.
11. Keep experimental output isolated from production output.
12. Make quality measurable using human review and explicit metrics.

### 2.2 Non-goals for the initial implementation

-   Implementing visual analysis immediately as part of the
    architecture-document task.
-   Implementing audio-event analysis immediately.
-   Replacing the current LLM provider architecture or removing the
    OpenAI fallback.
-   Rewriting the approved PRD or TechSpec without explicit approval.
-   Rebuilding the frontend or introducing a production cloud-storage
    workflow before the local pipeline is reliable.
-   Recursively generating short clips from short clips.
-   Forcing a fixed number of long or short clips when the source does
    not contain enough good moments.
-   Treating model scores as calibrated probabilities of virality.
-   Adding filters, multiple caption presets, or advanced visual effects
    before the clean-master/render separation is in place.

------------------------------------------------------------------------

## 3. Current baseline and constraints

The local agent must verify this section against the repository before
implementation.

### 3.1 Known stack and current work

-   Frontend: React + TypeScript + Vite.
-   Backend: Python + FastAPI.
-   Media tools: FFmpeg and FFprobe.
-   Transcription: `faster-whisper`, currently local CPU/int8 with VAD
    and word timestamps where available.
-   LLM candidate discovery: provider abstraction with local Ollama
    (`qwen2.5:7b`) and OpenAI adapter.
-   Planned persistence: Neon database and Cloudflare R2; neither is
    currently required for the local-first MVP.
-   Local development hardware: 16 GB RAM and NVIDIA RTX 4050 with 6 GB
    dedicated VRAM. Shared memory is not equivalent to dedicated VRAM;
    inference should be benchmarked and sequenced conservatively.

### 3.2 Current Phase 2 candidate discovery

-   Transcript is processed in multiple overlapping windows.
-   Current default chunk size is approximately 750 words, with 45
    seconds of overlap.
-   Candidate pool target is 10, but this is a target rather than a
    promise.
-   Hard candidate duration bounds are 10--60 seconds; preferred range
    15--45 seconds and target 30 seconds.
-   Candidate validation checks source bounds, duration, evidence
    grounding, and related rejection reasons.
-   Backend computes overall scores from eight dimensions and
    goal-specific weights; model-provided overall scores must not
    replace backend scoring.
-   IoU deduplication threshold is 0.50.
-   Local Ollama multi-window smoke test took approximately 6 minutes 35
    seconds on the current 10-minute test video. This is a measurement
    from one test, not a general performance guarantee.

### 3.3 Existing quality findings

A human reviewed seven generated candidate clips. The recurring defect
was poor editorial closure: - several clips began well but ended
mid-conversation; - one clip cut a word in half; - another opened after
audience laughter and ended as a new topic began; - one clip felt
comparatively complete; - the reviewer liked the idea of discovering
complete conversations first, then optional shorter moments within them.

These observations justify investigating boundary refinement and the
two-level workflow. They do not yet prove that every current candidate
is poor or that a specific algorithm will solve the problem. Preserve
the existing human evaluation document and update it with the review
observations; do not overwrite experiment artifacts.

------------------------------------------------------------------------

## 4. Core architecture principles

1.  **Clean master is the source of truth for further editing.** It is
    trimmed and, once supported, reframed, but has no captions or
    effects newly burned in by our renderer.
2.  **Final render is a derivative.** Captions, filters, overlays, and
    other presentation effects are applied to a clean master.
3.  **Long and short discovery are distinct workflows.** They can share
    infrastructure, but not blindly reuse the same discovery
    prompt/logic.
4.  **One hierarchy level only.** Short clips may have a long-clip
    parent; short clips never become parents of additional clips.
5.  **Artifacts are reusable contracts.** A long-clip folder should
    contain enough validated metadata and transcript information to be
    used as short-pipeline input.
6.  **Timeline coordinates must be explicit.** Store source-video
    timestamps and clip-local timestamps; do not infer one from the
    other without a recorded offset.
7.  **Models propose; application validates.** Models do not control
    file paths, write production files, bypass validators, or define
    final ranking scores.
8.  **No forced output count.** Zero short clips from a long clip is
    acceptable.
9.  **Experimental output is isolated.** Experiments can be flexible
    under `experimental_output/`; production paths are controlled by
    application code.
10. **Local-first, cloud-ready.** File IDs and metadata should be
    designed so R2 and Neon can be introduced without relying on
    filenames as identity.
11. **Quality gates precede optimization.** Measure usable/publishable
    clips and boundary quality before optimizing for speed or raw
    candidate counts.
12. **Approved product specs remain authoritative.** This architecture
    is a proposal and implementation guide, not permission to rewrite
    approved PRD/TechSpec content.

------------------------------------------------------------------------

## 5. Input ingestion and local storage

### 5.1 Input directory

Uploaded/imported videos are placed directly inside a date folder. Do
not create an additional folder per video.

``` text
input/
└── YYYY-MM-DD/
    ├── anne_hathaway_tonight_show.mp4
    ├── podcast_episode_42.mp4
    └── tutorial_part_1.mov
```

-   Date is the local ingestion date, formatted `YYYY-MM-DD`.
-   Filenames are normalized to lowercase `snake_case`, retaining the
    extension.
-   No spaces in stored input filenames.
-   Normalize unsafe/punctuation-heavy names safely; handle Unicode and
    empty normalized names deterministically.
-   Do not overwrite on filename collision. Use a deterministic
    collision suffix such as `_2`, `_3`, etc.
-   Preserve the original filename in metadata.
-   Do not use the filename as the permanent identity of a video.

### 5.2 Ingestion metadata

Create a small versioned metadata record for each input video, with
fields equivalent to:

-   `schema_version`
-   `video_id` (stable generated ID)
-   `original_filename`
-   `stored_filename`
-   `ingested_at` (timezone-aware timestamp)
-   `ingestion_date`
-   `file_size_bytes`
-   `media_type` / extension
-   `content_hash` where practical
-   `source_path` relative to the application-managed root
-   `probe_status` and basic media metadata when available

Exact field names should be reconciled with existing schemas by the
local agent. Avoid duplicating metadata structures without need.

### 5.3 Future R2/Neon compatibility

Local folders are the current storage mechanism, not the permanent
identity system. Keep stable IDs and relative/object keys separate from
absolute machine-specific paths. When R2 is introduced: - video and
artifact bytes can move to R2; - metadata can move to Neon; -
application services should resolve storage through a storage
abstraction rather than scattering filesystem paths throughout business
logic.

Do not implement R2 or Neon as part of the initial architecture-planning
task.

------------------------------------------------------------------------

## 6. Production output structure

### 6.1 Directory layout

Use a date folder, normalized source-video name, and a timestamped run
folder under the existing `outputs/` directory. The run timestamp is the **actual run creation time in
Asia/Kolkata (IST)**, formatted `HH_MM_SS`. It is not a source-video
timestamp.

``` text
outputs/
└── YYYY-MM-DD/
    └── anne_hathaway_tonight_show/
        └── HH_MM_SS__run_001/
            ├── manifest.json
            ├── run_metadata.json
            ├── long_clips/
            │   ├── clip_01/
            │   │   ├── clip_01.mp4
            │   │   ├── clip_01_final.mp4
            │   │   ├── transcript.json
            │   │   ├── metadata.json
            │   │   ├── captions.srt
            │   │   └── captions.ass
            │   └── clip_02/
            │       └── ...
            └── short_clips/
                ├── clip_01/
                │   ├── clip_01.mp4
                │   ├── clip_01_final.mp4
                │   ├── transcript.json
                │   ├── metadata.json
                │   ├── captions.srt
                │   └── captions.ass
                └── clip_02/
                    └── ...
```

`captions.srt` and `captions.ass` are optional/generated when
applicable. A clip's `clip_XX.mp4` is the clean master;
`clip_XX_final.mp4` is the rendered deliverable. During early stages, if
final rendering is unavailable or disabled, the final file may not
exist; metadata must state this clearly rather than copying/renaming the
clean file and pretending effects were applied.

### 6.2 Run-folder collision handling

Multiple runs may begin within the same second. The output manager must
avoid collisions without overwriting existing output. Use a
deterministic suffix such as `run_001`, `run_002` for repeated run
timestamps, or an equivalent unique run ID. The local agent should
inspect current run handling and recommend a consistent approach.

### 6.3 Production output ownership

Only the application's output manager/pipeline may create, rename,
replace, or delete production output files. LLMs and experiment scripts
must never choose production paths or write there directly. Write to a
temporary/staging location, validate successful completion, then
atomically publish the completed artifact where practical.
Failed/incomplete outputs should be marked in run metadata and must not
appear as completed deliverables.

### 6.4 Experimental output

Use a separate root such as:

``` text
experimental_output/
└── <experiment_id>/
    ├── request.json
    ├── response.json
    ├── notes.md
    └── generated_artifacts/
```

The exact experiment layout may be flexible. Experimental scripts may
write only inside this root unless explicitly authorized otherwise.
Existing smoke-test artifacts must not be moved, renamed, deleted, or
overwritten as part of planning.

------------------------------------------------------------------------

## 7. Clip identity, lineage, and timeline model

Every original video, long clip, and short clip must have a stable ID
independent of its folder name.

Recommended conceptual relationships:

-   Original video: `video_id`
-   Long clip: `clip_id`, `parent_video_id`
-   Short clip: `clip_id`, `parent_clip_id` (where the parent is a long
    clip)
-   Run: `run_id`
-   Render: `render_id` or a render-version record

### 7.1 Timeline fields

For every clip, preserve: - `source_start_seconds`: start relative to
the original source video. - `source_end_seconds`: end relative to the
original source video. - `local_start_seconds`: start relative to its
immediate parent video. - `local_end_seconds`: end relative to its
immediate parent video. - `duration_seconds`. - `parent_id` and
`parent_type`. - For short clips, the long parent's source offset must
be used to map short-local times back to the original source.

Example: if a long clip starts at source time 300.0 seconds and a short
begins 8.0 seconds into that long clip, then the short starts at source
time 308.0 seconds. If there are additional trims or edits, store the
actual mapping rather than assuming a simple offset.

Use a single documented convention for inclusive/exclusive boundaries
and timestamp precision. Avoid mixing `MM:SS`, floating-point seconds,
and frame indexes as untyped values. Store canonical times as seconds
and derive display strings as needed.

### 7.2 Transcript reuse

The original transcript is produced once for the original video. A long
clip's transcript is derived by selecting/intersecting original
transcript segments and word timings with the long interval, then
converting the selected timestamps to long-local coordinates while
preserving source coordinates where useful.

A short clip's transcript is derived from the parent long clip's
transcript in the same manner. Do not retranscribe by default when the
inherited transcript and word timings are valid. Retranscription can be
an explicit recovery option if data is missing or quality checks fail.

When a word crosses a boundary, the implementation must use a documented
policy: preserve only valid in-range word timing, avoid fabricating
text/timestamps, and flag uncertain boundary text for review where
needed.

------------------------------------------------------------------------

## 8. Long-clip pipeline

### 8.1 Purpose

Find coherent, complete conversation/story arcs in the original source
video. This is not merely a pass that selects isolated short viral
moments. Long clips are the parent assets from which optional shorts may
later be discovered.

### 8.2 Planned stages

1.  **Resolve input:** identify the selected source video and ingestion
    metadata.
2.  **Probe media:** use FFprobe to establish duration, streams, frame
    rate, resolution, audio information and other relevant media
    properties.
3.  **Extract audio:** use the existing FFmpeg approach and validated
    audio mapping.
4.  **Transcribe:** use the existing `faster-whisper` pipeline, VAD, and
    word timestamps where available.
5.  **Discover long-clip candidates:** use chunked transcript processing
    so the whole source is covered without forcing one oversized LLM
    request. Prompt/strategy should prioritize coherent conversations,
    complete arcs, useful context, and clean endpoints.
6.  **Validate candidates:** enforce source bounds, duration limits,
    evidence grounding, valid timestamps, and other existing hard
    checks. Long-clip discovery uses dedicated duration settings:
    minimum 30 seconds, target 90 seconds, and maximum 180 seconds.
    (Do not increase the long-clip maximum to 300 seconds without
    further evaluation). These are discovery/validation settings, not
    forced output durations.
7.  **Rank and deduplicate:** retain backend-owned scoring and versioned
    goal weights. Deduplication must not erase useful alternative
    boundaries without recording why.
8.  **Refine boundaries:** plan a controlled experiment using genuine
    Whisper word timings and configurable outward boundary snapping,
    initially testing a 1.0–1.5-second silence/context cushion where
    appropriate. Do not treat word-timing snapping as a complete
    solution to editorial closure; evaluate word integrity (avoiding
    mid-word cuts) and conversational completeness (capturing complete
    arcs and room reactions) separately. Boundary refinements must
    strictly respect source bounds and the configured 180-second hard
    limit, without applying a fixed extension blindly. Compare results
    against existing human-reviewed examples before making the approach
    the default.
9.  **Human review / quality gate:** support candidate review and record
    accepted/rejected decisions and rejection reasons.
10. **Visual analysis (future):** analyze the original video for visual
    context, subject/speaker activity, scene changes and framing
    evidence. This is a planned extension, not part of the current Phase
    2 implementation.
11. **Create clean long master:** cut the selected source interval and
    apply the approved framing/reframing operation. Once smart reframing
    exists, the clean master is the actual reframed render. It contains
    no captions/effects newly burned in by our renderer.
12. **Derive transcript:** write the long-local transcript and timings
    from the original transcript.
13. **Render final version:** optionally apply a selected caption preset
    and effects to produce `clip_XX_final.mp4`.
14. **Publish artifacts:** write metadata, transcript, subtitle files as
    applicable, and update the run manifest.

### 8.3 Current versus future behavior

Current implementation may use centered 9:16 cropping or another
existing baseline. Do not claim person-focused/smart reframing is
implemented unless repository inspection confirms it. Architecture
should define a framing stage that can initially use the existing
implementation and later accept visual-analysis decisions.

### 8.4 Long-clip quality criteria

A valid long clip should: - start with enough context to understand the
exchange; - contain a coherent conversation/story arc rather than
unrelated fragments; - end at a natural or acceptably satisfying
point; - avoid mid-word cuts; - stay within configured hard duration
bounds (minimum 30.0s, maximum 180.0s, with a target of 90.0s); - have grounded transcript evidence and traceable timestamps; -
remain visually usable after framing.

The system should not force every clip to reach a fixed duration or produce a
fixed number of clips. A shorter complete arc (e.g. 35–50 seconds) is preferable to an
unnecessarily padded clip, provided it captures the complete context.

------------------------------------------------------------------------

## 9. Short-clip pipeline

### 9.1 Purpose

Find zero or more short standalone moments within a single accepted long
clip. Short-clip discovery is a distinct editorial task with its own
prompt, candidate criteria, boundary handling and evaluation.
Short clips use dedicated duration settings: minimum 10.0 seconds, target 30.0 seconds, and maximum 60.0 seconds.

### 9.2 Input contract

The short pipeline accepts a **specific long-clip artifact folder**, not
the original video's entire folder. It should resolve: - clean long
master video (`clip_XX.mp4`); - `transcript.json` with local word
timings and source mapping; - `metadata.json` with parent/source
identity and time intervals; - existing analysis artifacts, when
available; - caption/render metadata only as context, not as the default
video input.

The folder must be validated before processing. Missing required files
should produce actionable errors. It must not guess the input video
based on arbitrary directory ordering.

### 9.3 Planned stages

1.  Resolve and validate the selected long-clip folder.
2.  Load its clean master, transcript, metadata and applicable analysis
    artifacts.
3.  Discover short moments using short-focused criteria: clear hook,
    understandable context, coherent small exchange or idea,
    punchline/insight/emotional beat, and a satisfying ending.
4.  Allow zero or more candidates. Do not pad the result to reach a
    target count.
5.  Validate source/parent-local time bounds and evidence against the
    long transcript, enforcing short-clip hard bounds (10.0s – 60.0s, target 30.0s).
6.  Rank and deduplicate using backend-owned scoring/validation. Keep
    short discovery logic separate from long discovery.
7.  Refine short boundaries, including word integrity (using genuine Whisper word timings), speech turn
    boundaries and acceptable closure. Avoid mid-word truncation.
8.  Visual analysis (future): analyze the long clip rather than
    re-analyzing the entire original video. Reuse compatible parent
    analysis results and perform targeted analysis only where justified.
9.  Create the short clean master from the **clean, reframed long
    master**, without our captions/effects baked in.
10. Derive the short transcript from the long transcript, preserving
    source and local timestamps.
11. Apply selected caption preset/effects to create `clip_XX_final.mp4`.
12. Publish metadata, optional subtitle files, and manifest parent-child
    linkage.

### 9.4 Short-clip quality criteria

A good short need not contain an entire conversation, but should be
understandable and meaningful on its own. It should not be vague,
contextless, or merely provocative without payoff. It should have a
strong opening and a clean endpoint, and must not routinely cut off a
word or the key conclusion. Some long clips legitimately have no good
standalone shorts.

### 9.5 No recursive subclipping

Short clips never become parents of further short clips. The only
supported tree is:

`original video → long clip → short clip`

The code should enforce this via parent-type validation or an equivalent
domain rule, not only via CLI convention.

------------------------------------------------------------------------

## 10. Future video-analysis design

Video analysis is planned, not to be implemented during the current
architecture-document task.

### 10.1 Long clips

Analyze the original video as part of the long-clip workflow to provide
visual evidence for candidate quality, scene/context understanding and
person-focused framing. Analysis may include selected frames,
active-speaker/person presence, scene boundaries, and framing
suggestions. Choose the methods only after benchmarking quality,
latency, memory/VRAM use and cost where applicable.

### 10.2 Short clips

Analyze the clean long-clip master for short discovery and refinement.
Reuse parent analysis where valid, with timestamp conversion and
provenance. Avoid rerunning a full-source analysis for each child clip.

### 10.3 Analysis artifact contract

Keep analysis outputs as versioned structured artifacts with: -
model/method and version; - source video/clip ID; - timestamp coordinate
system; - timestamped observations and confidence where available; -
evidence/provenance; - generation status and errors; - compatibility
information for reuse.

Do not store only unstructured prose if downstream stages need precise
timestamp mapping.

### 10.4 Avoid overclaiming reuse

Not all analysis can be reused without adjustment. A source-video scene
timestamp, person track, or framing decision may need coordinate
transformation or revalidation after trimming/reframing. Preserve
original coordinates and mapping information.

------------------------------------------------------------------------

## 11. Future audio analysis and evidence fusion

Audio-event analysis is a future extension and must not be implemented
as part of the current architecture-planning task or mixed into the
current Phase 2 changes.

Potential audio evidence includes laughter, applause, cheering, dramatic
pauses, music changes, impacts, sound effects, and other nonverbal
events. An audio-analysis result should contain timestamped event type,
confidence, supporting acoustic evidence, rationale, suggested context
window, related transcript candidate IDs where applicable, and whether
it is an independent audio-only candidate or supporting evidence.

Fusion behavior: 1. If audio and transcript identify the same moment,
merge their evidence into one candidate rather than duplicating it. 2.
If audio supports a transcript candidate, use it as additional ranking
or boundary evidence. 3. If audio finds an independently meaningful
nonverbal moment, allow an audio-only candidate. 4. Match evidence by
time overlap/proximity, event type and context; do not merge everything
nearby. 5. Track candidate quality, evidence strength and confidence
separately. Do not blindly add raw scores from different systems. 6.
Missing evidence from one modality is not automatically negative
evidence. 7. Avoid double-counting correlated detectors of the same
event. 8. Benchmark lightweight audio models/features on available
hardware before selecting a solution.

------------------------------------------------------------------------

## 12. Captioning, final renders, and effects

### 12.1 Clean master versus final deliverable

For every clip: - `clip_XX.mp4` = clean master, trimmed and reframed as
applicable, with no captions/effects newly burned in by our renderer. -
`clip_XX_final.mp4` = final rendered deliverable using the selected
caption preset and enabled effects.

"Clean" does not mean the original source has no captions embedded in
its pixels. It means our pipeline has not added its own caption/effect
layer to the master.

The short pipeline defaults to `clip_XX.mp4` from its long parent, never
the parent's final render. This prevents inherited captions/filters from
being burned into child videos and allows each short to choose its own
style.

### 12.2 Caption presets

Plan for a registry/configuration of named caption presets (initially
one default preset is sufficient). A preset should describe
styling/layout choices, not alter the transcript's meaning. Record: -
preset ID and version; - font/style/position/animation options
supported; - subtitle source and timing; - render settings.

Do not implement four or five styles before the clean-master
architecture and a single reliable final render are working. Multiple
render variants should be represented explicitly in metadata rather than
overwriting the only final file.

### 12.3 Effects and versioning

Filters and other effects should be composable render settings. The
clean master remains unchanged. If multiple variants are later
supported, use a predictable variant naming convention or render
manifest, e.g. default final, alternate style, filtered variant. Never
silently overwrite an existing final render without an explicit
replacement/version policy.

------------------------------------------------------------------------

## 13. CLI and orchestration

The exact CLI should be reconciled with existing commands by the local
agent. Intended user-facing capability:

``` bash
# Full end-to-end: original video -> long clips -> optional shorts (automated by default)
python -m app.cli.main --pipeline full --input <video-file>

# Full end-to-end with review gate: pauses after long clips for user approval
python -m app.cli.main --pipeline full --input <video-file> --review-gate

# Resume full pipeline after long-clip approval
python -m app.cli.main --pipeline resume --run-dir <run-folder>

# Long-clip pipeline only
python -m app.cli.main --pipeline long --input <video-file>

# Short-clip pipeline only, from a particular long-clip folder
python -m app.cli.main --pipeline short --input <long-clip-folder>
```

These are illustrative commands, not a requirement to replace existing
CLI syntax without migration planning.

### 13.1 Review Gate Design
- **Automated Default**: Full-pipeline execution defaults to running straight through: ingesting the source, discovering/rendering long clips, and immediately executing short discovery on each valid long clip.
- **Optional `--review-gate`**: When enabled, the full pipeline halts after long-clip clean masters and metadata are published. The run manifest status transitions to `awaiting_review`.
- **Review Workflow**: The user inspects the generated long clips in `outputs/.../long_clips/` and approves or rejects clips (via CLI review flag or review API/UI).
- **Zero-Duplication Orchestration Architecture**:
  - `run_long_pipeline()` encapsulates long-clip ingestion, transcription, discovery, clean-master rendering, and transcript slicing.
  - `run_short_pipeline()` encapsulates short-clip package validation, short discovery, and cutting shorts from the long clean master.
  - `run_full_pipeline(source, review_gate=False)` chains `run_long_pipeline()` and `run_short_pipeline()` cleanly:
    1. Runs `run_long_pipeline()`.
    2. If `review_gate=True`, logs review instructions, records status in `manifest.json`, and stops gracefully.
    3. If `review_gate=False`, loops through accepted long clips and invokes `run_short_pipeline()` on each.
  - `resume_full_pipeline(run_dir)` reads the existing `manifest.json`, filters for approved long clips, and calls `run_short_pipeline()` on them without re-executing long-clip generation.

### 13.2 Requirements
- Full pipeline invokes the same long and short orchestration services as standalone commands.
- Long-only must not automatically generate shorts unless an explicit option requests it.
- Short-only must operate on one selected long-clip folder and must not rediscover long clips from the original video.
- Commands should support configuration for goal, duration constraints, caption preset, effects, output root, and whether final rendering is enabled, as appropriate.
- Validate incompatible flags and inputs early.
- Use clear exit codes and actionable error messages.
- Support dry-run/plan mode if feasible.
- Do not make the CLI responsible for duplicating business logic.

------------------------------------------------------------------------

## 14. Manifest and metadata contracts

### 14.1 Run manifest

`manifest.json` is the run-level index. It should include: - schema
version; - run ID, run creation timestamp and timezone; - input video
ID, original/stored filename and source metadata; - selected pipeline
mode; - configuration snapshot or reference; - model/provider/version
information; - run status and stage status; - long clips and short clips
with IDs, relative artifact paths, source/local intervals, duration,
score breakdown, validation/review status; - parent-child
relationships; - render variants and caption preset IDs; - errors,
rejection counts/reasons, and relevant metrics; - creation/update
timestamps.

Do not make the manifest the only copy of essential clip metadata; each
clip should also have its own `metadata.json` so a long clip can be
processed independently.

### 14.2 Clip metadata

Clip metadata should capture: - schema version, clip ID and clip type; -
parent ID/type and original video ID; - source and parent-local time
intervals; - duration and media properties; - transcript artifact path
and timing coordinate conventions; - candidate evidence, score
breakdown, validation/rejection information and human review where
applicable; - clean-master path/status; - render variants/status and
caption/effect configuration; - relevant model/pipeline versions; -
creation timestamp and errors.

### 14.3 Versioning and migrations

Version metadata schemas. Readers should reject unsupported schemas with
a clear error or apply explicit migrations. Avoid silently guessing
missing fields. The local agent should identify current schemas and
propose the smallest compatible evolution.

------------------------------------------------------------------------

## 15. Output lifecycle, failures, and re-runs

-   Use run IDs to isolate runs; never overwrite a prior run by default.
-   Write intermediate artifacts to staging/temp locations and publish
    completed outputs atomically where possible.
-   Mark stages as pending/running/succeeded/failed/skipped.
-   If a stage fails, retain diagnostic metadata and clearly identify
    incomplete artifacts.
-   Allow rerunning a failed stage when its dependencies are still
    valid; don't rerun expensive transcription/analysis unnecessarily.
-   Track cache keys or artifact fingerprints based on input content,
    configuration, and model/version where useful.
-   Do not assume a cached artifact is valid if its source, schema, or
    model configuration changed.
-   Keep logs useful but avoid unnecessarily logging full private
    transcripts or secrets.
-   Do not move/rename/delete existing smoke-test artifacts during
    architecture planning.
-   Define cleanup policies later; do not automatically delete source or
    intermediate files in the MVP.

------------------------------------------------------------------------

## 16. Quality evaluation and metrics

Candidate count alone is not the success metric. Measure the usefulness
and editorial quality of outputs.

### Long-clip metrics

-   candidate acceptance rate;
-   human-usable rate;
-   publishable rate;
-   natural-start and natural-ending ratings;
-   mid-word cut rate;
-   context/completeness rating;
-   framing usability;
-   duplicate rate;
-   time to generate and failure rate.

### Short-clip metrics

-   standalone-understandability;
-   hook effectiveness;
-   ending/punchline completeness;
-   contextless/vague rate;
-   publishable rate;
-   mid-word cut rate;
-   parent-child traceability;
-   number of useful shorts per accepted long clip (descriptive, not a
    quota).

### Pipeline metrics

-   transcription latency;
-   LLM latency per window and total;
-   video/audio analysis latency when added;
-   render latency;
-   memory/VRAM use;
-   failed stage counts and retry rate;
-   proportion of work reused on reruns.

The existing aspiration of roughly 50--60% usable candidates is an
experimental goal, not a guarantee. Keep human evaluation separate from
model scores. Preserve rejection reasons and compare changes against a
fixed evaluation set before broad rollout.

------------------------------------------------------------------------

## 17. Testing strategy and acceptance criteria

### 17.1 Unit tests

-   Filename normalization, extension preservation and collision
    handling.
-   Input metadata creation and path safety.
-   Timeline conversions between source, long-local and short-local
    coordinates.
-   Transcript slicing with word timestamps and boundary-crossing words.
-   Parent-type rules and prevention of recursive short parents.
-   Metadata schema validation and version handling.
-   Manifest updates and status transitions.
-   Output path creation, run collision handling and prevention of
    unintended overwrites.
-   Clean master versus final render path selection.
-   Caption preset configuration and render variant naming.
-   Candidate validation, duration bounds, evidence grounding and dedup
    behavior.

### 17.2 Integration tests

-   Input video → transcription → long candidate discovery → validation
    → clean long master.
-   Existing long-clip folder → short candidate discovery → clean short
    master.
-   Full orchestration uses the same services as standalone long and
    short modes.
-   Transcript reuse works without a second transcription call when
    valid artifacts exist.
-   Short source defaults to the parent's clean master, not final
    render.
-   Failure in one long clip's short pipeline does not corrupt other
    clips or the parent master.
-   Manifest and clip metadata correctly represent partial failure and
    reruns.
-   Experimental scripts cannot accidentally publish to production
    output.

### 17.3 End-to-end acceptance

1.  A video with spaces in its filename is ingested into the date folder
    under a normalized snake_case name without overwrite risk.
2.  Long-only mode creates a run folder with long-clip artifacts and no
    short clips unless explicitly requested.
3.  Every accepted long clip has a clean master and a valid, reusable
    transcript/metadata contract.
4.  Short-only mode accepts one long-clip folder and produces zero or
    more shorts without requiring the original full video as its
    discovery input.
5.  Short timestamps map correctly to the original source.
6.  Full mode produces the same logical results as running long mode
    followed by short mode with the same configuration and artifacts.
7.  Final render is separate from clean master; changing
    captions/effects does not mutate the clean master.
8.  Every short has a valid long-clip parent; no short has a short
    parent.
9.  Manifest accurately lists files, relationships, configurations and
    statuses.
10. Existing Phase 2 validation/scoring regressions remain covered.
11. No approved PRD/TechSpec rewrite or unrelated feature implementation
    occurs without approval.

------------------------------------------------------------------------

## 18. Implementation roadmap and work tracking

This section is the source of truth for implementation progress.
Statuses below begin as **Not started** and must only be changed after
evidence (code, tests, or reviewed deliverables) confirms completion.

Suggested statuses: - `Not started` - `In progress` - `Blocked` -
`Implemented — needs verification` - `Verified` - `Deferred` -
`Cancelled`

A stage is not `Verified` merely because code was written; its
acceptance criteria and relevant tests must pass.

### Phase 0 --- Architecture alignment and baseline

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  ID                Work item                             Status           Completion evidence
  ----------------- ------------------------------------- ---------------- ---------------------------------------------------------------------------
  A0.1              Compare this document with the        Verified         `docs/ARCHITECTURE_REVIEW_AND_IMPLEMENTATION_PLAN.md` Section 2 & 3
                    actual repository                                      

  A0.2              Identify conflicts with approved PRD  Verified         `docs/ARCHITECTURE_REVIEW_AND_IMPLEMENTATION_PLAN.md` Section 4
                    v0.2.1 / TechSpec v0.2.1                               

  A0.3              Map current discovery, validation,    Verified         `docs/ARCHITECTURE_REVIEW_AND_IMPLEMENTATION_PLAN.md` Section 2
                    rendering, transcript, CLI and                         
                    output code                                            

  A0.4              Confirm human evaluation report       Verified         `docs/evaluations/PHASE2_MULTIWINDOW_QUALITY_EVALUATION.md`
                    includes all seven clip reviews                        updated with 7-clip findings & experiment evidence

  A0.5              Approve architecture amendments,      In progress      Decisions 1–5 recorded; pending final plan review
                    duration settings, and stage order                     
  ----------------------------------------------------------------------------------------------------------------------------------------------------

### Phase 1 --- Input ingestion and artifact foundations

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  ID                Work item                             Status           Completion evidence
  ----------------- ------------------------------------- ---------------- ---------------------------------------------------------------------------
  A1.1              Define stable IDs and versioned       Verified         Schema `app.domain.ingestion.models.IngestionMetadata` and unit tests in
                    metadata contracts                                     `backend/tests/unit/test_ingestion_storage.py`

  A1.2              Implement date-based input folders    Verified         `normalize_filename` and `ingest_source_video` in
                    and snake_case normalization                           `backend/app/services/storage/ingestion.py`

  A1.3              Add duplicate-name collision          Verified         `resolve_unique_input_path` deterministic suffixing (`_2`, `_3`); tested
                    protection                                             in `backend/tests/unit/test_ingestion_storage.py`

  A1.4              Define source/local timestamp         Verified         `ClipTimeline`, `source_to_parent_local`, `parent_local_to_source`, and
                    conventions and conversion helpers                     nested conversions in `backend/app/domain/timeline/models.py`; hardened against non-finite values (F-H2)

  A1.5              Define output manager, run IDs,       Verified         `OutputManager` in `backend/app/services/storage/output_manager.py` with
                    staging and collision policy                           same-second run collision safety and atomic staging (.rendering.mp4)

  A1.6              Define manifest and clip metadata     Verified         `RunManifest` and `ClipMetadata` in `backend/app/domain/manifest/models.py`;
                    schemas                                                hardened with lineage validator (F-M2) and tested in `test_manifest_models.py`
  ----------------------------------------------------------------------------------------------------------------------------------------------------

### Phase 2 --- Long-clip quality and reusable clean masters

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  ID                Work item                             Status           Completion evidence
  ----------------- ------------------------------------- ---------------- ---------------------------------------------------------------------------
  A2.1              Evaluate existing Phase 2 candidates  Verified         Human evaluation synthesized in
                    and boundary failures                                  `docs/evaluations/PHASE2_MULTIWINDOW_QUALITY_EVALUATION.md`

  A2.2              Propose and benchmark boundary        Verified         Controlled experiment using genuine Whisper word timings in
                    refinement experiment (word snapping                   `backend/app/services/candidates/boundaries.py` benchmarked on test moments;
                    with 1.0–1.5s cushion)                                 detailed in `docs/evaluations/PHASE2_MULTIWINDOW_QUALITY_EVALUATION.md`

  A2.3              Implement approved boundary           Verified         `LONG_CLIP_SYSTEM_PROMPT` in `backend/app/services/llm/prompts.py`,
                    improvements and long-clip bounds                      `GenerationSettings.for_long_clips()` in `candidates.py` (min 30s,
                    (30s–180s)                                             target 90s, max 180s), and unit tests in `test_long_clip_pipeline.py`

  A2.4              Render clean long masters             Verified         `render_long_clip_package` in `backend/app/services/rendering/long_clip_renderer.py`
                    (`clip_XX.mp4`) to output contract                     producing clean master (`burn_subtitles=False`, 9:16 vertical crop)

  A2.5              Derive long-local transcript and      Verified         `slice_transcript_for_long_clip` in `backend/app/services/transcription/slicing.py`
                    word timings                                           with preserved genuine Whisper word timings and re-zeroed local coordinates

  A2.6              Add per-clip metadata and run         Verified         Atomic writing of `metadata.json` with source/local timeline and
                    manifest updates                                       `ManifestLongClipItem` generation in `render_long_clip_package`

  A2.7              Support final long-clip render        Verified         Dual-render support in `render_long_clip_package` generating derivative
                    as a derivative                                        `clip_XX_final.mp4` (`burn_subtitles=True`) while preserving clean master
  ----------------------------------------------------------------------------------------------------------------------------------------------------

### Phase 3 --- Standalone short-clip pipeline

  ----------------------------------------------------------------------------------------------------------------------------------------------------
  ID                Work item                             Status           Completion evidence
  ----------------- ------------------------------------- ---------------- ---------------------------------------------------------------------------
  A3.1              Define and validate long-clip folder  Verified         `validate_long_master_package` in
                    input contract                                         `backend/app/services/candidates/short_package.py` and unit tests

  A3.2              Implement short-focused discovery     Verified         `run_short_clip_pipeline` in `short_pipeline.py` using short-mode
                    strategy                                               settings (10-60s) and short-focused prompt (`SYSTEM_PROMPT`)

  A3.3              Implement short validation,           Verified         Local candidate validation, scoring, deduplication, and Whisper word-timing
                    ranking and boundary refinement                        refinement in `run_short_clip_pipeline`

  A3.4              Reuse long transcript and analysis    Verified         Sliced long transcript reused directly without retranscription; word timings
                    artifacts                                              preserved and re-zeroed locally via `slice_transcript_for_short_clip`

  A3.5              Render clean short masters from       Verified         `render_short_clip_package` in `short_clip_renderer.py` rendering
                    clean long masters                                     from clean master (`burn_subtitles=False`, 9:16 vertical format)

  A3.6              Link each short to its long parent    Verified         `ClipMetadata` and `RunManifest` validation enforcing `parent_type='long_clip'`,
                    and original source                                    `parent_id`, and explicit source/local timelines

  A3.7              Permit zero shorts and prevent        Verified         Tests in `test_short_clip_pipeline.py` confirming zero shorts is valid and
                    recursive subclipping                                  recursive short-of-short discovery is strictly rejected
  ----------------------------------------------------------------------------------------------------------------------------------------------------

### Phase 4 --- Orchestration and CLI

  -------------------------------------------------------------------------
  ID                Work item         Initial status    Completion evidence
  ----------------- ----------------- ----------------- -------------------
  A4.1              Add/align         Not started       CLI integration
                    long-only CLI                       tests
                    mode                                

  A4.2              Add/align         Not started       CLI integration
                    short-only CLI                      tests
                    mode                                

  A4.3              Add full          Not started       Full pipeline test
                    end-to-end                          
                    orchestration                       

  A4.4              Ensure full mode  Not started       Architecture/code
                    reuses standalone                   review
                    services                            

  A4.5              Add stage status, Not started       Failure/retry
                    actionable errors                   integration tests
                    and safe reruns                     
  -------------------------------------------------------------------------

### Phase 5 --- Caption presets and render variants

  -----------------------------------------------------------------------
  ID                Work item         Initial status    Completion
                                                        evidence
  ----------------- ----------------- ----------------- -----------------
  A5.1              Formalize clean   Not started       Tests verify no
                    master vs final                     master mutation
                    render contract                     

  A5.2              Implement one     Not started       Render quality
                    reliable default                    check
                    caption preset                      

  A5.3              Store render      Not started       Metadata fixtures
                    settings and                        and tests
                    preset versions                     

  A5.4              Add additional    Deferred          Only after
                    caption styles                      single-style
                                                        pipeline is
                                                        stable

  A5.5              Add configurable  Deferred          Separate render
                    filters/effects                     variants; clean
                                                        source unchanged
  -----------------------------------------------------------------------

### Phase 6 --- Video analysis and smart framing (future)

  ------------------------------------------------------------------------------
  ID                Work item         Initial status    Completion evidence
  ----------------- ----------------- ----------------- ------------------------
  A6.1              Benchmark         Deferred          Quality/latency/memory
                    candidate                           report
                    visual-analysis                     
                    methods                             

  A6.2              Define versioned  Deferred          Approved schema
                    visual-analysis                     
                    artifacts                           

  A6.3              Use               Deferred          Evaluation proves useful
                    original-video                      improvement
                    analysis in long                    
                    pipeline                            

  A6.4              Produce actual    Deferred          Human framing review
                    person-focused                      
                    clean long                          
                    masters                             

  A6.5              Reuse/map         Deferred          Timeline and reuse tests
                    analysis in short                   
                    pipeline                            
  ------------------------------------------------------------------------------

### Phase 7 --- Audio analysis and multimodal evidence fusion (future)

  ----------------------------------------------------------------------------
  ID                Work item         Initial status    Completion evidence
  ----------------- ----------------- ----------------- ----------------------
  A7.1              Benchmark local   Deferred          Quality/latency/VRAM
                    audio-event                         report
                    analysis options                    

  A7.2              Define            Deferred          Approved schema
                    timestamped                         
                    audio-event                         
                    artifacts                           

  A7.3              Fuse audio and    Deferred          Fixed-set evaluation
                    transcript                          and fusion tests
                    evidence without                    
                    duplication                         

  A7.4              Support           Deferred          Human-reviewed
                    independent                         examples
                    audio-only                          
                    candidates where                    
                    justified                           
  ----------------------------------------------------------------------------

### Phase 8 --- Cloud-ready storage and production hardening (future)

  ---------------------------------------------------------------------------
  ID                Work item         Initial status    Completion evidence
  ----------------- ----------------- ----------------- ---------------------
  A8.1              Define storage    Deferred          Interface and local
                    abstraction for                     implementation tests
                    local filesystem                    
                    and R2                              

  A8.2              Move metadata     Deferred          Migration and
                    persistence to                      recovery plan
                    Neon when                           
                    approved                            

  A8.3              Add R2 object     Deferred          Integration tests
                    storage and                         
                    upload lifecycle                    

  A8.4              Add cleanup,      Deferred          Security/operations
                    quotas, access                      review
                    control and                         
                    operational                         
                    monitoring                          
  ---------------------------------------------------------------------------

------------------------------------------------------------------------

## 19. Dependencies and suggested delivery order

Recommended sequence:

1.  Complete Phase 0 repository comparison and approve this
    architecture.
2.  Preserve and finish current candidate quality evaluation; decide the
    smallest boundary-quality experiment.
3.  Establish the artifact contracts and output manager before multiple
    pipeline stages write files.
4.  Implement long-clip clean master + transcript/metadata contract.
5.  Implement the standalone short pipeline against that contract.
6.  Add orchestration and CLI modes.
7.  Add one final-render/caption path, then additional styles/effects.
8.  Benchmark and add video analysis.
9.  Benchmark and add audio analysis/fusion.
10. Introduce R2/Neon when the local workflow and artifact contracts are
    stable.

The agent may recommend changing this sequence if the repository has
hard dependencies, but it must explain why and identify which stages can
be safely isolated.

------------------------------------------------------------------------

## 20. Risks and design questions to resolve during repository review

1.  **Current output assumptions:** existing code may assume one flat
    candidate list or fixed output paths.
2.  **Boundary refinement:** better word-level boundaries do not
    automatically guarantee editorial closure; evaluation is needed.
3.  **Transcript timing drift:** converting between source and
    clip-local time can introduce off-by-offset errors if not
    standardized.
4.  **Reframing reuse:** visual-analysis results are reusable only if
    coordinate/timestamp provenance is preserved and the clean master is
    actually reframed.
5.  **Captioned parent input:** using a final render as the child source
    can bake captions/effects into shorts; clean master must be the
    default.
6.  **Runtime:** a second discovery pass may increase total time.
    Benchmark before deciding batch/concurrency strategies; avoid
    exhausting 6 GB VRAM by running large local inference jobs
    concurrently.
7.  **Model inconsistency:** LLM output can vary. Keep fixed evaluation
    inputs, store configuration/model versions, and measure human
    usefulness.
8.  **Output collisions:** same-second runs and duplicate input names
    must never overwrite existing data.
9.  **Schema drift:** local folder contracts must be versioned to allow
    future R2/Neon migration.
10. **Overbuilding:** do not implement video/audio analysis, multiple
    caption styles, filters, cloud storage, or a large UI redesign
    before the base hierarchy works.
11. **Specification drift:** keep approved PRD/TechSpec unchanged unless
    explicit approval is given.
12. **Experimental artifact safety:** existing smoke-test outputs are
    evidence and must not be moved or overwritten during investigation.

------------------------------------------------------------------------

## 21. Instructions for the local coding agent

When this document is handed to the agent:

1.  Read this document fully.
2.  Inspect the actual repository and current approved PRD/TechSpec.
3.  Treat this document as the proposed target architecture, not proof
    that features are already implemented.
4.  Produce a repository-grounded review that maps each relevant
    requirement to existing modules/files and identifies gaps,
    conflicts, unknowns, and dependencies.
5.  Update the existing human candidate-evaluation document with the
    user's review of all seven clips if that update has not already been
    completed.
6.  Recommend precise amendments to this architecture document where
    repository facts require them. Keep product decisions separate from
    implementation facts.
7.  Create a staged implementation plan with small tasks, dependencies,
    acceptance criteria, tests, and rollback considerations.
8.  Populate the work tracker only with evidence-backed statuses. Do not
    mark work implemented/verified merely because a plan exists.
9.  Do not modify production code, prompts, configuration, schemas,
    approved PRD/TechSpec, or generated smoke artifacts during this
    review unless separately authorized.
10. Do not rerun expensive model inference or move/rename/delete
    artifacts as part of this review.
11. Do not implement audio analysis, video analysis, smart reframing,
    additional caption styles, filters, R2, or Neon as part of this
    review.
12. Return the report paths, key repository findings, architecture
    conflicts, recommended implementation order, and any decisions
    needed from the product owner.

------------------------------------------------------------------------

## 22. Decision log

The following decisions have been agreed in product discussion and repository review:

-   [x] Product name remains undecided; call it AI Video Clipper for
    now.
-   [x] AutoShorts is a separate reference application, not the name of
    this product.
-   [x] Local-first input/output now; R2 and Neon are future
    integrations.
-   [x] Input folders use `input/YYYY-MM-DD/` with videos directly
    inside.
-   [x] Ingested filenames use lowercase `snake_case`, preserving
    extension.
-   [x] Input name collisions must never overwrite existing files; use deterministic suffixing (`_2`, `_3`).
-   [x] Output layout uses existing `outputs/` root (retained for backward compatibility) → date → normalized video name → IST timestamped run folder (`outputs/YYYY-MM-DD/<video_name>/HH_MM_SS__run_001/`).
-   [x] Individual clip folders use `clip_01/`, `clip_02/`, etc.,
    without redundant per-clip timestamps.
-   [x] `clip_XX.mp4` is the clean master; `clip_XX_final.mp4` is the
    rendered deliverable.
-   [x] The clean master has no captions/effects newly burned in by our
    renderer.
-   [x] Short clips are cut from the clean, reframed long master, not
    the parent's final render.
-   [x] Long and short discovery are distinct workflows with shared
    utilities.
-   [x] Short pipeline accepts a specific long-clip folder as input.
-   [x] Full pipeline orchestrates the same standalone workflow
    services.
-   [x] Hierarchy is exactly original → long → short; no recursive
    short-of-short processing.
-   [x] Transcript and valid word timings are reused by deriving
    parent/child-local timelines.
-   [x] Long-clip duration bounds: minimum 30 seconds, target 90 seconds, maximum 180 seconds. (Do not increase to 300 seconds without further evaluation).
-   [x] Short-clip duration bounds: minimum 10 seconds, target 30 seconds, maximum 60 seconds.
-   [x] Full-pipeline execution defaults to fully automated end-to-end; an optional `--review-gate` flag pauses after long-clip clean masters are generated for user approval before short discovery.
-   [x] Boundary refinement experiment will use genuine Whisper word timings and configurable outward boundary snapping (initially testing a 1.0–1.5s cushion), evaluating word integrity and conversational completeness separately against the fixed human-reviewed test set before making default.
-   [x] Stage 1 scope is strictly limited to input ingestion, filename normalization, stable IDs, metadata/timeline contracts, output management, collision safety, and manifest foundations; discovery and boundary changes are deferred to Stage 2.
-   [x] Video analysis is planned for later: original video for long
    discovery, long master for short discovery.
-   [x] Audio analysis and transcript/audio fusion are planned for
    later, not part of current implementation.
-   [x] Production output is owned by the application output manager;
    experiments stay under `experimental_output/`.
-   [x] No fixed number of clips is guaranteed; zero shorts is valid.
-   [x] Do not rewrite approved PRD/TechSpec without explicit approval.
-   [x] Current candidate-quality evaluation completed and synthesized in `PHASE2_MULTIWINDOW_QUALITY_EVALUATION.md`.

------------------------------------------------------------------------

## 23. Open decisions for implementation

The following implementation-level decisions remain to be finalized during Stage 1 technical delivery:

-   Exact Pydantic schema field names for `ingestion_metadata.json` and `manifest.json`.
-   Whether run folder names use only `HH_MM_SS__run_NNN` or append a stable short run ID.
-   Exact backward-compatibility wrapper strategy for legacy CLI scripts (`process_local.py`, `discover_candidates.py`, `render_clips.py`).
-   Detailed format for recording reviewer status transitions in `manifest.json` (`pending`, `awaiting_review`, `approved`, `rejected`).
-   Which minimal UI changes (if any) are needed versus CLI-only verification during Stages 1–4.
-   Which future video-analysis artifacts can be reused after
    trimming/reframing and which need revalidation (staged for Phase 6).
