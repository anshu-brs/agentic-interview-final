import requests

def fetch_remotive_jobs():
    url = "https://remotive.com/api/remote-jobs"
    res = requests.get(url)
    data = res.json()

    jobs = []

    for j in data["jobs"]:
        jobs.append({
            "id": str(j["id"]),
            "title": j["title"],
            "company": j["company_name"],
            "location": "Remote",
            "work_mode": "Remote",
            "salary_range": None,
            "experience_required": "Not specified",
            "job_type": "Full-time",
            "description": j["description"][:400],
            "required_skills": j.get("tags", []),
            "apply_link": j["url"],
            "source": "remotive"
        })

    return jobs

def fetch_lever_jobs(company: str):
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    res = requests.get(url)

    try:
        data = res.json()
    except Exception:
        return []

    # Ensure it's a list
    if not isinstance(data, list):
        return []

    jobs = []

    for j in data:
        if not isinstance(j, dict):
            continue

        jobs.append({
            "id": str(j.get("id", "")),
            "title": j.get("text", ""),
            "company": company,
            "location": j.get("categories", {}).get("location", "") if isinstance(j.get("categories"), dict) else "",
            "work_mode": "Unknown",
            "salary_range": None,
            "experience_required": "Not specified",
            "job_type": "Full-time",
            "description": j.get("descriptionPlain", "")[:400],
            "required_skills": [],
            "apply_link": j.get("hostedUrl", ""),
            "source": "lever"
        })

    return jobs

import requests

def fetch_greenhouse_jobs(board: str):
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    res = requests.get(url)

    try:
        data = res.json()
    except Exception:
        return []

    # SAFETY CHECK 1: correct structure
    if not isinstance(data, dict):
        return []

    if "jobs" not in data:
        return []

    jobs = []

    for j in data["jobs"]:
        jobs.append({
            "id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company": board,
            "location": j.get("location", {}).get("name", ""),
            "work_mode": "Unknown",
            "salary_range": None,
            "experience_required": "Not specified",
            "job_type": "Full-time",
            "description": "",
            "required_skills": [],
            "missing_skills": [],
            "match_score": 0,
            "match_reason": "Fetched from Greenhouse",
            "apply_link": j.get("absolute_url", ""),
            "source": "greenhouse"
        })

    return jobs