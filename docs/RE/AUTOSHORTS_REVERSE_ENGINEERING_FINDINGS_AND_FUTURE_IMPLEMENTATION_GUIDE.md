# AutoShorts Reverse-Engineering Findings and Future Implementation Guide

**Purpose:** Preserve the findings from the AutoShorts source-code
investigation so future development can refer to them without repeating
the reverse-engineering exercise.

**Status:** Research findings and recommendations, not an implementation
mandate.

**Reference application:** AutoShorts 0.1.3\
**Inspected Git revision:** `5ae8dd388b190222e18ea63b8823616fbdf2a4a9`\
**Reference repository:** `C:\Lakshya\AI\autoshorts`\
**Primary report:**
`C:\Lakshya\AI\autoshorts\docs\RE\AUTOSHORTS_FINAL_VIDEO_PRODUCTION_PIPELINE.md`\
**Related reports:** `AUTOSHORTS_OLLAMA_CANDIDATE_DISCOVERY.md`,
`AUTOSHORTS_VIDEO_ANALYSIS_PIPELINE.md`\
**Reverse-engineering skill:**
`C:\Users\laksh\.agents\skills\reverse-engineer-anything`

------------------------------------------------------------------------

## 1. Executive summary

The inspected AutoShorts implementation is comparatively conventional.
Its perceived polish does not come from sophisticated video
understanding. Its reported pipeline combines audio extraction and
transcription, text-only LLM candidate discovery, candidate persistence
and user selection, deterministic FFmpeg vertical cropping, word-timed
captions, and standard H.264/AAC encoding.

The investigation found **no active visual-content analysis** in the
inspected revision: no frame sampling, face detection/tracking,
active-speaker detection, scene analysis, saliency analysis, or
multimodal vision inference. A database field named `face_track_json`
was reported as a schema stub rather than a working tracking system.

The most reusable lessons are practical:

-   Caption presentation can substantially affect perceived polish.
-   Configurable caption presets are more maintainable than separate
    rendering implementations.
-   Clean masters and final styled renders should be separate artifacts.
-   Rendering should degrade gracefully if optional caption rendering
    fails.
-   Audio loudness normalization is worth evaluating, not assuming.
-   Static center cropping is cheap but can fail when the subject is
    off-center.
-   Candidate-selection quality and final-render quality are separate
    problems and should be evaluated separately.

**Recommended decision:** Do not copy AutoShorts wholesale. Preserve our
transcript-first, evidence-grounded discovery and parent/child timeline
architecture. Borrow useful finishing concepts later, after long-clip
discovery and the short-clip pipeline are validated.

## 2. Scope, evidence, and confidence

The reverse-engineering agent inspected the AutoShorts repository and
reported that the investigation was read-only, with no source
modifications. These findings apply to the inspected revision; they do
not establish what later versions of AutoShorts do.

### Areas investigated

-   Overall media-processing flow.
-   Candidate discovery and local Ollama use.
-   Transcription and audio extraction.
-   Final FFmpeg render path and crop calculation.
-   Caption generation, styles, and timing.
-   Encoding parameters and output artifacts.
-   Failure fallback behavior.
-   Presence or absence of visual-analysis implementations.

### Known evidence limitations

-   The reports contain an inconsistency about standalone SRT word
    grouping: one section describes three-word groups, while another
    describes two-word groups. Do not copy the exact SRT grouping
    behavior without checking the relevant source.
-   The named caption presets were identified in code, but their exact
    visual appearance and quality have not been independently
    benchmarked here.
-   The investigation describes implementation mechanics, not
    comparative product performance.
-   A possible context-truncation risk for long transcripts was flagged,
    but not conclusively verified.

For an unresolved detail, first consult the saved reports and relevant
source evidence. Re-run reverse engineering only if those sources cannot
answer a specific question.

## 3. AutoShorts end-to-end pipeline

The reported workflow is:

