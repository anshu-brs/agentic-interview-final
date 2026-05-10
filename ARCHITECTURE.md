# MockMaster — Architecture Document (v2)

> Hackathon submission for: **Intelligent Mock Interview Agent**

---

## 1. Problem Summary & User Journey

MockMaster is an agentic AI-powered mock interview platform. A candidate uploads their PDF resume; the system infers realistic target roles, runs a fully adaptive 10-question interview with multimodal scoring (technical + audio delivery + visual presence), generates a coached feedback report, and surfaces live job recommendations.

### User Journey

```
1. Upload Resume (PDF)
       │
       ▼
2. Resume Analysis  ──►  Skills extracted, 3 roles inferred, skill gaps per role identified
       │
       ▼
3. Select Role  ──►  Candidate chooses the role to be interviewed for
       │
       ▼
4. Live Interview  ──►  10 LLM-generated adaptive questions
   (concurrent)          Real-time audio analysis per answer (librosa)
                         Real-time visual analysis per answer (face-api.js)
       │
       ▼
5. Feedback Report  ──►  Technical score + audio delivery + visual presence
                          Verdict: Strong Hire / Hire / Borderline / No Hire
                          Coached improvement notes + resource recommendations
       │
       ▼
6. Job Recommendations  ──►  Crawled live postings (Remotive, Lever, Greenhouse)
                              Ranked by weighted match score + missing skills shown
```

---

## 2. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Browser)                           │
│                                                                      │
│  index.html ──► resume.html ──► interview.html ──► jobs.html        │
│                                                                      │
│  • PDF upload via fetch() FormData                                   │
│  • Web Speech API  — real-time speech-to-text (transcript)          │
│  • MediaRecorder   — audio blob captured per answer                 │
│  • face-api.js v0.22.2 (TinyFaceDetector + FaceLandmark68Tiny +     │
│      FaceExpressionNet) — runs 100% in-browser on <canvas>          │
└─────────────────────────────┬──────────────────────────────────────┘
                              │ HTTP / REST (JSON)
┌─────────────────────────────▼──────────────────────────────────────┐
│                       BACKEND (FastAPI)                              │
│                                                                      │
│  POST /api/analyse-resume      →  resume_agent.analyse_resume()     │
│  POST /api/interview/start     →  interview_agent.start_interview() │
│  POST /api/interview/answer    →  interview_agent.next_question()   │
│  POST /api/interview/feedback  →  interview_agent.get_feedback()    │
│  POST /api/interview/analyse-audio → audio_analyser.analyse_audio() │
│  POST /api/jobs                →  job_agent + job_aggregator        │
└──────────┬─────────────────────┬──────────────────┬────────────────┘
           │                     │                  │
      Groq API             librosa / pyin      Job APIs
  (llama-3.3-70b)          (server-side)   (Remotive, Lever,
                                            Greenhouse)
```

### Module Interaction Flow

```
resume_agent.analyse_resume(pdf_bytes)
  └─ Returns: { skills, inferred_roles, experience_years, skill_gaps{role→[gaps]} }
        │
        └──► interview_agent.start_interview(role, skills, skill_gaps[role])
                  └─ Returns: warm-up Q1
                        │
                        └──► [browser submits answer + audio blob]
                                  │
                                  ├──► audio_analyser.analyse_audio(blob)
                                  │       └─ Returns: confidence, clarity, tone, WPM
                                  │
                                  └──► interview_agent.next_question(history + audio scores)
                                            └─ Returns: score, feedback, Q(n+1)
                                                  │
                                                  └──► [repeat × 10]
                                                            │
                                                            └──► interview_agent.get_feedback(history)
                                                                      └─ Returns: report
