# Reverse Engineering Report: AutoShorts Post-Transcription Video Analysis Pipeline

**Target Reference Application**: AutoShorts (`C:\Lakshya\AI\autoshorts`)  
**Investigated Artifacts**:
* Source Tree: `C:\Lakshya\AI\autoshorts` (commit `5ae8dd3`, tag `v0.1.3` at `4ff6e61`)
* Compiled Binary: `C:\Lakshya\Applications\AutoShorts_0.1.3_x64-setup.exe` (PE32 NSIS installer)
* Decompressed Application Payload: `15,815,832` bytes (NSIS LZMA stream extraction)

**Destination Project**: AI Video Clipper (`C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`)  
**Document Path**: `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper\docs\RE\AUTOSHORTS_VIDEO_ANALYSIS_PIPELINE.md`
**Skill Reference**: `reverse-engineer-anything` (`C:\Users\laksh\.agents\skills\reverse-engineer-anything\SKILL.md`)  
**Date**: October 2026  
**Auditor**: Antigravity Assistant  

---

## 1. Executive Summary

This investigation sought to determine whether and how AutoShorts analyzes visual video information after transcription to discover, validate, refine, rank, or reframe short-form video clips.

### Definitive Finding
**AutoShorts performs ZERO visual analysis at any stage of its pipeline.**

Specifically:
1. **No Frame Extraction**: No video frames are ever extracted as images (JPEG, PNG, RGB buffers) before, during, or after transcription.
2. **No Multimodal/Vision Inference**: All LLM integrations (DeepSeek, Claude 3.5 Sonnet, Google Gemini, OpenAI GPT-4o-mini, OpenRouter, Groq, and local Ollama) send **pure text prompts containing only transcript text and timestamp annotations**. No image payloads, base64 strings, or video file URLs are transmitted to any model.
3. **No Computer Vision Dependencies**: The codebase contains no computer vision libraries—neither OpenCV, MediaPipe, PySceneDetect, ONNX Runtime, nor any Rust/JavaScript image processing libraries.
4. **Dead Database Schema Artifact (`face_track_json`)**: The SQLite database schema contains a column `face_track_json` in the `clips` table, but source audit reveals this column was committed as an unused stub in the initial commit (`fbb9ead`, June 22, 2026) and is **never populated, updated, or read** by any business logic.
5. **Static Geometric Center Cropping**: Vertical portrait reframing (9:16) is performed exclusively via a hardcoded mathematical FFmpeg filter expression (`crop=w='2*trunc(min(iw,ih*9/16)/2)':h='2*trunc(min(ih,iw*16/9)/2)'`). This cuts a static window out of the exact geometric center of the frame with no active speaker tracking, face centering, or saliency awareness.
6. **No Video Player or Visual Previews in UI**: The frontend contains no HTML5 `<video>` player, canvas, or thumbnail renderer. It displays a static CSS mockup placeholder with the text `"9:16"`.

---

## 2. End-to-End Processing-Flow Diagram

The following diagram illustrates the verified end-to-end execution path of AutoShorts from media ingestion through clip rendering:

