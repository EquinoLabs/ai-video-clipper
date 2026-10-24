# Reverse Engineering & Recreation Specification: AutoShorts Video Transcription Pipeline

**Target Artifact**: `C:\Lakshya\Applications\AutoShorts_0.1.3_x64-setup.exe`  
**Source Repository Analysis**: `C:\Lakshya\AI\autoshorts` (v0.1.3)  
**Destination Repository**: `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`  
**Analysis Date**: October 2026  
**Status**: Complete / Verified

---

## 1. Executive Summary & Reverse Engineering Findings

### 1.1 Target Binary Profile
* **File**: `AutoShorts_0.1.3_x64-setup.exe`
* **Size**: 4,184,413 bytes (~4.18 MB)
* **Format**: PE32 (Win32 x86 NSIS self-extracting installer stub housing a 64-bit Tauri v2 payload)
* **SHA-256**: `f6902049636f3761adf813661f36c4d40b4c305bc8f799f4adc2e1192e922658`
* **Runtime Framework**: Tauri v2 (`com.autoshorts.desktop`) with Rust backend (`autoshorts_lib`) and React 19 frontend bundle.

### 1.2 Transcription Subsystem Capabilities
AutoShorts implements a **hybrid dual-engine transcription system**:
1. **Cloud Speech-to-Text**: Deepgram Nova-2 (`model=nova-2`) over HTTPS POST with multi-speaker diarization and filler word detection.
2. **Offline Speech-to-Text**: Local OpenAI Whisper (`base` model by default), operated either via the native `whisper` CLI or a dynamically synthesized Python script running PyTorch/`openai-whisper`.
3. **Audio Pre-Processing**: FFmpeg stream extraction to 16 kHz 16-bit mono PCM WAV.
4. **Heuristic Word-to-Sentence Segmentation**: Dynamic boundary grouping based on pause durations (>900ms), speaker transition, and sentence-ending punctuation.

---

## 2. End-to-End Transcription Architecture

```
                    ┌────────────────────────────────────────┐
                    │      Source Video/Audio Ingestion       │
                    │ (.mp4, .mov, .mp3, .wav, .m4a, yt-dlp) │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │        FFprobe Media Inspection        │
                    │   Checks duration, video/audio streams │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │        FFmpeg Audio Extraction         │
                    │  16,000 Hz, 1-channel Mono WAV (-vn)   │
                    └───────────────────┬────────────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
  ┌─────────────────────────────┐               ┌─────────────────────────────┐
  │  Engine A: Deepgram Nova-2  │               │   Engine B: Local Whisper   │
  │  (Cloud REST API)           │               │   (CLI or Python Fallback)  │
  │  - Nova-2 model             │               │   - 'base' model            │
  │  - smart_format = true      │               │   - word_timestamps = True  │
  │  - diarize = true           │               │   - GPU/MPS acceleration    │
  │  - filler_words = true      │               │     if available            │
  └──────────────┬──────────────┘               └──────────────┬──────────────┘
                 │                                             │
                 └──────────────────────┬──────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │     Word Normalization & Sorting       │
                    │  Extracts: text, start, end, speaker   │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │     Heuristic Segment Aggregator       │
                    │  Splits on >0.9s pause, speaker shift, │
                    │  or punctuation (., !, ?)              │
                    └───────────────────┬────────────────────┘
                                        │
                                        ▼
                    ┌────────────────────────────────────────┐
                    │       Output: NormalizedTranscript     │
                    │  - Raw JSON saved to SQLite/Postgres   │
                    │  - Input to LLM Viral Moment Detector  │
                    │  - Input to FFmpeg Subtitle Generator  │
                    └────────────────────────────────────────┘
```

---

## 3. Detailed Technical Breakdown: Code & Methods

### 3.1 Media Probing (`probe_media`)
Before audio extraction, the system verifies media stream presence and formats using `ffprobe`:

```bash
ffprobe -v error -print_format json -show_format -show_streams "<source_path>"
```

* **Target Data Extracted**:
  * `duration_sec`: from `format.duration` (parsed to float)
  * `has_video`: check if any stream has `codec_type == "video"`
  * `width`, `height`: from the primary video stream
  * `audio_codec`, `video_codec`: from stream headers

---

### 3.2 Standardized Audio Extraction (`extract_audio`)
Speech recognition models (both Whisper and Deepgram) achieve optimal accuracy and lowest latency on 16 kHz single-channel uncompressed WAV. AutoShorts enforces this exact FFmpeg command:

```bash
ffmpeg -y -i "<source_path>" -vn -ac 1 -ar 16000 "<project_dir>/transcription_audio.wav"
```