1.  User imports a source video.
2.  FFprobe inspects media properties.
3.  FFmpeg extracts mono 16 kHz audio.
4.  Audio is transcribed using Deepgram or a local Whisper path; the
    local path provides word timestamps.
5.  A text-only LLM proposes candidate intervals from the transcript.
6.  Candidate records are stored in SQLite.
7.  The user selects a candidate or uses "Cut All."
8.  The application prepares subtitle data and FFmpeg text filters.
9.  FFmpeg renders a vertical MP4 with captions burned in.
10. The application updates candidate/database state and records the
    output path.
11. The output consists of individual clip files and a separate subtitle
    file.

### Implications for our product

AutoShorts' architecture is not a reason to replace our domain model.
Our product has additional requirements that should remain intact:

-   Discover meaningful long conversations first.
-   Discover short moments from accepted long masters, not recursively
    from Shorts.
-   Keep clean masters separate from final captioned deliverables.
-   Preserve source, long-local, and short-local timestamps and lineage.
-   Let backend validation---not the LLM---own interval validity and
    overall scoring.
-   Treat generated output artifacts as evidence; agents must not
    manually edit them.

Reuse isolated rendering and UX concepts rather than adopting
AutoShorts' end-to-end data flow.

## 4. Candidate discovery: findings and reuse decision

### Reported AutoShorts behavior

The local Ollama integration reportedly uses:

`POST http://localhost:11434/api/chat`

Reported settings and models:

-   Default model: `llama3.2` (3B).
-   Alternatives mentioned in code: `qwen2.5:3b` and `qwen2.5:7b`.
-   Temperature: `0.2`.
-   Streaming disabled.
-   JSON-schema output format used.
-   No explicit `num_ctx` setting found in the inspected code.

The report described minimal duration filtering and raw-score sorting,
with SQLite storing up to ten candidates and the UI selecting three to
six. The report also identified weaknesses in source-bound checking,
evidence grounding, deduplication, and overall-score reliability
compared with our intended design.

### Reuse decision

**Do not replace our candidate-discovery logic with AutoShorts'
approach.**

Our existing design is better aligned with our goals:

-   Evidence-backed candidate proposals.
-   Backend validation of source bounds and transcript evidence.
-   Versioned, goal-specific score weights.
-   Backend-calculated overall scores.
-   Configurable long/short duration settings.
-   Deduplication and reason-coded rejection.
-   Human review of actual rendered clips.

Potential future use of these findings:

-   Use the Ollama request pattern as a reference when debugging
    provider integration.
-   Consider explicit context-window configuration only after measuring
    actual context limits and quality.
-   Benchmark model/prompt changes against a fixed evaluation set,
    changing one major variable at a time.
-   Preserve raw proposals and rejection reasons so model weaknesses
    remain visible.

Do not infer that a 3B or 7B model is sufficient merely because
AutoShorts uses one. Our Qwen 2.5 7B long-discovery experiment proposed
ten candidates, but only one was accepted; most rejected candidates were
too short. This is evidence that prompt compliance and editorial quality
need evaluation, not a reason to weaken validation.

## 5. Vertical crop: behavior and implications

### Reported crop method

AutoShorts reportedly uses a static geometric center crop for 9:16
output:

``` text
crop=w='2*trunc(min(iw,ih*9/16)/2)':h='2*trunc(min(ih,iw*16/9)/2)'
```

For a 1920×1080 landscape source, this produces approximately a 606×1080
crop beginning around x=657. The crop keeps the center and discards the
sides.

The inspected implementation reportedly does not provide
blurred-background/padding as an alternative and does not dynamically
pan the crop to follow a speaker.

### Benefits

-   Simple, inexpensive, deterministic, and reproducible.
-   Requires no vision model.
-   Produces a 9:16 frame from common landscape footage.

### Failure modes

-   An off-center speaker can be cropped out.
-   A two-shot can lose one or both people.
-   Split-screen content can become unusable.
-   A moving subject can leave the crop.
-   The crop can remove visual context even when the transcript is
    strong.