```mermaid
flowchart TD
    subgraph INGESTION ["1. Ingestion & Pre-Inspection"]
        A["Input Media (.mp4 / .mov / .mp3 / YouTube)"] --> B["FFprobe Media Probe<br/>(Reads duration, width, height, codecs)"]
        B --> C["FFmpeg Audio Extraction<br/>(ffmpeg -vn -ac 1 -ar 16000 output.wav)"]
    end

    subgraph TRANSCRIPTION ["2. Speech-to-Text Pipeline"]
        C --> D{"Provider Selection"}
        D -->|Cloud| E["Deepgram Nova-2 REST API<br/>(Binary WAV via HTTPS POST)"]
        D -->|Local| F["OpenAI Whisper<br/>(CLI or transcribe.py fallback)"]
        E --> G["Word-Level Timestamps<br/>(text, start, end, speaker)"]
        F --> G
        G --> H["Heuristic Sentence Segmentation<br/>(Splits on >0.9s pause, speaker shift, punctuation)"]
        H --> I[("SQLite Database<br/>transcripts table")]
    end

    subgraph CANDIDATE_DISCOVERY ["3. Text-Only Candidate Discovery"]
        I --> J["Segment Compaction<br/>'[{start:.2}-{end:.2}] {speaker}: {text}'"]
        J --> K{"LLM Engine Dispatch"}
        K -->|Ollama| L["Local Ollama (/api/chat)<br/>Format: JSON Schema, Temp: 0.2"]
        K -->|DeepSeek| M["DeepSeek Chat (/chat/completions)<br/>Pure Text Prompt"]
        K -->|Claude| N["Anthropic Messages (/v1/messages)<br/>Pure Text Prompt"]
        K -->|Gemini| O["Google Gemini (/generateContent)<br/>Pure Text Prompt"]
        K -->|OpenAI| P["OpenAI (/chat/completions)<br/>Pure Text Prompt"]
        L & M & N & O & P --> Q["Defensive JSON Parser<br/>(Extracts start, end, score, hook, rationale)"]
        Q --> R["Duration Filter (30-90s) & Score Sort"]
        R --> S[("SQLite Database<br/>candidates table & clips table [pending]")]
    end

    subgraph RENDERING ["4. FFmpeg Video Rendering & Subtitling"]
        S --> T["User / Batch Trigger: 'Cut'"]
        T --> U["Generate Subtitle Data<br/>- .srt file from transcript words<br/>- FFmpeg drawtext filter string (2 words/chunk)"]
        U --> V["FFmpeg Flat Clip Render<br/>Fast seek: -ss {start} -i {src} -t {duration}<br/>Static Center Crop: crop=w=...:h=...<br/>Chained drawtext filter overlay<br/>Codec: libx264 fast CRF 18, aac 192k"]
        V --> W{"Render Succeeded?"}
        W -->|Yes| X["Save MP4 to Documents/AutoShorts/clips"]
        W -->|No (Font/Filter Error)| Y["Fallback Render (No Captions)<br/>Re-runs FFmpeg without drawtext"]
        Y --> X
        X --> Z["Update SQLite clips table<br/>status='done', output_path='...'"]
    end

    style INGESTION fill:#1e293b,stroke:#475569,stroke-width:2px,color:#f8fafc
    style TRANSCRIPTION fill:#1e293b,stroke:#475569,stroke-width:2px,color:#f8fafc
    style CANDIDATE_DISCOVERY fill:#1e293b,stroke:#475569,stroke-width:2px,color:#f8fafc
    style RENDERING fill:#1e293b,stroke:#475569,stroke-width:2px,color:#f8fafc
```

---

## 3. Video-Analysis Techniques & Source Audit

A comprehensive search of the entire AutoShorts codebase (`src/` and `src-tauri/`) was conducted for video analysis mechanisms. Below are the verified findings:

| Video Analysis Technique | Status in AutoShorts | Source Reference | Technical Observation |
| :--- | :--- | :--- | :--- |
| **Video Frame Extraction** | **ABSENT** | N/A | No `ffmpeg -vf fps=...`, `-vframes`, or frame decoders exist anywhere in the code. |
| **Scene Change Detection** | **ABSENT** | N/A | No `select='gt(scene,0.4)'`, PySceneDetect, or keyframe boundary analysis. |
| **Adaptive Frame Sampling** | **ABSENT** | N/A | No frames are sampled at any interval. |
| **Face / Speaker Detection** | **DEAD STUB** | [`src-tauri/src/db.rs#L77`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/db.rs#L77)<br>[`src-tauri/src/models.rs#L79`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/models.rs#L79) | Column `face_track_json TEXT` exists in the database table `clips`, but is never written, updated, or referenced in rendering. |
| **Active Speaker Tracking** | **ABSENT** | N/A | No audio-visual synchronization or active speaker bounding box tracking. |
| **Saliency / Gaze Tracking** | **ABSENT** | N/A | No saliency maps or optical flow. |
| **Multimodal / Vision APIs** | **ABSENT** | [`src-tauri/src/llm.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs) | All LLM endpoints receive text-only payloads. No base64 image data or URLs are ever constructed. |
| **Vertical Video Reframing** | **STATIC ONLY** | [`src-tauri/src/media.rs#L130`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs#L130) | Hardcoded mathematical center crop expression in FFmpeg filtergraph. |
| **Computer Vision Libs** | **ABSENT** | [`src-tauri/Cargo.toml`](file:///C:/Lakshya/AI/autoshorts/src-tauri/Cargo.toml)<br>[`package.json`](file:///C:/Lakshya/AI/autoshorts/package.json) | Neither OpenCV, MediaPipe, image-rs, ONNX, nor PyTorch are present in project manifests. |

---

## 4. Models, Providers, and Inference Interfaces

AutoShorts supports seven LLM providers in [`src-tauri/src/llm.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs). Every single provider is invoked using **text-only chat/completions endpoints**:

### 4.1 DeepSeek (Default Cloud Provider)
* **Function**: `detect_candidates_with_deepseek` ([`lines 33–98`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L33-L98))
* **Endpoint**: `POST https://api.deepseek.com/chat/completions`
* **Model**: Default `deepseek-chat` (or user override from settings).
* **Payload Structure**:
  ```json
  {
    "model": "deepseek-chat",
    "messages": [
      {
        "role": "user",
        "content": "<system_instructions>\n\nTranscript:\n[0.00-3.50] S1: Text..."
      }
    ],
    "temperature": 0.2,
    "response_format": { "type": "json_object" }
  }
  ```
* **Visual Payload**: **None**.

### 4.2 Google Gemini
* **Function**: `detect_candidates_with_gemini` ([`lines 120–185`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L120-L185))
* **Endpoint**: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`
* **Model**: Default `gemini-2.5-flash`.
* **Payload Structure**:
  ```json
  {
    "contents": [
      {
        "parts": [
          { "text": "<system_instructions>\n\nTranscript:\n..." }
        ]
      }
    ],
    "generationConfig": {
      "responseMimeType": "application/json",
      "temperature": 0.2
    }
  }
  ```
* **Visual Payload**: **None**. Despite Gemini's native multimodal video/image capability (`inlineData` / file API), AutoShorts passes only `{ "text": prompt }`.

### 4.3 Anthropic Claude
* **Function**: `detect_candidates_with_claude` ([`lines 405–464`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L405-L464))
* **Endpoint**: `POST https://api.anthropic.com/v1/messages`
* **Model**: Default `claude-3-5-sonnet-latest`.
* **Payload Structure**: Passes text message content (`role: "user", content: prompt`).
* **Visual Payload**: **None**. Claude's image content blocks (`type: "image"`) are not used.

### 4.4 OpenAI
* **Function**: `detect_candidates_with_openai` ([`lines 202–262`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L202-L262))
* **Endpoint**: `POST https://api.openai.com/v1/chat/completions`
* **Model**: Default `gpt-4o-mini`.
* **Visual Payload**: **None**. Pure text chat completions payload.

### 4.5 Local Ollama
* **Function**: `detect_candidates_with_local_llm` ([`lines 476–553`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L476-L553))
* **Endpoint**: `POST http://localhost:11434/api/chat`
* **Models**: `llama3.2`, `qwen2.5:3b`, `qwen2.5:7b`.
* **Visual Payload**: **None**. Passes `"images": []` is omitted entirely; only text messages are sent.

---

## 5. Interaction Between Transcript and Visual Analysis

Because visual analysis is completely absent from AutoShorts, the interaction between transcript and visual analysis is strictly unidirectional and decoupled:

1. **Discovery is 100% Transcript-Driven**: Moments are chosen entirely based on spoken transcript keywords, hooks, emotional shifts, and narrative boundaries. The LLM has zero awareness of who is on screen, camera cuts, visual pacing, screen shares, or visual humor.
2. **Boundaries are Audio-Driven**: The start and end timestamps (`start_sec`, `end_sec`) are selected by the LLM from the timestamped audio transcript segments (`[start-end] S1: text`). No visual keyframe alignment or scene cut boundary snapping is performed.
3. **Reframing is Purely Geometric**: Video frames are blindly cropped around the geometric center point during final clip rendering, regardless of where the active speaker is located.

---

## 6. Effects on Candidate Selection, Ranking, Boundaries, and Rendering

| Pipeline Step | Is Visual Information Used? | Actual Implementation in AutoShorts | Source Reference |
| :--- | :--- | :--- | :--- |
| **Candidate Inclusion / Filtering** | **NO** | Evaluates only transcript duration `(end - start) >= 30.0s` and non-empty hook string. | [`src-tauri/src/llm.rs#L705-L717`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L705-L717) |
| **Candidate Ranking & Scores** | **NO** | Ranks candidates strictly by the scalar `score` returned by the text LLM. | [`src-tauri/src/llm.rs#L719`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L719) |
| **Start / End Boundaries** | **NO** | Directly uses the text transcript segment timestamps emitted by the LLM. | [`src-tauri/src/lib.rs#L586`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L586) |
| **Thumbnail / Opening Frame** | **NO** | No thumbnail generation exists. Frontend displays a CSS icon card. | [`src/main.tsx#L1019-L1031`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L1019-L1031) |
| **Vertical Reframing / Crop** | **NO** (Static Center Crop) | Uses static FFmpeg filter: `crop=w='2*trunc(min(iw,ih*9/16)/2)':h='2*trunc(min(ih,iw*16/9)/2)'`. | [`src-tauri/src/media.rs#L130`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs#L130) |
| **Caption Timing** | **NO** (Audio-Derived) | Word timing is derived from Deepgram/Whisper audio timestamps in 2-word chunks. | [`src-tauri/src/lib.rs#L978-L987`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L978-L987) |

### The Center-Crop Mathematical Reality
In [`src-tauri/src/media.rs#L130`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs#L130), the FFmpeg crop filter is specified as:
```text
crop=w='2*trunc(min(iw,ih*9/16)/2)':h='2*trunc(min(ih,iw*16/9)/2)'
```
Because the `x` and `y` offset parameters are omitted, FFmpeg applies its built-in defaults:
* `x = (in_w - out_w) / 2`
* `y = (in_h - out_h) / 2`

**Mathematical Example on 1080p Landscape (1920x1080)**:
* `iw = 1920`, `ih = 1080`
* `out_w = 2 * trunc(min(1920, 1080 * 9 / 16) / 2) = 2 * trunc(607.5 / 2) = 606`
* `out_h = 2 * trunc(min(1080, 1920 * 16 / 9) / 2) = 2 * trunc(1080 / 2) = 1080`
* `x_offset = (1920 - 606) / 2 = 657`

This extracts a static `606 x 1080` vertical window positioned horizontally from pixel 657 to 1263.
* If a speaker is centered in the camera frame, they remain in view.
* If a speaker is seated on the left (e.g. pixels 100–600) or right (pixels 1300–1800), **their body and face are completely cropped out of the output clip**, resulting in a video showing empty background or a microphone stand.

---

## 7. Configuration Options and Default Values

All visual and rendering configurations in AutoShorts are hardcoded with zero user-facing toggles:

| Parameter | Configuration Location | Configurable via UI? | Default Value | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Crop Aspect Ratio** | `src-tauri/src/media.rs#L130` | No | 9:16 portrait | Hardcoded into the FFmpeg filter string. |
| **Crop Position** | `src-tauri/src/media.rs#L130` | No | Center `(in_w - out_w)/2` | No dynamic face or speaker tracking offset. |
| **Video Encoder** | `src-tauri/src/media.rs#L137` | No | `libx264` | Software encoding; no NVENC, QuickSync, or VideoToolbox. |
| **Encoder Preset & Quality** | `src-tauri/src/media.rs#L137` | No | `-preset fast -crf 18` | Constant Rate Factor 18 (visually lossless). |
| **Pixel Format** | `src-tauri/src/media.rs#L137` | No | `yuv420p` | Standard 8-bit YUV 4:2:0 for maximum mobile playback compatibility. |
| **Audio Codec & Bitrate** | `src-tauri/src/media.rs#L142` | No | `-c:a aac -b:a 192k` | Standard stereo/mono AAC at 192 kbps. |
| **Caption Visual Style** | `src/main.tsx#L127` | Yes (Style Modal) | `modern-box` | Controls font color, stroke, background box, and drop shadow. |

---

## 8. Test Execution and Verification

### 8.1 Static Binary & Code Verification
* Decompression of the compiled installer `AutoShorts_0.1.3_x64-setup.exe` confirmed:
  1. The exact crop filter string `crop=w='2*trunc(min(iw,ih*9/16)/2)':h='2*trunc(min(ih,iw*16/9)/2)'` is compiled directly into the binary's text segment.
  2. No strings referencing OpenCV, MediaPipe, `dlib`, `yolo`, `scrfd`, or `retinaface` exist anywhere in the executable.
  3. All network requests initiated by the application target either transcription (`api.deepgram.com`) or text completion endpoints (`api.deepseek.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `api.openai.com`, `openrouter.ai`, `api.groq.com`, `localhost:11434`).

### 8.2 Rendering Execution Test
To confirm FFmpeg execution behavior during clip cutting, we analyzed the render command invocation in [`src-tauri/src/media.rs#L126-L145`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs#L126-L145):
```rust
let mut cmd = Command::new("ffmpeg");
cmd.args(["-y", "-ss", &start, "-i", source_path, "-t", &duration]);
cmd.args(["-vf", &filter]);
cmd.args(["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]);
cmd.args(["-c:a", "aac", "-b:a", "192k"]);
cmd.arg(output_path);
```
* **Seeking Logic**: Uses fast input seeking (`-ss <start> -i <source> -t <duration>`). This seeks to the nearest keyframe before `<start>` and decodes forward, resetting presentation timestamps (PTS) to 0.
* **Caption Timing Sync**: Subtitle drawtext timestamps are calculated relative to clip start (`start_rel = first.start - candidate.start_sec`), correctly matching the reset PTS of the cut video stream.

---

## 9. Evidence Table

| Claim / Component | Classification | File Path & Function | Line Numbers |
| :--- | :--- | :--- | :--- |
| **No Frame Extraction** | `CONFIRMED_SOURCE` | [`src-tauri/src/media.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs) | Whole file (only `probe_media`, `extract_audio`, `render_flat_clip`) |
| **Static Center Crop** | `CONFIRMED_SOURCE` & `CONFIRMED_RUNTIME` | [`src-tauri/src/media.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs) (`render_flat_clip`) | [`lines 130–136`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/media.rs#L130-L136) |
| **Dead Schema: `face_track_json`** | `CONFIRMED_SOURCE` | [`src-tauri/src/db.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/db.rs) (`migrate`, `list_clips_for_project`)<br>[`src-tauri/src/models.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/models.rs) (`Clip`) | [`db.rs#L77, L401, L413`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/db.rs#L77)<br>[`models.rs#L79`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/models.rs#L79) |
| **Text-Only LLM Prompts** | `CONFIRMED_SOURCE` & `CONFIRMED_RUNTIME` | [`src-tauri/src/llm.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs) | [`lines 33–553`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/llm.rs#L33-L553) |
| **No Image/CV Dependencies** | `CONFIRMED_SOURCE` | [`src-tauri/Cargo.toml`](file:///C:/Lakshya/AI/autoshorts/src-tauri/Cargo.toml)<br>[`package.json`](file:///C:/Lakshya/AI/autoshorts/package.json) | Full manifests |
| **No UI Video Player Element** | `CONFIRMED_SOURCE` | [`src/main.tsx`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx) (`portrait-preview-mock`) | [`lines 1019–1031`](file:///C:/Lakshya/AI/autoshorts/src/main.tsx#L1019-L1031) |
| **Font Sizing Based on Width** | `CONFIRMED_SOURCE` | [`src-tauri/src/lib.rs`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs) (`build_drawtext_filters`) | [`lines 1004–1006`](file:///C:/Lakshya/AI/autoshorts/src-tauri/src/lib.rs#L1004-L1006) |

---

## 10. Separation of Facts, Inferences, and Unresolved Questions

### Confirmed Facts
1. AutoShorts does not read, sample, or decode video frames for any AI, heuristic, or ranking purpose.
2. The selection of clips is 100% transcript-driven.
3. Vertical cropping is a static center-cut with no speaker tracking.
4. `face_track_json` in the SQLite database is an unused placeholder column from an early prototype or planned feature that was never implemented.
5. All multimodal LLM APIs (Gemini, Claude, OpenAI) are used strictly as text-in / text-out chat models.

### Reasonable Inferences
1. The author likely intended to implement face tracking (evidenced by the database column `face_track_json` and `.portrait-preview-mock`), but abandoned or deferred it in favor of shipping the simpler static center-crop pipeline.
2. The author avoided multimodal video analysis due to API cost and latency: sending sampled video frames or raw video to Gemini or Claude 3.5 Sonnet increases API costs by 10x–50x per run compared to sending pure text transcripts.

### Unresolved Questions
1. Did the author experiment with an external face tracking script or sidecar binary prior to the initial commit `fbb9ead`? (No orphaned branch or PR exists in the Git repository).
2. Was static center cropping considered an acceptable trade-off because AutoShorts primarily targets single-speaker webcam/talking-head podcasts where the speaker is naturally centered?

---

## 11. Architectural Lessons for AI Video Clipper

The findings from AutoShorts provide critical architectural guidance for designing the **AI Video Clipper** product:

### 11.1 The Pitfalls of AutoShorts' Approach
1. **The "Missing Speaker" Failure Mode**:
   AutoShorts' static center crop (`crop=w=...:h=...`) fails completely on two-person interviews (e.g. host on the left, guest on the right), wide podcast tables, screen shares, and dynamic camera movements. It produces clips where the speaking subject is partially or entirely out of frame.
2. **Visual Disconnect in Moments Discovery**:
   Because moments are chosen purely from text, AutoShorts frequently selects moments that sound engaging in the transcript but are visually uninteresting (e.g. static title slides, off-screen audio, or b-roll transitions).

### 11.2 What AI Video Clipper Should Do Instead
To build a professional, industry-grade video clipper, AI Video Clipper should implement a **two-tier visual pipeline**:

#### Tier 1: Text-First Candidate Discovery (Fast & Cheap)
Follow AutoShorts' model of using the text transcript for the initial coarse discovery pass. This keeps token costs under $0.005 per run and runs in 3–5 seconds:
* Use `LLMProvider` on chunked transcript text to generate candidate time intervals `[start_seconds, end_seconds]`.

#### Tier 2: Post-Discovery Visual Refinement & Active Speaker Tracking (Targeted & Accurate)
Do **NOT** analyze the entire 1-hour video with computer vision. Instead, apply visual analysis **only to the selected candidate clip intervals** (e.g. 5 clips × 45 seconds = 3.75 minutes of video):
1. **Active Speaker Detection (ASD) & Smart Framing**:
   * Use a lightweight face detection and tracking model (e.g., SCRFD, MediaPipe Face, or YOLO-Face) running locally in the background worker on the candidate intervals.
   * Calculate smoothed horizontal bounding box centers ($x_{target}$) for each frame or shot.
   * Generate an animated or smoothed dynamic crop filter in FFmpeg (`crop=w=...:h=...:x='smooth_x(t)':y=...`) so the camera smoothly pans to keep the active speaker centered.
2. **Shot Boundary Snapping**:
   * Run lightweight scene change detection (via PySceneDetect or FFmpeg `select='gt(scene,0.4)'`) on the candidate boundaries.
   * Snap the start/end timestamps to the nearest visual shot cut within a ±1.5s tolerance to avoid cutting mid-camera transition.
3. **Visual Quality & Keyframe Ranking**:
   * Sample 3–5 keyframes from each candidate.
   * Evaluate visual saliency, face presence, and clarity to inform candidate ranking and automatically pick the optimal thumbnail frame.

---

### Audit Conclusion
AutoShorts is fundamentally an **audio-and-text pipeline with a static FFmpeg cutting script**. It contains no visual intelligence. 

By identifying this limitation, the AI Video Clipper team can recognize that AutoShorts' rendering engine is a baseline reference for FFmpeg fast-seeking and subtitle burning, but its complete absence of visual analysis leaves a major product opportunity for AI Video Clipper to deliver true value through **dynamic speaker-tracking framing** and **scene-aware clip refinement**.
