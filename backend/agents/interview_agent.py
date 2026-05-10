import os
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

# ── Load .env ─────────────────────────────────────────────────────────────────
_this_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_this_dir / ".env", override=True)
load_dotenv(dotenv_path=_this_dir.parent / ".env", override=False)
load_dotenv(dotenv_path=_this_dir.parent.parent / ".env", override=False)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
print(f"[interview_agent] Groq key loaded: {'YES' if GROQ_API_KEY else 'NO — add GROQ_API_KEY to .env'}")

client = Groq(api_key=GROQ_API_KEY)
MODEL  = "llama-3.3-70b-versatile"
TOTAL_QUESTIONS = 10

# ─────────────────────────────────────────────────────────────────────────────
# SCORING RUBRIC
# Injected into every evaluation prompt so the LLM uses a fixed scale
# instead of defaulting to 7 out of politeness.
# ─────────────────────────────────────────────────────────────────────────────
SCORING_RUBRIC = """
STRICT SCORING RUBRIC — you MUST follow this. Do NOT default to 5, 6, or 7.

  1   : Candidate repeated the question back, said nothing, or answered in under
        8 meaningful words. Completely off-topic answers also score 1.

  2   : A few words with zero substance. "I don't know", "I'm not sure", or
        a single vague sentence with no meaning.

  3   : Vague answer. Touches the topic but shows no real understanding.
        Buzzwords only (e.g. "I follow best practices"). No examples at all.

  4   : Partial — candidate knows the surface but can't go deeper. Missing the
        key concept or gives an incorrect explanation.

  5   : Adequate. Correct at a basic level but incomplete. No concrete example,
        or example is irrelevant. Would not impress an interviewer.

  6   : Decent. Mostly correct with a weak example. Missing depth, trade-offs,
        or nuance. Passes a bar-raiser but barely.

  7   : Good. Correct, specific, uses a real example. Demonstrates understanding
        but lacks depth on edge cases or trade-offs.

  8   : Strong. Thorough, well-structured, concrete examples, mentions trade-offs
        or alternatives. Would impress most interviewers.

  9   : Excellent. Insightful, shows senior-level thinking, raises considerations
        unprompted, demonstrates deep hands-on expertise.

 10   : Exceptional. Rare. Covers every angle, shows mastery, would pass a
        Google/Microsoft/top-tier system design interview.

MANDATORY CHECKS — apply BEFORE choosing a score:
  □ Did the candidate repeat the question verbatim? → score 1
  □ Is the answer under 10 words? → score ≤ 2
  □ Is the answer under 25 words with no example? → score ≤ 3
  □ Does the answer contain only buzzwords, no explanation? → score ≤ 3
  □ Does the answer have no concrete example or specific detail? → cap at 5
  □ Is the answer vague filler ("I always try my best", "I am a team player")? → score ≤ 4
  □ Did the candidate say "I don't know" or similar? → score ≤ 2

Scores of 7 and above MUST have a justification. Be honest. Be strict.
"""


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


async def call_groq(prompt: str) -> str:
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,   # low temp = less "polite inflation", more consistent scoring
            max_tokens=1200,
        )
    )
    return resp.choices[0].message.content


# ── start_interview ───────────────────────────────────────────────────────────
async def start_interview(role: str, resume_summary: str, skills: list,
                          experience_years: int, skill_gaps: list = None) -> dict:
    gaps_section = ""
    if skill_gaps:
        gaps_section = f"\nIdentified skill gaps to probe later: {', '.join(skill_gaps)}"

    prompt = f"""You are a senior interviewer. Return ONLY valid JSON, no markdown, no extra text.

Role: {role}
Candidate background: {resume_summary}
Skills: {', '.join(skills)}
Experience: {experience_years} years{gaps_section}

Generate a warm-up behavioral first question specific to this role.

Return exactly this JSON and nothing else:
{{
  "question": "your question here",
  "question_type": "behavioral",
  "hint": "one sentence tip for the candidate",
  "difficulty": "warm-up",
  "topic": "topic name e.g. motivation"
}}"""

    text = await call_groq(prompt)
    try:
        data = parse_json(text)
    except Exception:
        data = {}

    return {
        "question":        data.get("question", f"Tell me about yourself and why you want to work as a {role}."),
        "question_type":   "behavioral",
        "hint":            data.get("hint", "Use the STAR method — Situation, Task, Action, Result."),
        "difficulty":      "warm-up",
        "topic":           data.get("topic", "introduction"),
        "question_number": 1,
        "total_questions": TOTAL_QUESTIONS,
    }