### Recommendation for our implementation

Do not adopt static center crop as the only long-term framing strategy.
However, do not start face tracking or multimodal analysis during the
current discovery stages.

When finishing work begins, compare these deterministic options:

1.  **Center crop:** lowest complexity and useful baseline.
2.  **Fit with blurred background:** preserve the full source frame,
    filling the vertical canvas with a blurred enlargement behind it.
3.  **Configurable crop position:** allow horizontal adjustment by
    configuration or a future preview UI.
4.  **Smart reframing:** future work only if visual analysis is
    justified and can be evaluated.

Use the simplest option that improves representative footage. Not every
source needs AI-based reframing.

### Future framing acceptance checks

-   Output has the expected 9:16 aspect ratio/resolution.
-   No unintended black bars unless explicitly selected.
-   The primary subject remains visible throughout.
-   Two-person conversations remain visually understandable where
    possible.
-   Crop position does not jump unexpectedly.
-   Audio and duration remain correct.
-   Variants do not overwrite one another.

## 6. Caption rendering: the strongest reusable finding

### Reported behavior

AutoShorts uses FFmpeg text filters to burn captions into the final
vertical video. The report describes rapid uppercase caption groups,
commonly two words per displayed group, with word-level timing. A
separate subtitle file is also generated.

Reported sizing behavior is proportional to the cropped output width:

-   Approximate font size: `cropped_width * 0.075`.
-   Clamped between 16 and 80 pixels.
-   Box padding scales proportionally.

Proportional sizing is a useful concept: captions should scale with
output dimensions instead of relying on a fixed font size for every
render size.

### Reported presets

The investigation identified seven named presets:

1.  `modern-box`
2.  `classic-outline`
3.  `minimal-shadow`
4.  `vibrant-cyan`
5.  `vibrant-yellow-box`
6.  `vibrant-green`
7.  `vibrant-red`

Treat these as style references, not a requirement to clone every
detail. The exact standalone SRT word grouping remains unresolved;
verify before reproducing it.

### Recommended first version

Start with **three differentiated presets**, adding more only if testing
shows real value:

-   **Clean / Minimal:** readable text, restrained shadow or outline,
    low distraction.
-   **Bold / Outline:** bold, high-contrast text with a strong outline.
-   **Kinetic / Highlighted:** short word groups with a highlight color
    and tighter word-level timing.

Three high-quality presets are more valuable than seven inconsistent
ones.

### Make presets configuration-driven

A preset should be configuration, not a separate rendering
implementation. Where the current renderer supports them, centralize:

-   Font family and weight.
-   Font size or proportional sizing rule.
-   Text and highlight colors.
-   Outline/stroke and shadow.
-   Background box and padding.
-   Vertical placement and safe margins.
-   Words per caption group.
-   Word-level timing behavior.
-   Optional animation behavior.

Do not expose every control in the first UI. First make a small set
reliable; expose deeper customization only when it is useful.

### Caption quality checks

-   Captions match existing transcript and word timestamps.
-   No words or timings are fabricated.
-   Text is legible at phone size.
-   Captions do not unnecessarily cover faces or important visual
    content.
-   Text fits inside safe margins and does not clip.
-   Groups do not flash too quickly or linger after speech.
-   Long words and punctuation do not overflow.
-   Re-rendering does not mutate the clean master.
-   Any subtitle sidecar is consistent with the rendered version.

Caption rendering belongs in the **finishing layer**, after discovery
and clean-master generation. It must not change candidate scoring or
source/parent timeline semantics.

## 7. Clean masters and final deliverables

### Reported AutoShorts output

The inspected implementation reportedly creates individual files such as
`clip-01_flat.mp4` with captions burned in, plus a corresponding `.srt`.
Its output location is under
`~/Documents/AutoShorts/<project_slug>/clips/`.

