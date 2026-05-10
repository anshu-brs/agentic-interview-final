from backend.services.job_sources import (
    fetch_remotive_jobs,
    fetch_lever_jobs,
    fetch_greenhouse_jobs,
)


def _safe_call(fn):
    try:
        return fn()
    except Exception as e:
        print("Job source failed:", e)
        return []


def _score_jobs(jobs: list, profile: dict) -> list:
    """
    Add match_score, match_reason, and missing_skills to every job.

    profile = {
        "skills": set[str],          # candidate skills, lowercased
        "roles":  list[str],         # inferred role names, lowercased
        "experience_years": int,
    }
    """
    candidate_skills = {s.lower() for s in profile.get("skills", [])}
    candidate_roles  = [r.lower() for r in profile.get("roles", [])]
    exp_years        = int(profile.get("experience_years", 0))

    for job in jobs:
        required = {s.lower() for s in job.get("required_skills", [])}
        title_lower = job.get("title", "").lower()

        # 1. Skill match
        skill_hits  = len(candidate_skills & required)
        skill_total = max(len(required), 1)
        skill_match = skill_hits / skill_total          # 0.0 – 1.0

        # 2. Role relevance (title overlap with any inferred role)
        role_match = any(r in title_lower for r in candidate_roles)

        # 3. Experience alignment
        job_level = job.get("experience_required", "").lower()
        if "intern" in job_level and exp_years == 0:
            exp_score = 30
        elif "0-1" in job_level and exp_years <= 1:
            exp_score = 30
        elif "1-2" in job_level and 1 <= exp_years <= 2:
            exp_score = 30
        elif exp_years > 2:
            exp_score = 20
        else:
            exp_score = 0

        # Weighted final score (capped at 100)
        raw_score = (
            skill_match * 40
            + (20 if role_match else 0)
            + exp_score
        )
        job["match_score"]    = min(100, round(raw_score))
        job["missing_skills"] = list(required - candidate_skills)
        job["match_reason"]   = (
            f"{skill_hits}/{skill_total} skill matches; "
            f"{'role title aligns' if role_match else 'adjacent role'}; "
            f"{'experience fits' if exp_score > 0 else 'experience gap'}."
        )

    # Best matches first
    return sorted(jobs, key=lambda j: j["match_score"], reverse=True)


def get_all_jobs(profile: dict) -> list:
    """
    Fetch jobs from all live sources, apply match scoring, and return
    sorted results.  Always receives a profile dict from the route.
    """
    jobs = []
    jobs += _safe_call(lambda: fetch_remotive_jobs())
    jobs += _safe_call(lambda: fetch_lever_jobs("swiggy"))
    jobs += _safe_call(lambda: fetch_greenhouse_jobs("microsoft"))

    return _score_jobs(jobs, profile)
