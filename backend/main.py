import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from backend.agents.resume_agent import analyse_resume
from backend.agents.interview_agent import start_interview, next_question, get_feedback
from backend.agents.job_agent import get_job_recommendations
from backend.services.audio_analyser import analyse_audio
from backend.services.job_aggregator import get_all_jobs

app = FastAPI(title="MockMaster API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response Models ─────────────────────────────────────────────────

class InterviewStartRequest(BaseModel):
    role: str
    resume_summary: str
    skills: list[str]
    experience_years: int
    skill_gaps: list[str] = []

class InterviewAnswerRequest(BaseModel):
    role: str
    resume_summary: str
    question: str
    answer: str
    history: list[dict]
    question_number: int
    skill_gaps: list[str] = []

class FeedbackRequest(BaseModel):
    role: str
    history: list[dict]

class JobsRequest(BaseModel):
    skills: list[str]
    roles: list[str]
    experience_years: int
    resume_summary: str

# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/analyse-resume")
async def analyse_resume_endpoint(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    pdf_bytes = await file.read()
    try:
        result = await analyse_resume(pdf_bytes)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview/start")
async def interview_start(req: InterviewStartRequest):
    try:
        result = await start_interview(
            req.role, req.resume_summary, req.skills,
            req.experience_years, req.skill_gaps
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview/answer")
async def interview_answer(req: InterviewAnswerRequest):
    try:
        result = await next_question(
            role=req.role,
            resume_summary=req.resume_summary,
            question=req.question,
            answer=req.answer,
            history=req.history,
            question_number=req.question_number,
            skill_gaps=req.skill_gaps,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview/feedback")
async def interview_feedback(req: FeedbackRequest):
    try:
        result = await get_feedback(req.role, req.history)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/interview/analyse-audio")
async def analyse_audio_endpoint(
    audio: UploadFile = File(...),
    transcript: str = ""
):
    """
    Receives a raw audio blob (webm/wav) from the browser MediaRecorder.
    Returns confidence_score, clarity_score, pace_wpm, hesitation_count,
    pitch_variation, tone, and plain-English coaching notes.
    """
    audio_bytes = await audio.read()
    try:
        result = analyse_audio(audio_bytes, transcript=transcript)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jobs")
async def get_jobs(req: JobsRequest):
    profile = {
        "skills": set(s.lower() for s in req.skills),
        "roles":  [r.lower() for r in req.roles],
        "experience_years": req.experience_years,
    }

    live_jobs = get_all_jobs(profile)

    # Fall back to LLM-generated recommendations if live crawl is sparse
    if len(live_jobs) < 3:
        return await get_job_recommendations(
            req.skills, req.roles, req.experience_years, req.resume_summary
        )

    return {"jobs": live_jobs[:10]}


# ── Serve frontend ────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "frontend")),
    name="static"
)

@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "index.html"))

@app.get("/{page}.html")
def pages(page: str):
    return FileResponse(os.path.join(BASE_DIR, "frontend", f"{page}.html"))