# ── _pre_score: deterministic checks run BEFORE the LLM ──────────────────────
def _pre_score(question: str, answer: str):
    """
    Returns (override_score, flag_message) if the answer is obviously bad.
    Returns (None, "") if the answer needs normal LLM evaluation.
    """
    a = answer.strip()
    words = a.split()
    word_count = len(words)

    # 1. Empty / blank
    if word_count == 0:
        return 1, "⚠ SCORER: Answer is empty. Score MUST be 1."

    # 2. Very short — under 10 words
    if word_count < 10:
        return 2, f"⚠ SCORER: Answer is only {word_count} words. Score MUST be ≤ 2."

    # 3. Candidate repeated the question (≥ 5 of first 10 question-words appear in answer)
    q_words = set(question.lower().split()[:10])
    a_words  = set(a.lower().split()[:10])
    if len(q_words & a_words) >= 5:
        return 1, "⚠ SCORER: Answer repeats the question. Score MUST be 1."

    # 4. "I don't know" style non-answers
    non_answers = ["i don't know", "i do not know", "idk", "no idea", "not sure",
                   "i have no idea", "i am not sure", "i'm not sure", "i dont know"]
    if any(na in a.lower() for na in non_answers):
        return 2, "⚠ SCORER: Candidate admitted they don't know. Score MUST be ≤ 2."

    # 5. Only flag genuinely empty short answers (under 12 words, no substance).
    # Raised from 25 — concise correct answers were being wrongly capped at 4.
    substance_markers = [
        "because", "so that", "which means", "this means",
        "for example", "such as",
        "i built", "i worked", "i used", "i designed", "i implemented",
        "we built", "we used", "we implemented",
        "the result", "this allows", "this ensures", "this prevents",
        "in my", "at my", "during my",
        "it works by", "it uses", "it stores", "it handles",
        "you can", "you need", "you would", "you should",
    ]
    if word_count < 12 and not any(m in a.lower() for m in substance_markers):
        return None, "⚠ SCORER: Very short answer with no substance. Likely 2–3 unless it is a precise one-line technical fact."

    return None, ""


# ── next_question ─────────────────────────────────────────────────────────────
async def next_question(role: str, resume_summary: str, question: str,
                        answer: str, history: list, question_number: int,
                        skill_gaps: list = None) -> dict:

    history_lines, used_topics = [], []
    for i, h in enumerate(history):
        t = h.get("topic", f"topic_{i}")
        used_topics.append(t)
        audio_note = ""
        if h.get("confidence_score") is not None:
            audio_note = (f" | Audio: confidence={h['confidence_score']}/10,"
                          f" clarity={h.get('clarity_score','?')}/10,"
                          f" tone={h.get('tone','?')}")
        history_lines.append(
            f"Q{i+1}[{h.get('question_type','?')}] topic={t}: {h['question']}\n"
            f"  Answer: {h['answer']}\n  Score: {h.get('score','?')}/10{audio_note}"
        )

    recent = [h.get("score", 5) for h in history[-3:]]
    avg    = sum(recent) / len(recent) if recent else 5
    trend  = ("Drop difficulty, ask easier question, candidate is struggling." if avg <= 4
              else "Increase difficulty significantly, candidate is excelling." if avg >= 8
              else "Maintain current difficulty.")

    is_final = question_number >= TOTAL_QUESTIONS

    gaps_hint = ""
    if skill_gaps:
        gaps_hint = f"\nWeak areas to probe: {', '.join(skill_gaps)}"

    # ── Run deterministic pre-check first ────────────────────────────────────
    override_score, flag_msg = _pre_score(question, answer)

    score_instruction = f"""
{SCORING_RUBRIC}
{flag_msg}
Now score this answer. Your score field must be an INTEGER between 1 and 10.
{"The score MUST be " + str(override_score) + " due to the check above." if override_score is not None else ""}
""".strip()

    prompt = f"""You are a STRICT senior interviewer evaluating a {role} candidate.
Return ONLY valid JSON, no markdown, no extra text.

{score_instruction}

Candidate background: {resume_summary}{gaps_hint}

Interview history so far (NEVER repeat topics: {', '.join(used_topics) or 'none'}):
{chr(10).join(history_lines) or 'No previous questions.'}

Question being evaluated (Q{question_number}/{TOTAL_QUESTIONS}):
{question}

Candidate's answer:
\"\"\"{answer.strip()}\"\"\"

Adaptive next-question rule: {trend}
Question progression: Q1-2=warm-up behavioral, Q3-5=mid technical, Q6-8=tough technical, Q9-10=edge cases/leadership.
is_final must be {"true" if is_final else "false"}.
Next question MUST be on a completely NEW topic not in the forbidden list above.

Return exactly this JSON — fill every field with real values, no placeholders:
{{
  "score": <integer 1-10 per rubric above>,
  "feedback": "<2-3 sentences of honest, specific feedback — name exactly what was missing or wrong>",
  "is_final": {"true" if is_final else "false"},
  "next_question": {{
    "question": "<specific role-relevant question on a new topic>",
    "question_type": "<behavioral|technical|situational>",
    "hint": "<one concrete tip>",
    "difficulty": "<warm-up|mid|tough>",
    "topic": "<new topic name>"
  }}
}}"""

    text = await call_groq(prompt)
    try:
        data = parse_json(text)
    except Exception:
        data = {}

    llm_score = int(data.get("score", 5))

    # ── Apply hard caps — LLM politeness cannot override these ───────────────
    if override_score is not None:
        # Hard override from pre-check (empty, repeated question, "I don't know")
        final_score = override_score
    else:
        # Only apply a cap for the soft-warning case (very short, no substance).
        # Do NOT blanket-cap answers just because they are under 25 words —
        # concise correct answers should score normally.
        _, flag = _pre_score(question, answer)
        if flag:
            final_score = min(llm_score, 4)
        else:
            final_score = llm_score

    response = {
        "score":    final_score,
        "feedback": data.get("feedback", "Try to give a more detailed answer with specific examples."),
        "is_final": bool(data.get("is_final", is_final)),
    }

    nq = data.get("next_question", {})
    if not response["is_final"] and nq:
        response["next_question"] = {
            "question":        nq.get("question", f"Describe a technical challenge you faced as a {role}."),
            "question_type":   nq.get("question_type", "technical"),
            "hint":            nq.get("hint", "Be specific and use real examples."),
            "difficulty":      nq.get("difficulty", "mid"),
            "topic":           nq.get("topic", f"topic_{question_number}"),
            "question_number": question_number + 1,
            "total_questions": TOTAL_QUESTIONS,
        }
    return response


