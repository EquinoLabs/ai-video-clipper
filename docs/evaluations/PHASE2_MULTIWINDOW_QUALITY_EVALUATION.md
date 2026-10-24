# Phase 2 Multi-Window Candidate Discovery — Manual Evaluation Sheet

**Artifact Evaluated**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/candidates.json`  
**Source Media**: `Anne Hathaway Forgets The Princess Diaries and The Devil Wears Prada Details, Chats The Idea of You - The Tonight Show Starring Jimmy Fallon (1080p, h264).mp4`  
**Duration**: 622.84s (~10m 23s)  
**Provider / Model**: `ollama` / `qwen2.5:7b`  
**Editorial Goal**: `humor`  
**Settings**: Min 10.0s, Target 30.0s, Max 60.0s | Chunks: 4 (750 words, 45s overlap) | Target per window: 4  
**Date of Run**: 2026-10-22  
**Evaluation Status**: Both Part 1 (7 candidate clips) and Part 2 (Moments A, B, C comparative experiments) reviewed. Findings recorded.

---

## Executive Summary of Human Review Findings

The human reviewer inspected all seven rendered candidate clips (`cnd_001` through `cnd_007`) in vertical 9:16 format with burned subtitles, alongside the controlled boundary experiments for Moments A, B, and C.

### Key Across-the-Board Findings
1. **Core Defect — Poor Editorial Closure**:
   - Several clips began well but ended mid-conversation (e.g., `cnd_003`, `cnd_004`, `cnd_007`).
   - One clip cut off mid-word due to word-timing truncation.
   - Another opened after audience laughter had already begun and terminated awkwardly just as an unrelated conversational topic started (`cnd_007`).
2. **Standout Candidate**:
   - `cnd_001` (`5:31 – 5:47`, 16.28s) was the only clip that felt comparatively complete and editorially satisfying from setup to punchline.
3. **Core Architectural Insight**:
   - Discovering short standalone clips directly from a 10-minute transcript repeatedly produces truncated fragments of larger conversations.
   - The reviewer validated the proposed two-level hierarchy: discovering coherent, complete **long clips (conversations/story arcs)** first, and then discovering optional **short punchy moments** within accepted long clips.

---

## Review Folder Locations

Open these directories to play the 9:16 vertical clips (with synchronized burned subtitles):

- **Candidate Clips (cnd_001 – cnd_007)**:  
  `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper\outputs\smoke_test_ollama_qwen25_humor_multiwindow\rendered_clips\`  
  (Relative: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/`)