```

---

## 3. Module Design & Key Choices

### Module 1 — Context Understanding (`resume_agent.py`)

**What it does:**
- Parses PDF text with PyMuPDF (`fitz`)
- Sends resume text to Groq `llama-3.3-70b-versatile` in a single structured prompt
- Returns: `name`, `email`, `skills[]`, `inferred_roles[]` (up to 3), `experience_years`, `skill_gaps{role→[gaps]}`, `strengths[]`, `work_experience[]`

**Key design choices:**
- Single LLM call for the entire analysis (fast, < 2s)
- `skill_gaps` is keyed by role — when the user picks a role, only that role's gaps are passed to the interview orchestrator, so the agent probes exactly the weak areas for the chosen role
- `parse_json()` strips markdown fences (```` ```json ```` blocks) before parsing — robust to LLM formatting

**Trade-offs:**
- Single prompt vs multi-stage pipeline: single is faster and sufficient for text-based PDFs
- Scanned/image PDFs will return empty text — OCR (e.g. pytesseract) is future work

---

### Module 2 — Interview Orchestrator Agent (`interview_agent.py`)

**What it does:**
- `start_interview()`: generates Q1 as a role-specific warm-up behavioural question
- `next_question()`: scores the previous answer AND generates the next question in one LLM call
- `get_feedback()`: synthesises full multimodal report from 10-question history

**Adaptive difficulty engine:**
```
Rolling average of last 3 scores:
  avg ≤ 4  →  "Drop difficulty — candidate is struggling"
  avg ≥ 8  →  "Increase difficulty — candidate is excelling"
  else     →  "Maintain current difficulty"

Question progression schedule:
  Q1–Q2   →  warm-up / behavioural
  Q3–Q5   →  mid technical
  Q6–Q8   →  tough technical
  Q9–Q10  →  edge cases / leadership
```

**Anti-inflation scoring — `_pre_score()` deterministic pre-check:**

Before the LLM scores, a rule-based function applies hard overrides:

| Condition | Override |
|-----------|----------|
| Empty answer | Score = 1 (hard) |
| < 10 words | Score = 2 (hard) |
| Repeats the question | Score = 1 (hard) |
| "I don't know" phrasing | Score = 2 (hard) |
| < 12 words, no substance | Cap LLM score at ≤ 4 |

A detailed `SCORING_RUBRIC` (1–10 with mandatory checks) is also injected into every evaluation prompt to prevent the LLM from defaulting to polite scores of 6–7.

**Topic deduplication:**
- `used_topics[]` list is built from the interview history and injected as a forbidden list into every next-question prompt. The LLM is instructed to pick a completely new topic each time.

**Trade-offs:**
- All intelligence in LLM prompts rather than a hard-coded state machine → more natural, but adds ~1–3s latency per Groq call. Acceptable for an interview setting where human thinking time is longer.

---

### Module 3 — Audio Intelligence (`audio_analyser.py`)

**Pipeline:**
```
Browser MediaRecorder (.webm/opus blob)
  │
  └──► POST /api/interview/analyse-audio
            │
            └──► _convert_to_wav()  [ffmpeg subprocess: webm → 16kHz mono WAV]
                      │
                      └──► librosa.load()
                                │
                                ├── librosa.pyin()  →  F0 pitch extraction (voiced frames only)
                                ├── librosa.rms()   →  Energy / amplitude
                                ├── Silence gaps >0.5s  →  hesitation_count
                                └── word_count / voiced_duration  →  pace_wpm
```

**Scoring formulas:**
```python
confidence_score = pitch_score × 0.35 + energy_score × 0.35 + (1 - hesitation_penalty) × 0.30
clarity_score    = (1 - pause_ratio) × 0.50 + articulation_rate_score × 0.50

tone classification:
  pitch_std < 20 Hz  →  "flat"
  20–50 Hz           →  "moderate"
  > 50 Hz            →  "expressive"
```

**Integration with feedback:**
Audio metrics (confidence, clarity, WPM, tone, hesitation_count) are stored in the interview history alongside the LLM score and passed to `get_feedback()`. The final LLM coaching prompt includes an audio summary so `communication_insights` is data-driven.

**Trade-offs:**
- Requires ffmpeg in PATH. Fallback path attempts direct librosa decode of the webm, but this may fail on some platforms.
- Noisy environments reduce pitch extraction accuracy. Works best with a headset/quiet room.

---