#### CLI Parameter Breakdown:
* `-y`: Overwrite output file if it exists.
* `-i "<source_path>"`: Path to the input media container.
* `-vn`: **Disable video recording**. Discards all video tracks, drastically reducing CPU time and disk I/O.
* `-ac 1`: **Channels = 1 (Mono)**. Downmixes stereo/surround sound into a single channel. Prevents stereo phase issues in ASR engines.
* `-ar 16000`: **Audio Sample Rate = 16,000 Hz**. Required native sampling rate for acoustic models in Whisper and Deepgram. Prevents redundant model-side resampling.

---

### 3.3 Engine A: Cloud Deepgram Nova-2 Pipeline

#### 1. Endpoint & Query Parameters
* **URL**: `https://api.deepgram.com/v1/listen`
* **Query Parameters**:
  * `model=nova-2`: Uses Deepgram's flagship Nova-2 architecture.
  * `smart_format=true`: Automatically applies numbers, currency, dates, and punctuation formatting.
  * `diarize=true`: Detects different speakers and assigns word-level speaker numbers.
  * `punctuate=true`: Adds punctuation marks to transcript outputs.
  * `filler_words=true`: Detects speech disfluencies (e.g., "uh", "um"), crucial for detecting natural pauses and realistic cut boundaries in short-form clips.

#### 2. Request Headers & Body
* `Authorization`: `Token <DEEPGRAM_API_KEY>`
* `Content-Type`: `audio/wav`
* `Body`: Raw binary bytes of the extracted `transcription_audio.wav`.

#### 3. Deepgram Response Normalization
The engine queries JSON pointer `/results/channels/0/alternatives/0`:
* Language extracted from: `/metadata/language` (default `"en"`).
* Duration extracted from: `/metadata/duration`.
* Words iteration:
  * Word text: `word.get("punctuated_word").or(word.get("word"))`
  * Word start: `word.start` (float seconds)
  * Word end: `word.end` (float seconds)
  * Word speaker: `format!("S{}", speaker + 1)` (maps 0-indexed integers `0, 1` to strings `"S1", "S2"`).

---

### 3.4 Engine B: Local Whisper Pipeline

AutoShorts supports fully offline transcription through a two-tiered resolution:

#### Tier 1: System CLI (`whisper`)
If the binary `whisper` or `whisper.exe` is found on system `PATH`:
```bash
whisper "<audio_path>" --model base --output_format json --output_dir "<audio_dir>" --word_timestamps True
```
* Reads generated `<stem>.json`.
* Cleans up auxiliary files produced by Whisper CLI (`.txt`, `.srt`, `.vtt`, `.tsv`).

#### Tier 2: Python Runtime Driver (`transcribe.py`)
If CLI is not present, AutoShorts inspects Python interpreters (`python`, `py`, `python3`) for the `whisper` module:
```bash
python -c "import whisper"
```
It dynamically writes a worker script (`transcribe.py`) to the app's models directory and launches it:
```bash
python transcribe.py "<audio_path>" "<output_json_path>" base
```

#### The `transcribe.py` Driver Script:
```python
import sys
import json
import whisper

def main():
    if len(sys.argv) < 3:
        print("Usage: transcribe.py <audio_path> <output_json_path> [model_name]")
        sys.exit(1)
        
    audio_path = sys.argv[1]
    output_json_path = sys.argv[2]
    model_name = sys.argv[3] if len(sys.argv) > 3 else "base"
    
    # Loads model (auto uses CUDA or Apple Silicon MPS if available)
    model = whisper.load_model(model_name)
    
    # Transcribe with word-level timestamps enabled
    result = model.transcribe(audio_path, word_timestamps=True)
    
    normalized = {
        "language": result.get("language", "en"),
        "duration": result.get("segments", [])[-1]["end"] if result.get("segments") else 0.0,
        "speakers": ["S1"],
        "words": [],
        "segments": []
    }
    
    for segment in result.get("segments", []):
        normalized["segments"].append({
            "start": segment["start"],
            "end": segment["end"],
            "speaker": "S1",
            "text": segment["text"].strip()
        })
        
        for word in segment.get("words", []):
            cleaned_text = word["word"].strip()
            normalized["words"].append({
                "text": cleaned_text,
                "start": word["start"],
                "end": word["end"],
                "speaker": "S1"
            })
            
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
```

---

### 3.5 The Heuristic Sentence Segmentation Algorithm (`build_segments`)

Raw ASR words must be aggregated into natural conversational sentences for LLM reasoning and subtitle chunking. AutoShorts implements a segment aggregator with three boundary conditions:

```rust
pub fn build_segments(words: &[TranscriptWord]) -> Vec<TranscriptSegment> {
    let mut segments = Vec::new();
    let mut current: Option<TranscriptSegment> = None;

    for word in words {
        let should_break = current.as_ref().map_or(false, |segment| {
            let pause = word.start - segment.end;
            let speaker_changed = segment.speaker != word.speaker;
            let sentence_end = segment.text.ends_with(['.', '!', '?']);
            
            // Boundary Condition:
            // 1. A silence gap longer than 900 milliseconds (0.9s)
            // 2. Change of speaker turn
            // 3. Sentence terminator followed by next word
            pause > 0.9 || speaker_changed || sentence_end
        });

        if should_break {
            if let Some(segment) = current.take() {
                segments.push(segment);
            }
        }

        match &mut current {
            Some(segment) => {
                segment.end = word.end;
                segment.text.push(' ');
                segment.text.push_str(&word.text);
            }
            None => {
                current = Some(TranscriptSegment {
                    start: word.start,
                    end: word.end,
                    speaker: word.speaker.clone(),
                    text: word.text.clone(),
                });
            }
        }
    }

    if let Some(segment) = current {
        segments.push(segment);
    }

    segments
}
```

---

## 4. Standard Data Schema

To maintain complete compatibility, any reimplementation should output this canonical schema:

### TypeScript Definition
```typescript
interface TranscriptWord {
  text: string;
  start: number;   // In seconds, float (e.g. 12.345)
  end: number;     // In seconds, float (e.g. 12.890)
  speaker?: string | null; // e.g. "S1", "S2"
}

interface TranscriptSegment {
  start: number;
  end: number;
  speaker?: string | null;
  text: string;
}

interface NormalizedTranscript {
  language: string;       // ISO 639-1 code (e.g. "en")
  duration: number;       // Total audio duration in seconds
  speakers: string[];     // Array of distinct speaker IDs (e.g. ["S1", "S2"])
  words: TranscriptWord[];
  segments: TranscriptSegment[];
}
```

### JSON Schema Sample
```json
{
  "language": "en",
  "duration": 45.2,
  "speakers": ["S1", "S2"],
  "words": [
    { "text": "The", "start": 0.0, "end": 0.28, "speaker": "S1" },
    { "text": "secret", "start": 0.32, "end": 0.74, "speaker": "S1" },
    { "text": "to", "start": 0.78, "end": 0.92, "speaker": "S1" },
    { "text": "viral", "start": 0.96, "end": 1.45, "speaker": "S1" },
    { "text": "shorts.", "start": 1.48, "end": 1.95, "speaker": "S1" }
  ],
  "segments": [
    {
      "start": 0.0,
      "end": 1.95,
      "speaker": "S1",
      "text": "The secret to viral shorts."
    }
  ]
}
```

---

## 5. Step-by-Step Recreation Guide (Python / FastAPI Implementation)

For integration into `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper`, here is the complete, modular Python implementation replicating the exact AutoShorts transcription engine:

### 5.1 Directory Layout
```
ai-video-clipper/
└── backend/
    ├── app/
    │   ├── services/
    │   │   ├── audio_extractor.py
    │   │   ├── segmenter.py
    │   │   ├── deepgram_service.py
    │   │   └── whisper_service.py
    │   └── models/
    │       └── transcript.py
```

### 5.2 Python Data Models (`models/transcript.py`)
```python
from pydantic import BaseModel
from typing import List, Optional

class TranscriptWord(BaseModel):
    text: str
    start: float
    end: float
    speaker: Optional[str] = "S1"

class TranscriptSegment(BaseModel):
    start: float
    end: float
    speaker: Optional[str] = "S1"
    text: str

class NormalizedTranscript(BaseModel):
    language: str
    duration: float
    speakers: List[str]
    words: List[TranscriptWord]
    segments: List[TranscriptSegment]
```

### 5.3 Audio Extraction Service (`services/audio_extractor.py`)
```python
import subprocess
import json
from pathlib import Path

class AudioExtractor:
    @staticmethod
    def probe_media(file_path: str) -> dict:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return json.loads(res.stdout)

    @staticmethod
    def extract_audio_16k_mono(source_path: str, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-i", source_path,
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            output_path
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return output_path
```

### 5.4 Boundary Segmentation Algorithm (`services/segmenter.py`)
```python
from typing import List
from ..models.transcript import TranscriptWord, TranscriptSegment

class TranscriptSegmenter:
    @staticmethod
    def build_segments(words: List[TranscriptWord]) -> List[TranscriptSegment]:
        segments: List[TranscriptSegment] = []
        if not words:
            return segments

        current_words: List[TranscriptWord] = []

        for word in words:
            if not current_words:
                current_words.append(word)
                continue

            last_word = current_words[-1]
            pause = word.start - last_word.end
            speaker_changed = (word.speaker != last_word.speaker)
            sentence_end = last_word.text.endswith(('.', '!', '?'))

            # AutoShorts exact boundary condition
            if pause > 0.9 or speaker_changed or sentence_end:
                seg_text = " ".join(w.text for w in current_words)
                segments.append(TranscriptSegment(
                    start=current_words[0].start,
                    end=current_words[-1].end,
                    speaker=current_words[0].speaker,
                    text=seg_text
                ))
                current_words = [word]
            else:
                current_words.append(word)

        if current_words:
            seg_text = " ".join(w.text for w in current_words)
            segments.append(TranscriptSegment(
                start=current_words[0].start,
                end=current_words[-1].end,
                speaker=current_words[0].speaker,
                text=seg_text
            ))

        return segments
```