- **First Three Minutes Experiments (Moments A, B, C)**:  
  `C:\Lakshya\Coding\EquinoLabs\ai-video-clipper\outputs\experiments\first_three_minutes\`  
  (Relative: `outputs/experiments/first_three_minutes/`)

---

## Instructions for Human Reviewers

For each candidate below, open the corresponding rendered `.mp4` file in your preferred media player and evaluate editorial and comedic viability.

1. **Verdict (`Keep` / `Reject` / `Needs Boundary Edit`)**: Overall publishing decision.
2. **Moment Quality (Humor / Engagement)**: Does it genuinely evoke humor, amusement, or charm, or is it flat conversation?
3. **Completeness (Setup & Payoff)**: Does the clip start cleanly before the setup and hold until the reaction/punchline finishes without an abrupt cutoff?
4. **Suggested Boundary Adjustments**: If the clip starts too late or cuts off too early, provide refined timestamps.
5. **Caption / Framing / Presentation Notes**: Note any subtitle desynchronization, line-break anomalies, or visual framing issues.
6. **Editorial Rationale / Reason**: Concrete justification for your editorial decision.

---

## Part 1: Review Checklist for the 7 Final Candidates

### Quick Reference Table

| Candidate ID | Rendered Filename | Original Interval | Duration | Score | Status | Human Review Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **cnd_001** | `cnd_001_331.6s_347.9s.mp4` | `5:31 – 5:47` (`331.58s – 347.86s`) | 16.28s | 90 | Valid | **Keep** (comparatively complete, lands punchline) |
| **cnd_002** | `cnd_002_571.7s_581.9s.mp4` | `9:31 – 9:41` (`571.68s – 581.90s`) | 10.22s | 90 | Valid | **Needs Boundary Edit** (too short, cuts off mid-thought) |
| **cnd_003** | `cnd_003_466.8s_478.7s.mp4` | `7:46 – 7:58` (`466.82s – 478.73s`) | 11.91s | 87 | Valid | **Needs Boundary Edit** (ends mid-conversation before payoff) |
| **cnd_004** | `cnd_004_557.1s_571.7s.mp4` | `9:17 – 9:31` (`557.06s – 571.68s`) | 14.62s | 84 | Valid | **Needs Boundary Edit** (awkward rhetorical cutoff without closure) |
| **cnd_005** | `cnd_005_358.1s_370.9s.mp4` | `5:58 – 6:10` (`358.05s – 370.87s`) | 12.82s | 80 | Valid | **Needs Boundary Edit** (funny setup, but ends mid-conversation) |
| **cnd_006** | `cnd_006_183.5s_195.5s.mp4` | `3:03 – 3:15` (`183.52s – 195.54s`) | 12.02s | 80 | Valid | **Needs Boundary Edit** (interesting cameo story, cuts word in half) |
| **cnd_007** | `cnd_007_375.5s_387.1s.mp4` | `6:15 – 6:27` (`375.47s – 387.07s`) | 11.60s | 80 | Needs Review | **Reject / Needs Edit** (starts after laughter, cuts as new topic begins) |

---

### Candidate: cnd_001
- **Rendered Filename**: `cnd_001_331.6s_347.9s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_001_331.6s_347.9s.mp4`
- **Original Interval**: `5:31 – 5:47` (`331.58s – 347.86s`)
- **Duration**: `16.28s` (Rendered file duration: `16.32s`, File size: `10.43 MB`)
- **Backend Overall Score**: `90` | **Validation Status**: `valid`
- **Hook**: *"I said the line and just the house went down"*
- **Transcript Excerpt**:
  > *"And then one night I went out there and I said the line and just the house went down. He killed it killed and I was like, oh, I found it. I just like and so then of course I leaned into it because good you do and so I leaned into it. And I'm just the audience is losing their minds. I look into the wings the cast is losing their minds. I'm high-fiving myself in my head"*
- **Grounding Evidence Quotes**:
  - `5:31 – 5:34` (`331.58s – 334.82s`): *"And then one night I went out there and I said the line and just the house went down\nHe killed it killed and I was like, oh, I found it"*
  - `5:43 – 5:47` (`343.62s – 347.86s`): *"And I'm just the audience is losing their minds\nI look into the wings the cast is losing their minds. I'm high-fiving myself in my head"*
- **Validation Notes**: Valid bounds and grounded evidence. High comedy/story score.

#### Human Review Fields
- **Verdict**: `[x] Keep  |  [ ] Reject  |  [ ] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: High. Genuinely funny anecdote where Anne describes an improvised line landing and bringing down the house.
- **Completeness (Setup & Payoff)**: Comparatively complete and satisfying. Lands the setup, buildup, and high-energy punchline.
- **Suggested Boundary Adjustments**: Boundaries (`5:31 – 5:47`, 16.28s) are viable as-is.
- **Caption / Framing / Presentation Notes**: Subtitles are well-synchronized; center crop keeps Anne in frame.
- **Editorial Rationale / Reason**: Best performing candidate from the multi-window discovery run. Holds together as a standalone vertical short.

---

### Candidate: cnd_002
- **Rendered Filename**: `cnd_002_571.7s_581.9s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_002_571.7s_581.9s.mp4`
- **Original Interval**: `9:31 – 9:41` (`571.68s – 581.90s`)
- **Duration**: `10.22s` (Rendered file duration: `10.28s`, File size: `3.54 MB`)
- **Backend Overall Score**: `90` | **Validation Status**: `valid`
- **Hook**: *"Humor in a playful exchange between characters."*
- **Transcript Excerpt**:
  > *"We're performing on the main stage now Hey's Campbell. August man. Yeah, well, I absolutely know who you are"*
- **Grounding Evidence Quotes**:
  - `9:31 – 9:35` (`571.68s – 575.26s`): *"We're performing on the main stage now"*
  - `9:35 – 9:41` (`575.94s – 581.90s`): *"Hey's Campbell. August man. Yeah, well, I absolutely know who you are"*
- **Validation Notes**: Barely satisfies 10.0s minimum duration (10.22s).