### Module 4 — Visual Intelligence (`interview.html` + face-api.js)

**Library:** `face-api.js v0.22.2` — runs entirely in-browser on a `<canvas>` element. No server CV call required.

**Models loaded:**
- `TinyFaceDetector` — fast face detection (~30ms/frame)
- `FaceLandmark68Tiny` — 68-point facial landmarks
- `FaceExpressionNet` — 7-class expression probabilities

**Metrics computed per answer:**

| Metric | Computation |
|--------|-------------|
| Eye contact | Face-centre X/Y deviation from frame centre, normalised 0–100 |
| Posture (proxy) | Face bounding-box height as % of frame height (ideal: 12–45%) |
| Engagement | `1 − neutral_weight × detection_confidence`, scaled 0–100 |
| Nervousness | `(fearful + disgusted×0.5 + sad×0.3)` expression weights, scaled 0–100 |

**Smoothing:** rolling buffer of last 5 detections averaged per answer to reduce single-frame jitter.

**Sampling:** 2-second interval timer while camera is live; scores are captured and stored at answer-submission time.

**Trade-offs:**
- Face-size-based posture is a proxy, not a full body-landmark model. Accurate for seated laptop/desktop use; less accurate if camera is very high or low.
- Less robust than MediaPipe on very low-light or extreme-angle faces — acceptable per PS "simplified CV models / heuristics acceptable" clause.
- Runs at ~30ms/inference on modern hardware — no GPU needed.

---

### Module 5 — Technical Evaluation Engine

**Mechanism:** Each answer is scored 0–10 by `llama-3.3-70b-versatile` using the `SCORING_RUBRIC` injected into the prompt, plus the deterministic `_pre_score()` override layer.

**Scoring inputs per question:**
- The question being evaluated
- The candidate's answer text
- Interview history (prior Q&A + scores + audio metrics)
- Role and resume summary (context for relevance scoring)
- Skill gaps (the LLM knows what areas to probe deeply)

**Output per question:** `score` (0–10) + `feedback` (2–3 sentence honest coaching).

**Overall score computation:**
```
avg_content = mean of all per-question scores (0–10)
expected_overall = round(avg_content × 10)   # maps to 0–100 scale
LLM overall_score is clamped to ±12 of expected_overall to prevent inflation
```

---

### Module 6 — Feedback & Coaching Agent (`interview_agent.get_feedback`)

**Inputs to final LLM call:**
- Full 10-question transcript (Q, A, score, audio metrics per answer)
- Computed `avg_content` score and `expected_overall` (to anchor the LLM)
- Audio summary: `avg_confidence`, `avg_clarity` across all answers

**Output schema:**
```json
{
  "overall_score": 74,
  "overall_verdict": "Hire",
  "summary": "...",
  "strengths": ["...", "...", "..."],
  "areas_to_improve": ["...", "...", "..."],
  "communication_insights": "...",
  "per_question_scores": [{"question": "...", "score": 8, "note": "..."}],
  "recommended_resources": ["...", "..."]
}
```

**Verdict thresholds:**

| Score | Verdict |
|-------|---------|
| 85–100 | Strong Hire |
| 70–84 | Hire |
| 50–69 | Borderline |
| 0–49 | No Hire |

---

### Job Recommendations (`job_agent.py`, `job_aggregator.py`, `job_sources.py`)

**Live sources:**
- `Remotive` — public `/api/remote-jobs` endpoint (no auth required)
- `Lever` — public `/v0/postings/{company}` (Swiggy configured)
- `Greenhouse` — public `/v1/boards/{company}/jobs` (Microsoft configured)

**Fallback:** If live crawling returns < 3 results (rate limits, API changes), `job_agent.py` calls Groq to generate 6 realistic LLM-synthesised job recommendations based on the candidate profile.

**Match scoring formula:**
```
match_score = skill_match × 12 + role_match × 20 + experience_score × 30   (capped at 100)
```

**Output per job:** title, company, location, work_mode, salary_range, required_skills, `missing_skills`, `match_score`, `match_reason`, apply_link.

---