The report does not describe a reusable clean-master/final-variant
package equivalent to our intended design.

### Our design decision

Keep our richer artifact separation:

-   `clip_XX.mp4`: clean master, cut and reframed, without captions or
    finishing effects newly burned in by our renderer.
-   `clip_XX_final.mp4`: final deliverable with selected caption
    style/effects.
-   `transcript.json`: clip-local transcript, preserving available word
    metadata.
-   `metadata.json`: source/parent lineage, timestamps, configuration,
    and render details.
-   Optional `captions.srt` and `captions.ass`.
-   Run-level manifest and run metadata.

If the source already has baked-in captions, our renderer cannot remove
them; "clean" means we have not added new captions or finishing effects.

Short clips must be rendered from the clean long master, never from a
final long render that may already contain captions/effects.

### Variant and overwrite safety

Future users may render multiple styles for the same clip. Give variants
explicit identities and prevent accidental overwrites.

Before implementing variants:

-   Inspect the current `OutputManager` overwrite behavior.
-   Record preset/configuration in metadata.
-   Use atomic staging/promotion.
-   Ensure failed renders do not leave partial final deliverables.
-   Never mutate existing artifacts in place.
-   Make reruns explicit and traceable.

## 8. Rendering and encoding defaults

### Reported settings

-   Video: H.264 using `libx264`.
-   Preset: `fast`.
-   CRF: `18`.
-   Pixel format: `yuv420p`.
-   Audio: AAC at 192 kbps.

These are useful baselines, not proven optimal values for every source
or deployment.

The report did not find audio loudness normalization, silence removal,
transitions, or dynamic pan/zoom in the inspected path.

### Recommendations

-   Keep encoding settings explicit and centralized.
-   Validate output playability and expected streams.
-   Check audio/video duration alignment.
-   Benchmark file size and render time alongside perceptual quality.
-   Treat CRF/preset changes as controlled experiments.

### Audio loudness normalization

Treat normalization as a **future experiment**, not an automatic
requirement. Compare source/output loudness on varied clips. Check for
improved consistency without clipping, pumping, or unwanted changes to
music and audience reactions. Preserve a way to disable it if it harms a
source.

### Silence removal and transitions

Do not add these just because they are common editing features. Silence
removal can damage comedic timing, pauses, reactions, and conversational
rhythm. Transitions may make interview/podcast clips feel less
authentic. Add them only if evaluation demonstrates benefit.

## 9. Graceful fallback when captions fail

The report says AutoShorts retries rendering without captions if the
caption-rendering path fails. This is a useful reliability pattern,
provided the fallback is explicit in metadata and logs.

### Recommended behavior

1.  Attempt the requested final render.
2.  If the caption/filter step fails, preserve the clean master.
3.  Record the error and failed attempt.
4.  Optionally produce a plain fallback deliverable only if product
    policy enables it.
5.  Mark the fallback clearly in metadata/status.
6.  Never report that the requested captioned render succeeded if it did
    not.

A fallback should preserve a usable video where possible without hiding
the error.

### Future tests

-   Normal caption rendering succeeds.
-   Caption rendering fails and clean master remains intact.
-   Optional fallback is playable.
-   Metadata records fallback status and error.
-   A temporary partial file is not treated as complete.
-   Retrying does not overwrite unrelated variants.

## 10. UI and preview observations

The report says the inspected AutoShorts implementation did not provide
a real video player/crop-adjustment experience; its preview was a CSS
mock rather than an actual rendered-video preview.

For our product, do not build a mock preview that appears interactive
but does not represent the render. When preview work is justified, show
a real representative render or clearly label an approximate preview and
its limitations.

A real preview can help validate crop, caption placement, line breaks,
and safe areas. It is not required for the current discovery stages.

## 11. Features not found in the inspected revision

The report found no active implementation for:

