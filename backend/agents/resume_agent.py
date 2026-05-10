import fitz
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
print(f"[resume_agent] Groq key loaded: {'YES' if GROQ_API_KEY else 'NO — add GROQ_API_KEY to .env'}")

if not GROQ_API_KEY:
    raise ValueError(
        "\n\nGROQ API KEY MISSING\n"
        "Open backend/agents/.env and add:\n"
        "GROQ_API_KEY=your_key_here\n"
        "Get FREE key at: https://console.groq.com\n"
    )

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


async def analyse_resume(pdf_bytes: bytes) -> dict:
    import asyncio

    print("Extracting text from PDF...")
    try:
        doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        raise ValueError(f"Could not read PDF: {e}")

    if not text.strip():
        raise ValueError("Empty PDF — use a text-based PDF, not a scanned image.")

    prompt = f"""You are an expert technical recruiter. Return ONLY valid JSON, no markdown, no extra text.

Analyse this resume and return exactly this JSON:
{{
  "name": "full name",
  "email": "email or empty string",
  "phone": "phone or empty string",
  "summary": "2-3 sentence professional summary",
  "skills": ["skill1", "skill2", "skill3"],
  "inferred_roles": ["Role 1", "Role 2", "Role 3"],
  "experience_years": 2,
  "education": ["Degree, Institution, Year"],
  "work_experience": [{{"company": "", "role": "", "duration": "", "highlights": ""}}],
  "skill_gaps": {{"Role 1": ["gap1", "gap2"]}},
  "strengths": ["strength1", "strength2", "strength3"]
}}

Resume:
{text[:6000]}"""

    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1500,
        )
    )
    raw = resp.choices[0].message.content
    try:
        data = parse_json(raw)
    except Exception as e:
        raise ValueError(f"AI returned bad response: {e}\nRaw: {raw[:300]}")

    return {
        "name":             data.get("name", ""),
        "email":            data.get("email", ""),
        "phone":            data.get("phone", ""),
        "summary":          data.get("summary", ""),
        "skills":           data.get("skills", []),
        "inferred_roles":   data.get("inferred_roles", []),
        "experience_years": int(data.get("experience_years", 0)),
        "education":        data.get("education", []),
        "work_experience":  data.get("work_experience", []),
        "skill_gaps":       data.get("skill_gaps", {}),
        "strengths":        data.get("strengths", []),
    }