## 4. Scoring Aggregation

| Signal | Source | Output Range | Role in Final Report |
|--------|--------|-------------|---------------------|
| Technical score | LLM per-answer avg | 0–100 | Primary — drives `overall_score` |
| Audio confidence | librosa formula | 0–10 | Shown separately; feeds `communication_insights` |
| Audio clarity | Hesitation + energy | 0–10 | Shown separately; feeds `communication_insights` |
| Speaking pace | WPM | words/min | Informational coaching note |
| Eye contact | face-api.js deviation | 0–100 | Informational — shown in visual panel |
| Posture | face-api.js bbox | 0–100 | Informational |
| Engagement | face-api.js expressions | 0–100 | Informational |
| Nervousness | face-api.js fear/sad | 0–100 | Informational |

Audio and visual scores are surfaced in dedicated UI panels and folded into the LLM coaching prompt. The final verdict is anchored primarily to technical content scores, with audio/visual contextualising the communication and behavioural assessment.

---

## 5. API Reference

| Method | Endpoint | Request | Response |
|--------|----------|---------|----------|
| POST | `/api/analyse-resume` | `multipart/form-data` — `file` (PDF) | Resume profile + skill_gaps |
| POST | `/api/interview/start` | `{role, resume_summary, skills, experience_years, skill_gaps}` | Q1 |
| POST | `/api/interview/answer` | `{role, question, answer, history, question_number, skill_gaps}` | `{score, feedback, next_question}` |
| POST | `/api/interview/feedback` | `{role, history}` | Full multimodal report |
| POST | `/api/interview/analyse-audio` | `multipart/form-data` — `audio` blob + `transcript` | Audio metrics |
| POST | `/api/jobs` | `{skills, roles, experience_years, resume_summary}` | Ranked job list |

---

## 6. Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | Python 3.11 + FastAPI | Async, fast, auto-docs |
| LLM | Groq API (`llama-3.3-70b-versatile`) | Free tier, low latency (~1s), 70B reasoning quality |
| PDF parsing | PyMuPDF (`fitz`) | Fast, no native deps |
| Audio analysis | librosa + pydub + ffmpeg | Pitch/F0 + energy analysis, webm decode |
| Visual analysis | face-api.js v0.22.2 (browser CDN) | No backend CV server, works on any laptop |
| STT | Web Speech API (browser built-in) | Zero infra, real-time |
| Frontend | Vanilla HTML / CSS / JS | No build step, hackathon-appropriate |
| Job crawling | Remotive API, Lever API, Greenhouse API | Public, no auth |

---

## 7. Limitations, Assumptions & Next Steps

### Current Limitations

| Area | Limitation |
|------|-----------|
| PDF input | Text-based only; scanned/image PDFs return empty (OCR not implemented) |
| Audio | Requires ffmpeg in PATH; noisy environments reduce pitch accuracy |
| Visual | Posture is a face-size proxy, not full body landmarks |
| Job sources | 3 companies hard-coded (Swiggy/Lever, Microsoft/Greenhouse, Remotive) |
| Session state | No persistence — interview state lives in browser memory; page refresh loses session |
| Browser | Chrome/Edge required for Web Speech API + MediaRecorder |

### Assumptions
- Candidates have a text-based PDF resume and a webcam/microphone
- Groq free tier is sufficient for demo (rate limits may apply under heavy load)
- Interview is conducted in a reasonably quiet, well-lit environment

### Recommended Next Steps

| Priority | Enhancement |
|----------|------------|
| High | Scanned PDF support via pytesseract OCR |
| High | Session persistence (localStorage or backend DB) for historical tracking |
| High | Retry + exponential backoff on Groq rate limits |
| Medium | MediaPipe Pose for full upper-body posture detection |
| Medium | Coding round simulation with Judge0 code execution API |
| Medium | PDF feedback report download |
| Medium | Add more Lever/Greenhouse company sources (Razorpay, CRED, Zepto) |
| Low | Real-time coaching hints during the interview ("Speak more slowly", "Make eye contact") |
| Low | Multi-language resume support |