# ── get_feedback ──────────────────────────────────────────────────────────────
async def get_feedback(role: str, history: list) -> dict:
    history_text = "\n\n".join(
        [f"Q{i+1}[{h.get('question_type','?')}]: {h['question']}\n"
         f"Answer: {h['answer']}\nScore: {h.get('score','?')}/10\n"
         f"Audio — confidence: {h.get('confidence_score','N/A')}, clarity: {h.get('clarity_score','N/A')}, "
         f"pace: {h.get('pace_wpm','N/A')} wpm, tone: {h.get('tone','N/A')}, hesitations: {h.get('hesitation_count','N/A')}"
         for i, h in enumerate(history)]
    )

    conf_vals = [h['confidence_score'] for h in history if h.get('confidence_score') is not None]
    clar_vals = [h['clarity_score']    for h in history if h.get('clarity_score')    is not None]
    audio_summary = ""
    if conf_vals:
        avg_conf = sum(conf_vals) / len(conf_vals)
        avg_clar = sum(clar_vals) / len(clar_vals) if clar_vals else None
        audio_summary = (f"\nOverall audio: avg confidence={avg_conf:.1f}/10, "
                         f"avg clarity={avg_clar:.1f}/10 over {len(conf_vals)} answers. "
                         "Include delivery insights in feedback.")

    # Compute true average from recorded scores so the LLM can't ignore them
    content_scores = [h.get("score", 0) for h in history if h.get("score") is not None]
    avg_content    = round(sum(content_scores) / len(content_scores), 1) if content_scores else 5
    expected_overall = round(avg_content * 10)   # e.g. avg 4.2 → overall ~42

    prompt = f"""You are a strict senior hiring manager writing a final interview debrief.
Return ONLY valid JSON, no markdown, no extra text.

Role: {role}{audio_summary}

The candidate's per-question content scores averaged {avg_content}/10.
The overall_score (out of 100) MUST be close to {expected_overall} (within ±8).
Do NOT inflate. A score of 3–4 average means a weak candidate — reflect that honestly.

Interview transcript:
{history_text}

Verdict scale: Strong Hire (85–100), Hire (70–84), Borderline (50–69), No Hire (0–49).

Return exactly this JSON — use real values, not placeholders:
{{
  "overall_score": <integer near {expected_overall}, honest not inflated>,
  "overall_verdict": "<Strong Hire|Hire|Borderline|No Hire>",
  "summary": "<2-3 honest sentences covering technical ability and communication>",
  "strengths": ["<specific strength 1>", "<specific strength 2>", "<specific strength 3>"],
  "areas_to_improve": ["<specific gap 1>", "<specific gap 2>", "<specific gap 3>"],
  "communication_insights": "<1-2 sentences on vocal delivery and clarity from audio data>",
  "per_question_scores": [{{"question": "<short question>", "score": <int>, "note": "<what was good or bad>"}}],
  "recommended_resources": ["<specific book/course/resource 1>", "<specific resource 2>"]
}}"""

    text = await call_groq(prompt)
    try:
        data = parse_json(text)
    except Exception:
        data = {}

    # Final guard: overall_score must stay close to what was actually earned
    reported = int(data.get("overall_score", expected_overall))
    if abs(reported - expected_overall) > 12:
        reported = expected_overall   # hard-clamp if LLM strays too far

    return {
        "overall_score":          reported,
        "overall_verdict":        data.get("overall_verdict", "Borderline"),
        "summary":                data.get("summary", "Interview completed."),
        "strengths":              data.get("strengths", []),
        "areas_to_improve":       data.get("areas_to_improve", []),
        "communication_insights": data.get("communication_insights", ""),
        "per_question_scores":    data.get("per_question_scores", []),
        "recommended_resources":  data.get("recommended_resources", []),
    }