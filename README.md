# MockMaster — Intelligent Mock Interview Agent

An agentic AI-powered mock interview platform. Upload your resume → get adaptive role-specific interview questions → receive multimodal feedback (technical + audio + visual) + live job recommendations.

---

## Features

### 🧠 Context Understanding
- PyMuPDF PDF parsing + Groq LLM analysis
- Extracts skills, experience, work history, education
- Infers up to 3 realistic job roles from resume evidence
- Generates **skill gaps per role** — injected into the interview orchestrator to probe weak areas

### 🎙️ Interview Orchestrator Agent
- 10 fully **dynamic LLM-generated questions** (no static list)
- **Adaptive difficulty** — rolling average of last 3 scores drives question hardness
- Question progression: Q1–2 warm-up → Q3–5 mid technical → Q6–8 tough → Q9–10 edge cases
- **Anti-inflation scoring** — deterministic pre-checks override polite LLM scores
- **Topic deduplication** — never repeats a topic across 10 questions

### 🎤 Audio Intelligence
- `librosa` + `pyin` for pitch/F0 analysis (voiced frames only)
- RMS-based hesitation/pause detection (pauses > 0.5s)
- Speaking pace (WPM), confidence score, clarity score
- All audio metrics flow into the final LLM coaching prompt

### 👁️ Visual Intelligence (face-api.js)
- **face-api.js v0.22.2** — TinyFaceDetector + FaceLandmark68Tiny + FaceExpressionNet
- Eye contact, posture, engagement, nervousness — computed from real face landmarks
- Rolling 5-frame buffer per answer for smooth, jitter-free scores
- Runs 100% in-browser — no backend CV call needed

### 📊 Feedback & Coaching
- Overall score (0–100) + verdict: Strong Hire / Hire / Borderline / No Hire
- `per_question_scores[]` — what was good or bad, per question
- Audio scores from all answers passed to LLM for `communication_insights`
- `recommended_resources[]` — specific books/courses per identified gap

### 💼 Job Recommendations
- Live crawling: Remotive, Lever (Swiggy), Greenhouse (Microsoft)
- LLM fallback when live crawling returns < 3 results
- Weighted match scoring with `match_reason` + `missing_skills` per job

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI |
| LLM | Groq API (`llama-3.3-70b-versatile`) |
| PDF parsing | PyMuPDF (fitz) |
| Audio | librosa, pydub, ffmpeg |
| Visual | face-api.js (browser CDN) |
| STT | Web Speech API (browser) |
| Frontend | Vanilla HTML / CSS / JS |
| Job crawling | Remotive API, Lever API, Greenhouse API |

---

## Prerequisites

- Python 3.11+
- **ffmpeg** (required for audio conversion):
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: `winget install ffmpeg` or download from https://ffmpeg.org/download.html
- Free **Groq API key** from https://console.groq.com
- **Chrome or Edge** (Web Speech API + MediaRecorder)

---

## Setup & Run

### 1. Clone / unzip the project

```bash
cd agentic-interview-main
```

### 2. Create your `.env` file

```bash
cp backend/agents/.env.example backend/agents/.env
```

Open `backend/agents/.env` and add your key:
```
GROQ_API_KEY=gsk_your_key_here
```

### 3. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

> **Note:** `librosa` pulls in `numba` which JIT-compiles on first run — expect a 10–15s startup delay the first time.

### 4. Run

**Windows:**
```cmd
cd backend
run_app.bat
```

**macOS / Linux:**
```bash
cd backend
chmod +x run_app.sh && ./run_app.sh
```

**Manual:**
```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. Open the app

```
http://127.0.0.1:8000
```

Use **Chrome or Edge** — Firefox does not support Web Speech API.

---

## Project Structure

```
agentic-interview-main/
├── backend/
│   ├── main.py                    # FastAPI app + all route definitions
│   ├── agents/
│   │   ├── resume_agent.py        # PDF parse → skills / roles / skill_gaps
│   │   ├── interview_agent.py     # Adaptive orchestrator + scoring rubric
│   │   ├── job_agent.py           # LLM-based job recommendation fallback
│   │   └── .env.example           # Copy to .env and add GROQ_API_KEY
│   ├── services/
│   │   ├── audio_analyser.py      # librosa pitch / energy / hesitation pipeline
│   │   ├── job_aggregator.py      # Orchestrates live job source calls
│   │   └── job_sources.py         # Remotive / Lever / Greenhouse crawlers
│   ├── requirements.txt
│   ├── run_app.sh                 # One-command launcher (Mac/Linux)
│   └── run_app.bat                # One-command launcher (Windows)
├── frontend/
│   ├── index.html                 # Landing page
│   ├── resume.html                # Resume upload + role selection
│   ├── interview.html             # Live interview (face-api.js integrated)
│   ├── jobs.html                  # Job recommendations UI
│   ├── css/
│   │   ├── main.css
│   │   ├── home.css
│   │   └── style.css
│   └── js/
│       └── utils.js
├── samples/
│   ├── sample_resume.txt          # Example resume for quick testing
│   └── expected_output.json       # Expected API responses for evaluation
└── ARCHITECTURE.md                # Full design document
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/analyse-resume` | Upload PDF → profile + skill_gaps |
| POST | `/api/interview/start` | Begin interview → Q1 |
| POST | `/api/interview/answer` | Submit answer → score + next question |
| POST | `/api/interview/feedback` | Final multimodal report |
| POST | `/api/interview/analyse-audio` | Audio blob → confidence / clarity metrics |
| POST | `/api/jobs` | Resume profile → matched live jobs |

---

## Quick Evaluation (No Browser Needed)

```bash
# 1. Start the server
cd backend && ./run_app.sh

# 2. Upload the sample resume
curl -X POST http://127.0.0.1:8000/api/analyse-resume \
  -F "file=@../samples/sample_resume.txt;type=application/pdf"

# 3. Compare the response to samples/expected_output.json
```

---


## Scoring Guide

| Overall Score | Verdict |
|--------------|---------|
| 85–100 | Strong Hire |
| 70–84 | Hire |
| 50–69 | Borderline |
| 0–49 | No Hire |

Per-question scores follow a strict rubric (1 = blank/repeated question, 10 = exceptional senior-level answer). Deterministic pre-checks prevent polite LLM inflation.