-   Frame sampling for candidate evaluation.
-   Face detection or face tracking.
-   Active-speaker tracking.
-   Scene-cut detection.
-   Saliency-based crop positioning.
-   Multimodal video-language analysis.
-   Dynamic pan/zoom.
-   Blurred-background vertical composition.
-   Silence removal.
-   Audio loudness normalization.
-   Transitions.

The `face_track_json` field was reported as a dead schema stub.

These absences help explain the output: composition is deterministic and
candidate discovery is transcript/text-based in the inspected revision.
They do not prove these features are unhelpful; they mean we should not
assume AutoShorts has solved them or copy nonexistent behavior.

## 12. Recommended implementation roadmap

This roadmap is aligned with our staged plan and does not authorize
implementation out of sequence.

### Stage A --- Finish discovery foundations

**Goal:** Produce coherent long masters and validate their quality.

-   Complete long-discovery integration and deterministic tests.
-   Review real long-master videos and transcripts.
-   Record editorial-quality findings.
-   Do not add caption presets or visual AI here.

**Exit evidence:** Valid packages plus human review of whether accepted
long clips preserve meaningful conversations.

### Stage B --- Standalone short-clip pipeline

**Goal:** Discover optional short moments from accepted clean long
masters.

-   Reuse long-local transcript and word timings.
-   Apply short-specific prompts and duration settings.
-   Render from the clean long master.
-   Preserve source/parent/local timestamps and lineage.
-   Allow zero Shorts.

**Exit evidence:** Deterministic tests, followed by a separately
authorized real end-to-end experiment and human review.

### Stage C --- Unified orchestration and output reliability

**Goal:** Make the long-to-short workflow repeatable and traceable.

-   Integrate stages through the intended CLI/orchestrator.
-   Preserve manifests and metadata.
-   Handle failures, reruns, and resume behavior deliberately.
-   Verify generated artifacts cannot be overwritten unexpectedly.

### Stage D --- Caption finishing presets

**Goal:** Improve presentation of already-good clips.

-   Reuse existing subtitle and FFmpeg foundations.
-   Implement three initial presets.
-   Keep the clean master unchanged.
-   Save final renders separately.
-   Add explicit fallback handling.
-   Evaluate render time, output size, caption legibility/timing, and
    human preference.

Preset work must not alter discovery, scoring, or timeline semantics.

### Stage E --- Framing experiments

Compare center crop, blurred-background fit, and adjustable crop
position on representative landscape and off-center-speaker footage.
Consider smart reframing only if deterministic options fail often enough
to justify complexity.

### Stage F --- Audio finishing experiments

Evaluate whether normalization improves consistency without damaging
source dynamics. Retain it only if controlled testing shows a clear
benefit.

### Stage G --- Further visual intelligence

Add subject-aware crop positioning, face/speaker tracking, scene-aware
selection, or multimodal evaluation only when there is a defined user
problem and an evaluation set. These are separate research/engineering
efforts, not prerequisites for the current product.

## 13. Future finishing evaluation checklist

### Functional correctness

-   [ ] Source and parent timelines remain unchanged.
-   [ ] Transcript and word timings are reused, not fabricated.
-   [ ] Clean master is preserved.
-   [ ] Final variants have distinct identities.
-   [ ] Metadata records style/configuration and render status.
-   [ ] Failures do not leave partial deliverables marked complete.
-   [ ] Reruns do not overwrite unrelated artifacts.

### Perceptual quality

-   [ ] Captions are readable on a phone-sized display.
-   [ ] Caption timing follows speech naturally.
-   [ ] Important visual content remains visible.
-   [ ] Crop keeps the relevant subject in frame.
-   [ ] Audio is clear and consistent without unnatural
    pumping/clipping.
-   [ ] Finishing improves rather than distracts from the clip.

### Engineering quality

-   [ ] Rendering settings are centralized and testable.
-   [ ] Existing renderer/subtitle abstractions are reused where
    appropriate.