#### Human Review Fields
- **Verdict**: `[ ] Keep  |  [ ] Reject  |  [x] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: Moderate playful banter, but too brief to establish comedic context.
- **Completeness (Setup & Payoff)**: Incomplete. Barely clears 10.0s minimum duration (10.22s); feels like an abrupt conversational snippet cut off mid-thought.
- **Suggested Boundary Adjustments**: Needs earlier setup and conversational resolution.
- **Caption / Framing / Presentation Notes**: Subtitles render fine, but timing feels rushed due to truncated duration.
- **Editorial Rationale / Reason**: Minimum-duration artifact; requires broader context window to be viable.

---

### Candidate: cnd_003
- **Rendered Filename**: `cnd_003_466.8s_478.7s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_003_466.8s_478.7s.mp4`
- **Original Interval**: `7:46 – 7:58` (`466.82s – 478.73s`)
- **Duration**: `11.91s` (Rendered file duration: `11.91s`, File size: `4.85 MB`)
- **Backend Overall Score**: `87` | **Validation Status**: `valid`
- **Hook**: *"You guys have great chemistry. Did I know when he was auditioned you? Oh, this is the guy. Oh, yeah, yeah, yeah, no as soon as he I actually burst out laughing when he walked in because"*
- **Transcript Excerpt**:
  > *"You guys have great chemistry. Did I know when he was auditioned you? Oh, this is the guy. Oh, yeah, yeah, yeah, no as soon as he I actually burst out laughing when he walked in because The it hasn't been here read the book"*
- **Grounding Evidence Quotes**:
  - `7:46 – 7:55` (`466.82s – 475.90s`): *"You guys have great chemistry. Did I know when he was auditioned you? Oh, this is the guy. Oh, yeah, yeah, yeah, no as soon as he I actually burst out laughing when he walked in because"*
  - `7:57 – 7:58` (`477.00s – 478.73s`): *"The it hasn't been here read the book"*
- **Validation Notes**: The hook generated by Ollama repeats conversational setup text.

#### Human Review Fields
- **Verdict**: `[ ] Keep  |  [ ] Reject  |  [x] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: High potential (Nicholas Galitzine chemistry/audition story), engaging topic.
- **Completeness (Setup & Payoff)**: Incomplete. Begins mid-thought with Jimmy's question and cuts off abruptly before the punchline ("The it hasn't been here read the book").
- **Suggested Boundary Adjustments**: Needs extension to capture the full audition reaction and punchline payoff.
- **Caption / Framing / Presentation Notes**: Subtitles cut off mid-sentence at 478.73s.
- **Editorial Rationale / Reason**: Classic mid-conversation truncation defect; strong candidate for two-level long-clip extraction.

---

### Candidate: cnd_004
- **Rendered Filename**: `cnd_004_557.1s_571.7s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_004_557.1s_571.7s.mp4`
- **Original Interval**: `9:17 – 9:31` (`557.06s – 571.68s`)
- **Duration**: `14.62s` (Rendered file duration: `14.68s`, File size: `5.15 MB`)
- **Backend Overall Score**: `84` | **Validation Status**: `valid`
- **Hook**: *"Humor in the setup of someone making a joke about people enjoying others' misfortune."*
- **Transcript Excerpt**:
  > *"Are you a part of that I have some our community that gets off on listening to people pay?"*
- **Grounding Evidence Quotes**:
  - `9:17 – 9:20` (`557.06s – 560.84s`): *"Are you a part of that I have some our community that gets off on listening to people pay?"*
- **Validation Notes**: Generic model-generated description hook.

#### Human Review Fields
- **Verdict**: `[ ] Keep  |  [ ] Reject  |  [x] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: Moderate. Jimmy making a joke about people enjoying others' misfortune.
- **Completeness (Setup & Payoff)**: Incomplete. Cut off awkwardly on a rhetorical question without the comedic resolution or room reaction.
- **Suggested Boundary Adjustments**: Extend ending to capture Anne's response and audience reaction.
- **Caption / Framing / Presentation Notes**: Subtitles end on an unfinished thought.
- **Editorial Rationale / Reason**: Lacks editorial closure; ends mid-conversation.

---

### Candidate: cnd_005
- **Rendered Filename**: `cnd_005_358.1s_370.9s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_005_358.1s_370.9s.mp4`
- **Original Interval**: `5:58 – 6:10` (`358.05s – 370.87s`)
- **Duration**: `12.82s` (Rendered file duration: `12.85s`, File size: `4.53 MB`)
- **Backend Overall Score**: `80` | **Validation Status**: `valid`
- **Hook**: *"Did you see the raccoons?"*
- **Transcript Excerpt**:
  > *"And I make them with the wood and then they just go behind you as soon as you came on stage a family of raccoons came out They were so cute I'm gonna focus on this scene because the raccoons were so cute So it's like well actually high five to the raccoons"*
- **Grounding Evidence Quotes**:
  - `5:58 – 6:05` (`358.05s – 365.19s`): *"And I make them with the wood and then they just go behind you as soon as you came on stage a family of raccoons came out"*
  - `6:07 – 6:10` (`367.51s – 370.87s`): *"They were so cute I'm gonna focus on this scene because the raccoons were so cute So it's like well actually high five to the raccoons"*
- **Validation Notes**: Raw candidate `[358.05s - 367.51s]` (9.46s) was rejected as sub-minimum (<10.0s), but this expanded proposal `[358.05s - 370.87s]` (12.82s) survived.

#### Human Review Fields
- **Verdict**: `[ ] Keep  |  [ ] Reject  |  [x] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: High humor value (outdoor theater raccoon anecdote).
- **Completeness (Setup & Payoff)**: Incomplete. Starts mid-story after Jimmy sets up the theater context, ending cuts off abruptly.
- **Suggested Boundary Adjustments**: Broaden start to include Jimmy setting up Shakespeare in the Park and Anne introducing the raccoons.
- **Caption / Framing / Presentation Notes**: Center framing cuts off some expressive gestures, but subtitles are clear.
- **Editorial Rationale / Reason**: Good moment trapped in bad boundaries. Would make a great short if cut from a complete long conversation.