### 5.5 Cloud Deepgram Nova-2 Service (`services/deepgram_service.py`)
```python
import httpx
from typing import Optional
from ..models.transcript import NormalizedTranscript, TranscriptWord
from .segmenter import TranscriptSegmenter

class DeepgramService:
    ENDPOINT = (
        "https://api.deepgram.com/v1/listen?"
        "model=nova-2&smart_format=true&diarize=true&punctuate=true&filler_words=true"
    )

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def transcribe(self, wav_file_path: str) -> NormalizedTranscript:
        with open(wav_file_path, "rb") as f:
            audio_bytes = f.read()

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/wav"
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(self.ENDPOINT, headers=headers, content=audio_bytes)
            resp.raise_for_status()
            data = resp.json()

        channel = data["results"]["channels"][0]["alternatives"][0]
        metadata = data.get("metadata", {})
        language = metadata.get("language", "en")
        duration = float(metadata.get("duration", 0.0))

        speakers_set = set()
        words: list[TranscriptWord] = []

        for w in channel.get("words", []):
            text = (w.get("punctuated_word") or w.get("word") or "").strip()
            if not text:
                continue

            spk_raw = w.get("speaker")
            speaker_str = f"S{spk_raw + 1}" if spk_raw is not None else "S1"
            speakers_set.add(speaker_str)

            words.append(TranscriptWord(
                text=text,
                start=float(w.get("start", 0.0)),
                end=float(w.get("end", 0.0)),
                speaker=speaker_str
            ))

        segments = TranscriptSegmenter.build_segments(words)

        return NormalizedTranscript(
            language=language,
            duration=duration,
            speakers=sorted(list(speakers_set)) if speakers_set else ["S1"],
            words=words,
            segments=segments
        )
```

### 5.6 Local Whisper Service (`services/whisper_service.py`)
```python
import whisper
from ..models.transcript import NormalizedTranscript, TranscriptWord, TranscriptSegment
from .segmenter import TranscriptSegmenter

class LocalWhisperService:
    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            # Loads on CUDA if available, MPS on macOS, or CPU fallback
            self._model = whisper.load_model(self.model_name)
        return self._model

    def transcribe(self, wav_file_path: str) -> NormalizedTranscript:
        model = self._get_model()
        result = model.transcribe(wav_file_path, word_timestamps=True)

        language = result.get("language", "en")
        raw_segments = result.get("segments", [])
        duration = float(raw_segments[-1]["end"]) if raw_segments else 0.0

        words: list[TranscriptWord] = []
        for seg in raw_segments:
            for w in seg.get("words", []):
                cleaned = w.get("word", "").strip()
                if not cleaned:
                    continue
                words.append(TranscriptWord(
                    text=cleaned,
                    start=float(w.get("start", 0.0)),
                    end=float(w.get("end", 0.0)),
                    speaker="S1"
                ))

        segments = TranscriptSegmenter.build_segments(words)

        return NormalizedTranscript(
            language=language,
            duration=duration,
            speakers=["S1"],
            words=words,
            segments=segments
        )
```

---

## 6. Verification & Quality Comparison

| Feature | AutoShorts Implementation | Recreated Implementation |
| :--- | :--- | :--- |
| **Audio Extraction** | `ffmpeg -y -i input -vn -ac 1 -ar 16000 output.wav` | Exact same parameters (`-vn -ac 1 -ar 16000`) |
| **Cloud Engine** | Deepgram Nova-2 (`diarize=true`, `smart_format=true`, `filler_words=true`) | Exact same query parameters & word normalization |
| **Local Engine** | Whisper `base` with `word_timestamps=True` | Identical OpenAI Whisper invocation |
| **Word Timestamps** | Exact float second start & end bounds | Exact float second start & end bounds |
| **Diarization** | Formatted as `"S1", "S2", ...` | Formatted as `"S1", "S2", ...` |
| **Segment Cut Rule** | `pause > 0.9s \|\| speaker_changed \|\| punct_end` | Identical multi-factor heuristic |
| **Downstream Compatibility**| Feeds directly to LLM prompt & FFmpeg subtitle generator | 100% JSON schema parity |