-   [ ] Presets are configuration-driven.
-   [ ] A style change does not duplicate the entire pipeline.
-   [ ] Unit tests cover configuration and failure behavior.
-   [ ] Real-model/render experiments are separately authorized and use
    new output runs.

### Product value

-   [ ] Human reviewers can notice the improvement.
-   [ ] Benefit justifies implementation and maintenance cost.
-   [ ] Work does not delay validation of the core long-to-short
    workflow.
-   [ ] The feature can be disabled or selected when unsuitable.

## 14. Repository and artifact safety

Standing requirements for future coding-agent work:

-   Keep `input/` and `outputs/` in `.gitignore`.
-   Do not commit source videos, generated masters, final renders, or
    run artifacts.
-   Agents may inspect outputs but must not manually edit, rename,
    delete, or overwrite them.
-   Fix pipeline code rather than altering output files to make an
    evaluation look correct.
-   Run new experiments only with explicit authorization and a newly
    created, isolated output run.
-   A separate `experimental_output/` directory is not required; normal
    `outputs/` is acceptable when the application creates a new unique
    run.
-   Preserve approved PRD and TechSpec unless the user explicitly
    authorizes changes.
-   Document unresolved assumptions rather than silently turning them
    into requirements.

## 15. Decision log

  -----------------------------------------------------------------------
  Topic                   Decision                Rationale
  ----------------------- ----------------------- -----------------------
  Copy AutoShorts         No                      Our product has
  architecture wholesale                          stronger timeline,
                                                  evidence, lineage, and
                                                  clean-master
                                                  requirements.

  Reuse FFmpeg finishing  Yes, later              Existing
  concepts                                        renderer/subtitle
                                                  foundations make this
                                                  incremental.

  Implement all seven     No                      Start with three
  presets immediately                             differentiated,
                                                  reliable styles.

  Keep clean masters      Yes                     Enables alternate
  separate from final                             styles and protects
  renders                                         against
                                                  repeated/burned-in
                                                  effects.

  Fallback when caption   Consider, with explicit Reliability helps, but
  rendering fails         status                  users must not be
                                                  misled about a failed
                                                  requested render.

  Use center crop as the  No                      Simple baseline, but it
  only framing mode                               can fail for off-center
                                                  subjects and two-shots.

  Add face                No                      Not needed to validate
  tracking/multimodal                             current discovery
  analysis now                                    stages; higher
                                                  complexity.

  Add audio normalization No                      Evaluate with a
  immediately                                     controlled experiment
                                                  first.

  Remove pauses/silence   No                      Can damage comedic
  by default                                      timing and
                                                  conversational rhythm.

  Re-run reverse          Not normally            Existing reports cover
  engineering for the                             discovery and final
  same areas                                      production for the
                                                  inspected revision.
  -----------------------------------------------------------------------

## 16. When another reverse-engineering pass is warranted

A new pass should be an exception, not a recurring step for the same
already-inspected code.

Consider it only if:

1.  A specific implementation detail is not answered by saved reports
    and source evidence is unavailable or unclear.
2.  The reference repository has changed materially and we explicitly
    want to compare the new revision.
3.  We investigate a genuinely new subsystem outside the previous scope.
4.  A contradiction between report and source could change an
    engineering decision.
5.  A future feature requires exact behavioral parity and current
    reports only describe it at a high level.

Before requesting another pass, search the three saved reports and
inspect the relevant source directly. Ask a narrowly scoped question
instead of requesting another full-repository review.

## 17. Final takeaway

The reusable lesson from AutoShorts is not "build the same app." It is:

-   Use transcript-based discovery to identify candidate moments.
-   Make vertical composition and captions legible.
-   Keep rendering deterministic and configurable.
-   Preserve clean source artifacts.
-   Fail gracefully and record what happened.
-   Evaluate actual videos, not merely whether a command succeeded.

For our product, the order matters: **first discover coherent
conversations, then discover useful Shorts, then polish their
presentation.** Finishing features should improve already-good
clips---not compensate for weak candidate selection.