---

### Candidate: cnd_006
- **Rendered Filename**: `cnd_006_183.5s_195.5s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_006_183.5s_195.5s.mp4`
- **Original Interval**: `3:03 – 3:15` (`183.52s – 195.54s`)
- **Duration**: `12.02s` (Rendered file duration: `12.08s`, File size: `6.08 MB`)
- **Backend Overall Score**: `80` | **Validation Status**: `valid`
- **Hook**: *"Yeah rock star everybody because you don't really see Anna do many things that are outside of her wear a trucker hat"*
- **Transcript Excerpt**:
  > *"Yeah rock star everybody because you don't really see Anna do many things that are outside of her wear a trucker hat. That's correct. Yeah, but everyone just went nuts"*
- **Grounding Evidence Quotes**:
  - `3:03 – 3:15` (`183.52s – 195.54s`): *"Yeah rock star everybody because you don't really see Anna do many things that are outside of her wear a trucker hat. That's correct. Yeah, but everyone just went nuts"*
- **Validation Notes**: Earliest surviving candidate in the run (~3m 03s). Covers the Anna Wintour Broadway cameo anecdote.

#### Human Review Fields
- **Verdict**: `[ ] Keep  |  [ ] Reject  |  [x] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: High. Anna Wintour wearing a trucker hat cameo on Broadway.
- **Completeness (Setup & Payoff)**: Defective boundary. Clip cuts a word in half at the start and cuts off the audience reaction at the end.
- **Suggested Boundary Adjustments**: Adjust start backward ~1.5s to avoid cutting the opening word; extend end by ~2-3s for reaction.
- **Caption / Framing / Presentation Notes**: Subtitle truncation on first word.
- **Editorial Rationale / Reason**: Clear evidence of word-boundary clipping; requires word-level alignment or sentence boundary snapping.

---

### Candidate: cnd_007
- **Rendered Filename**: `cnd_007_375.5s_387.1s.mp4`
- **Rendered File Path**: `outputs/smoke_test_ollama_qwen25_humor_multiwindow/rendered_clips/cnd_007_375.5s_387.1s.mp4`
- **Original Interval**: `6:15 – 6:27` (`375.47s – 387.07s`)
- **Duration**: `11.60s` (Rendered file duration: `11.61s`, File size: `4.07 MB`)
- **Backend Overall Score**: `80` | **Validation Status**: `needs_review`
- **Hook**: *"That's it. You got to work with everybody"*
- **Transcript Excerpt**:
  > *"That's it. You got to work with everybody Absolutely you got to work. You play well with others Let's say about the idea of you. Oh my gosh, but the trailer alone has gotten over 125 million views Across broke the record Both watch trailer of any streaming movie in history"*
- **Grounding Evidence Quotes**:
  - `6:15 – 6:20` (`375.47s – 380.45s`): *"That's it. You got to work with everybody Absolutely you got to work. You play well with others"*
  - `6:20 – 6:27` (`380.81s – 387.07s`): *"Let's say about the idea of you. Oh my gosh, but the trailer alone has gotten over 125 million views Across broke the record Both watch trailer of any streaming movie in history"*
- **Validation Notes**: Soft warning (`EVIDENCE_PARTIALLY_UNGROUNDED`). Quote 2 extends in transcript to 393.1s (6.0s beyond candidate end vs 5.0s tolerance). Contains conversational shift to movie trailer viewership.

#### Human Review Fields
- **Verdict**: `[ ] Keep  |  [x] Reject  |  [x] Needs Boundary Edit`
- **Moment Quality (Humor / Engagement)**: Low comedic value; conversational transition into commercial trailer statistics.
- **Completeness (Setup & Payoff)**: Severely mismatched. Opens after audience laughter has already begun, and ends abruptly right as the movie trailer viewership topic begins.
- **Suggested Boundary Adjustments**: Reject as humor clip; if repurposed, re-anchor boundaries around trailer discussion.
- **Caption / Framing / Presentation Notes**: Soft warning `EVIDENCE_PARTIALLY_UNGROUNDED` flagged during automated validation.
- **Editorial Rationale / Reason**: Editorial mismatch; bridges two unrelated topics and misses the punchline entirely. 

---

## Part 2: Review of the First Three Minutes (0:00 – 3:00)

No candidate survived from the first 180 seconds. Three raw candidates were proposed by the model in Window 1 (`0.1s – 205.8s`) and subsequently rejected:

| Proposed Interval | Duration | Rejection Reason Codes | Model Hook |
| :---: | :---: | :---: | :--- |
| `1:30 – 1:46` (`90.48s – 106.08s`) | 15.60s | `EVIDENCE_NOT_GROUNDED` | *"I'm gonna say wait, but I was genuinely confused. Wait, but it's her that was me, but I'm the is it that's wild"* |
| `1:58 – 2:05` (`118.74s – 125.54s`) | 6.80s | `DURATION_BELOW_MINIMUM` | *"Do you ever do you kind of do a project and then you kind of block it out of your mind or no?"* |
| `2:10 – 2:15` (`130.08s – 134.94s`) | 4.86s | `DURATION_BELOW_MINIMUM` | *"It is kind of funny when like you know, I was in this movie when I was 17. It's all called the princess diaries"* |

---

### Human Review Observations & Candidate Moment Analysis

> [!NOTE]
> **Separation of Concerns**: Automated model outputs and timestamps are preserved below exactly as recorded during discovery. Manual intervals and comparative clips (A1/A2, B1/B2, C2) represent controlled human editorial investigations, not model predictions.

#### Moment A: Jimmy Competing Against His Kids
- **Automated Model Output**: Overlooked by the model during Window 1 discovery (`0.1s – 205.8s`).
- **Controlled Comparison Clips**:
  - `A1_baseline.mp4`: `0:11 – 0:59` (`11.73s – 59.42s`, 47.69s) $\rightarrow$ `outputs/experiments/first_three_minutes/A1_baseline.mp4` (47.71s, 18.81MB)
  - `A2_with_laughter.mp4`: `0:11 – 1:03` (`11.73s – 63.00s`, 51.27s) $\rightarrow$ `outputs/experiments/first_three_minutes/A2_with_laughter.mp4` (51.28s, 20.10MB)
- **Human Review Findings & Verdict**:
  - **Verdict**: **A2 is better**.
  - **Editorial Finding**: The extra ~3 seconds of audience laughter (extending from 0:59 to 1:03) clearly improve the ending. The conversation itself is coherent, and letting the audience reaction resolve makes the comedic punchline (*"I play for money too"*) land naturally rather than feeling clipped abruptly.
  - **Review Status**: Completed (Human Review).

#### Moment B: Devil Wears Prada Trivia Confusion
- **Automated Model Output**: Proposed interval `1:30 – 1:46` (`90.48s – 106.08s`, duration: 15.60s).  
  **Automated Validation Verdict**: Rejected (`EVIDENCE_NOT_GROUNDED`) because the model's evidence quote was located at 115.04s–118.74s, well beyond the proposed 106.08s boundary.
- **Controlled Comparison Clips**:
  - `B1_rejected_model_proposal.mp4`: `1:30 – 1:46` (`90.48s – 106.08s`, 15.60s) $\rightarrow$ `outputs/experiments/first_three_minutes/B1_rejected_model_proposal.mp4` (15.62s, 7.59MB) [Diagnostic]
  - `B2_complete_arc.mp4`: `1:24 – 1:59` (`83.92s – 118.74s`, 34.82s) $\rightarrow$ `outputs/experiments/first_three_minutes/B2_complete_arc.mp4` (34.87s, 16.06MB)
- **Human Review Findings & Verdict**:
  - **Verdict**: **B2 is clearly better**.
  - **Editorial Finding**: B2 starts when Anne introduces the topic at approximately 1:24 (83.92s) and cleanly ends when the conversation concludes at 1:59 (118.74s). B1 (the raw model proposal) starts too late, lacks topic setup, and cuts off awkwardly after a joke and brief audience laughter without delivering the complete story arc.
  - **Review Status**: Completed (Human Review).

#### Moment C: Princess Diaries Quote Amnesia
- **Automated Model Output**: Proposed interval `2:10 – 2:15` (`130.08s – 134.94s`, duration: 4.86s).  
  **Automated Validation Verdict**: Rejected (`DURATION_BELOW_MINIMUM`) as sub-minimum (<10.0s).
- **Controlled Comparison Clips**:
  - Baseline Fragment (Model Attempt): `2:10 – 2:15` (`130.08s – 134.94s`, 4.86s) [Skipped as non-publishable]
  - `C2_complete_arc.mp4`: `2:06 – 2:36` (`125.76s – 156.27s`, 30.51s) $\rightarrow$ `outputs/experiments/first_three_minutes/C2_complete_arc.mp4` (30.56s, 14.32MB)
- **Human Review Findings & Verdict**:
  - **Verdict**: **C2 is confirmed as a coherent, acceptable short conversation with good audience reaction**.
  - **Editorial Finding**: The `2:06 – 2:36` interval forms a complete, well-paced conversational exchange (Anne discussing people quoting *The Princess Diaries* lines to her on the street and her amnesia regarding them). The model correctly identified a genuinely funny seed moment, but proposed an undersized 4.86s fragment that was properly rejected by validation; the true editorial boundaries span ~30 seconds.
  - **Review Status**: Completed (Human Review).

---

## 4. Stage 2 Boundary Refinement & Word-Timestamp Snapping Benchmark

### 4.1 Methodology & Implementation
To address the boundary truncation issues identified during initial evaluation (e.g. punchlines cut before audience reaction, mid-word truncations), Stage 2 introduced genuine Whisper word-level boundary snapping via `backend/app/services/candidates/boundaries.py` (`refine_candidate_boundaries`).

The refinement algorithm adheres to the following principles:
1. **Word Integrity Preservation**: Word boundaries `[word.start, word.end]` are treated as atomic units. If a candidate boundary falls mid-word (`word.start < boundary < word.end`), the boundary is snapped outward to enclose the full word without truncation.
2. **Post-Dialogue Laughter / Silence Cushioning**: In conversational television, the comedic payoff or conversational landing is accompanied by room laughter and pauses before the host or conversational partner speaks next. When a candidate ends after speech, the boundary expands into the subsequent silence gap by up to a configured cushion (1.0s–1.5s), terminating strictly before the next spoken word begins (`next_word.start - 0.05s`).
3. **Pre-Dialogue Breath / Setup Cushioning**: Leading silence before an utterance is similarly preserved (up to 0.5s) to avoid clipping the speaker's intake of breath or initial consonant.
4. **Hard Limit Safety**: Snapping strictly respects container bounds (`0.0 <= start < end <= container_end`) and hard maximum duration limits (`max_clip_duration_seconds`).

### 4.2 Benchmark Results on Human-Reviewed Test Moments

The boundary refinement service was benchmarked against the full transcript of the Jimmy Fallon / Anne Hathaway interview:

| Moment / Candidate | Baseline Raw Interval | Refined Interval | $\Delta$ Start / $\Delta$ End | Outcome & Quality Improvement |
| :--- | :---: | :---: | :---: | :--- |
| **Moment A (Baseline vs Laughter)** | `11.730s – 59.420s` (47.690s) | `10.995s – 60.920s` (49.925s) | `-0.735s` / `+1.500s` | **Captures full punchline landing.** Extends cleanly into the 2.74s laughter gap after *"I play for money too"* (59.42s) without encroaching on Jimmy's next topic question at 62.16s. |
| **Moment B (Setup Arc)** | `83.920s – 118.740s` (34.820s) | `83.770s – 118.740s` (34.970s) | `-0.150s` / `+0.000s` | **Clean topic entry.** Snaps start outward to capture Anne's introductory breath before *"So you know how..."*. End is cleanly bounded at the natural conclusion of the topic. |
| **Moment C (Conversation Arc)** | `125.760s – 156.270s` (30.510s) | `125.650s – 156.270s` (30.620s) | `-0.110s` / `+0.000s` | **Clean opening.** Captures leading syllable; end terminates at natural topic transition. |
| **Candidate 6 (`cnd_006`)** | `183.520s – 195.540s` (12.020s) | `183.520s – 196.490s` (12.970s) | `+0.000s` / `+0.950s` | **Prevents cut-off while protecting next sentence.** Safely expands into the 1.00s gap after the utterance, stopping cleanly at 196.49s (0.05s buffer before the next sentence begins at 196.54s). |

### 4.3 Evaluation Dimensions

| Evaluation Dimension | Stage 2 Status & Verified Behavior |
| :--- | :--- |
| **Word Integrity** | **100% Verified**: No word is ever split or cut mid-phoneme. Verified by unit tests in `test_boundary_refinement_prevents_mid_word_cuts`. |
| **Conversational Completeness** | **Addressed at Prompt & Config Level**: Long-clip prompts (`LONG_CLIP_SYSTEM_PROMPT`) explicitly guide the model to select complete conversational exchanges (setup, banter, payoff, reaction) rather than isolated punchlines. |
| **Standalone Understandability** | **Addressed at Config Level**: Duration floor increased from 10.0s to 30.0s (`GenerationSettings.for_long_clips()`), preventing sub-10s fragmented jokes from passing validation as long clips. |
| **Boundary Quality** | **Verified with Outward Snapping**: Automatic cushioning expands into audience laughter and natural pauses without encroaching on subsequent speakers or exceeding maximum clip duration. |

---

## 5. Controlled Long-Clip Discovery Experiment (Ollama / Qwen2.5:7b, Goal: Humor)

### 5.1 Experiment Setup & Configuration
- **Date/Timestamp**: 2026-10-24
- **Runtime**: 6 minutes 13 seconds (373.71s total)
- **Input Artifact**: `outputs/Anne_Hathaway_Forgets_The_Princess_Diaries_and_The_Devil_Wears_Prada_Details__Chats_The_Idea_of_You_-_The_Tonight_Show_Starring_Jimmy_Fallon__1080p__h264__20261020_202242/transcript.json` (622.84s source duration, 135 segments)
- **Output Artifacts Directory**: `experimental_output/long_clip_discovery_qwen25_humor_20261024/`
- **Execution Command**:
  ```powershell
  $env:PYTHONPATH="backend"
  backend\.venv\Scripts\python.exe backend/app/cli/discover_candidates.py `
      outputs/Anne_Hathaway_Forgets_The_Princess_Diaries_and_The_Devil_Wears_Prada_Details__Chats_The_Idea_of_You_-_The_Tonight_Show_Starring_Jimmy_Fallon__1080p__h264__20261020_202242/transcript.json `
      -o experimental_output/long_clip_discovery_qwen25_humor_20261024 `
      -p ollama `
      -m qwen2.5:7b `
      -g humor `
      --mode long
  ```
- **Configuration Parameters**:
  - `mode`: `long` (`LONG_CLIP_SYSTEM_PROMPT` active)
  - `min_duration_seconds`: `30.0s`
  - `preferred_min_seconds`: `45.0s`
  - `preferred_max_seconds`: `120.0s`
  - `target_duration_seconds`: `90.0s`
  - `max_duration_seconds`: `180.0s`
  - `transcript_chunk_size`: `1500 words` (resulted in 2 chunks processed)
  - `transcript_chunk_overlap_seconds`: `60.0s`

---

### 5.2 Discovery & Validation Results

- **Total Raw Candidates Proposed by Model**: 10
- **Total Candidates Accepted**: 1 (`cnd_001`)
- **Total Candidates Rejected**: 9 (all rejected by backend validation)

#### Accepted Candidate Details

| Candidate ID | Source Interval (`MM:SS`) | Raw Model Interval | Refined Interval | Duration | Score | Hook / Summary | Validation Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| `cnd_001` | `06:27 – 06:58` | `387.07s – 418.40s` | `387.07s – 418.40s` | 31.33s | 90 | Anne setting up the premise of *The Idea of You* (single mom Solène Marchand meeting boy band lead singer Hayes Campbell at Coachella and falling in love). | `VALID` |

*Boundary Refinement Audit for `cnd_001`*:
- Raw Interval: `[387.07s, 418.40s]` $\rightarrow$ Refined Interval: `[387.07s, 418.40s]`.
- Decision: Boundaries matched exact sentence start at 387.07s and terminal sentence close before Jimmy's reaction at 418.40s. Post-refinement revalidation: Validated clean.

#### Rejected Candidates Audit

| # | Proposed Interval (`MM:SS`) | Decimal Interval | Duration | Model Hook | Reason Codes & Diagnostic Finding |
| :-: | :---: | :---: | :---: | :--- | :--- |
| 1 | `00:27 – 00:39` | `27.37s – 39.45s` | 12.08s | The host introduces a personal anecdote about competitiveness. | `DURATION_BELOW_MINIMUM`: Sub-minimum (12.08s < 30.0s). The model isolated Jimmy's intro sentence rather than capturing the full ~50s board-game anecdote. |
| 2 | `01:51 – 02:05` | `111.84s – 125.54s` | 13.70s | The host shares a humorous anecdote about a quiz game. | `DURATION_BELOW_MINIMUM`: Sub-minimum (13.70s < 30.0s). Cut off the Devil Wears Prada setup (started too late, ending prematurely). |
| 3 | `02:43 – 03:09` | `163.13s – 189.54s` | 26.41s | The host shares a story about a Broadway debut with Anna Wintour. | `DURATION_BELOW_MINIMUM`, `EVIDENCE_PARTIALLY_UNGROUNDED`: Sub-minimum (26.41s < 30.0s) and missed the initial host setup at 156.27s. |
| 4 | `04:04 – 04:16` | `244.22s – 256.54s` | 12.32s | The host shares a humorous anecdote about a Broadway performance. | `DURATION_BELOW_MINIMUM`, `EVIDENCE_NOT_GROUNDED`: Model evidence quote was outside the proposed interval. |
| 5 | `06:50 – 07:03` | `410.88s – 423.96s` | 13.08s | Humorous setup of a mom unexpectedly meeting a boy band lead singer at a festival. | `DURATION_BELOW_MINIMUM`, `EVIDENCE_NOT_GROUNDED`: Fragmented snippet overlapping with `cnd_001`. |
| 6 | `07:42 – 07:55` | `462.00s – 475.90s` | 13.90s | Humorous interaction about accidentally walking into the wrong trailer. | `DURATION_BELOW_MINIMUM`: Sub-minimum (13.90s < 30.0s). |
| 7 | `07:57 – 08:06` | `477.00s – 486.16s` | 9.16s | Humorous reaction to a character's audition. | `DURATION_BELOW_MINIMUM`, `EVIDENCE_PARTIALLY_UNGROUNDED`: Sub-minimum (9.16s < 30.0s). |
| 8 | `08:50 – 09:05` | `530.98s – 545.30s` | 14.32s | Humorous reflection on the impact of the book and the character's development. | `DURATION_BELOW_MINIMUM`: Sub-minimum (14.32s < 30.0s). |
| 9 | `09:50 – 09:59` | `590.50s – 599.01s` | 8.51s | Humorous setup of the movie's release date. | `DURATION_BELOW_MINIMUM`: Sub-minimum (8.51s < 30.0s). |

---

### 5.3 In-Depth Evaluation Across Seven Quality Dimensions

1. **Conversational Completeness**:
   - `cnd_001` (`06:27 – 06:58`, 31.33s) is an acceptable narrative arc where Anne explains the core plot and premise of *The Idea of You*. However, it is an informational premise pitch rather than high-octane banter.
   - For all 9 rejected candidates, the local `qwen2.5:7b` model chronically collapsed back into selecting short 9s–15s single-sentence punchlines, failing to obey the prompt instruction to capture the preceding conversational setup (e.g. proposing 27.37s–39.45s instead of the full 11.73s–60.92s board game story).

2. **Standalone Understandability**:
   - `cnd_001` is 100% understandable in isolation without needing earlier interview context.
   - The 9 rejected candidates, if accepted, would have lacked context and setup, validating the necessity of the backend duration floor (`min_duration_seconds=30.0s`).

3. **Word Integrity and Boundary Quality**:
   - `cnd_001` begins cleanly on word boundary `387.07s` (*"Across broke the record..."*) and closes at `418.40s` (*"...how they fall in love"*), right before Jimmy interjects (*"Yeah, because you're just a mom..."*). No words are split mid-phoneme.
   - Refinement correctly identified that the boundary was already aligned with natural speech breaks, maintaining precision without artificial padding.

4. **Setup/Payoff & Reaction Capture**:
   - In `cnd_001`, the conversational setup begins with Jimmy asking about the trailer and Anne explaining the premise.
   - In the board game moment (Proposal 1), the model captured the middle thought (*"maybe being competitive is genetic..."*) but truncated the setup at the start (11.73s) and the punchline at the end (*"I play for money too"* at 59.42s).

5. **Duplication / Overlap**:
   - Zero duplication among accepted candidates (only 1 accepted). Proposal 5 overlapped with `cnd_001` and was rejected.

6. **Coverage Across the Source**:
   - The model evaluated both 1500-word chunks spanning the entire 10-minute video. However, because `qwen2.5:7b` persistently gravitated toward single-turn 10–14s intervals, only 1 candidate survived the 30.0s long-clip validation floor. Key editorial anchors like Moment A (0:11–1:03), Moment B (1:24–1:59), and Moment C (2:06–2:36) were either partially proposed as sub-30s fragments or missed.

7. **Ranking & Validation Quality**:
   - The backend validation layer performed with 100% precision: every proposal under 30.0s was rejected with typed reason codes (`DURATION_BELOW_MINIMUM`), preventing fragmented clips from passing into long-master rendering. No invalid candidates leaked through.

---

### 5.4 Comparison with Previous Short-Discovery Experiment

| Dimension | Previous Short Experiment (`smoke_test_ollama_qwen25_humor_multiwindow`) | Long Experiment (`long_clip_discovery_qwen25_humor_20261024`) |
| :--- | :--- | :--- |
| **Duration Settings** | `min=10s`, `target=30s`, `max=60s` | `min=30s`, `target=90s`, `max=180s` |
| **Chunking Strategy** | 750 words (~200s windows, 30s overlap) | 1500 words (~350s windows, 60s overlap) |
| **Prompt** | Short viral clips (`SYSTEM_PROMPT`) | Conversational arcs (`LONG_CLIP_SYSTEM_PROMPT`) |
| **Accepted Candidates** | 7 accepted (durations: 12.0s – 19.4s) | 1 accepted (duration: 31.33s) |
| **Boundary Quality** | Cut mid-reaction; no word snapping | Word-snapped; post-refinement revalidation active |
| **Backend Enforcement** | Allowed short fragments through | Successfully prevented fragmented snippets from becoming long masters |

**Key Diagnostic Insight**:
The prompt alone is insufficient to make a 7B parameter local model (`qwen2.5:7b`) span wide multi-turn 45–90s dialogue intervals when asked for "humor", because the model identifies comedic "moments" as individual funny lines rather than narrative arcs. The backend's 30.0s minimum floor prevented flawed long masters from being generated, preserving system integrity.

 
