import os
import json
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

_this_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_this_dir / ".env", override=True)
load_dotenv(dotenv_path=_this_dir.parent / ".env", override=False)
load_dotenv(dotenv_path=_this_dir.parent.parent / ".env", override=False)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
MODEL  = "llama-3.3-70b-versatile"


def parse_json(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            try:
                return json.loads(p)
            except Exception:
                continue
    return json.loads(text)


async def get_job_recommendations(skills: list, roles: list, experience_years: int, resume_summary: str) -> dict:
    import asyncio
    prompt = f"""You are a career advisor. Return ONLY valid JSON, no markdown, no extra text.

Candidate profile:
Summary: {resume_summary}
Skills: {', '.join(skills)}
Target roles: {', '.join(roles)}
Experience: {experience_years} years

Generate 6 realistic job recommendations. Return exactly this JSON:
{{
  "jobs": [
    {{
      "id": "1",
      "title": "Job Title",
      "company": "Company Name",
      "location": "City, Country",
      "work_mode": "Remote",
      "salary_range": "8-12 LPA",
      "experience_required": "1-2 years",
      "job_type": "Full-time",
      "description": "Brief job description",
      "required_skills": ["skill1", "skill2"],
      "missing_skills": ["skill3"],
      "match_score": 85,
      "match_reason": "Strong match because...",
      "apply_link": "https://linkedin.com/jobs",
      "source": "linkedin"
    }}
  ],
  "search_tips": ["tip1", "tip2"]
}}

Rules:
- Generate exactly 6 jobs
- Mix: 2 stretch roles, 3 good-fit, 1 safe/entry-level
- Use realistic Indian companies (TCS, Infosys, Swiggy, Zomato, Razorpay, Zepto, CRED, etc)
- match_score between 60-95
- missing_skills should be honest"""

    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2000,
        )
    )
    raw = resp.choices[0].message.content
    try:
        data = parse_json(raw)
    except Exception:
        data = {"jobs": [], "search_tips": []}

    return {
        "jobs":        data.get("jobs", []),
        "search_tips": data.get("search_tips", []),
    }