"""Evidence-based CV scoring. Form fields never award points."""
from __future__ import annotations

import re
from typing import Any


SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "FastAPI/Django": ("fastapi", "django", "flask"),
    "SQL/PostgreSQL": ("sql", "postgresql", "postgres", "mysql"),
    "REST APIs": ("rest api", "restful", "api development"),
    "Git": ("git", "github", "gitlab"),
    "Docker": ("docker", "containerization", "kubernetes"),
    "Cloud": ("aws", "azure", "gcp", "cloud"),
    "Backend": ("backend", "back-end", "server-side"),
    "JavaScript/TypeScript": ("javascript", "typescript", "node.js", "nodejs"),
    "React/Next.js": ("react", "next.js", "nextjs"),
    "Testing": ("pytest", "unit testing", "automation testing", "selenium", "playwright"),
    "QA": ("quality assurance", "qa engineer", "test cases", "bug tracking"),
    "Sales": ("sales", "business development", "lead generation", "crm"),
    "Communication": ("communication", "stakeholder", "presentation"),
}


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.I) for value in phrases)


def _years(text: str) -> float:
    values = [float(value) for value in re.findall(r"\b(\d{1,2}(?:\.\d)?)\+?\s*(?:years?|yrs?)\b", text, re.I)]
    return min(max(values, default=0.0), 60.0)


def _role_weights(title: str, requirements: Any) -> dict[str, int]:
    haystack = f"{title} {' '.join(requirements or [])}".lower()
    if "python" in haystack or "backend" in haystack:
        return {"Python": 20, "FastAPI/Django": 15, "SQL/PostgreSQL": 10, "REST APIs": 10, "Git": 5, "Docker": 10, "Cloud": 10, "Backend": 10}
    if any(value in haystack for value in ("quality", "qa", "test")):
        return {"QA": 25, "Testing": 25, "Git": 10, "SQL/PostgreSQL": 10, "REST APIs": 10, "Communication": 10}
    if any(value in haystack for value in ("sales", "business development")):
        return {"Sales": 45, "Communication": 25, "Cloud": 5, "Git": 5, "SQL/PostgreSQL": 5, "REST APIs": 5}
    matched = {name: 10 for name, aliases in SKILL_ALIASES.items() if any(alias in haystack for alias in aliases)}
    return matched or {"Communication": 20, "Git": 10, "SQL/PostgreSQL": 10, "REST APIs": 10, "Cloud": 10}


def review_cv(*, text: str, title: str, requirements: Any, submitted_skills: list[str], submitted_experience: float, security_status: str, security_flags: list[str]) -> dict[str, Any]:
    weights = _role_weights(title, requirements)
    evidence: list[dict[str, Any]] = []
    verified: list[str] = []
    missing: list[str] = []
    score = 0
    for skill, points in weights.items():
        found = _contains(text, SKILL_ALIASES[skill])
        evidence.append({"criterion": skill, "points": points if found else 0, "maximum": points, "evidence": "Found in visible CV text" if found else "Not found in visible CV text"})
        (verified if found else missing).append(skill)
        if found:
            score += points
    years = _years(text)
    experience_points = 10 if years >= 3 else (5 if years >= 1 else 0)
    score += experience_points
    evidence.append({"criterion": "Relevant experience", "points": experience_points, "maximum": 10, "evidence": f"{years:g} years evidenced in visible CV text"})
    max_score = sum(weights.values()) + 10
    normalized = round(min(100, score * 100 / max_score), 2)
    lower_text = text.lower()
    clean_submitted_skills = list(dict.fromkeys(str(skill).strip() for skill in (submitted_skills or []) if str(skill).strip()))
    unsupported = [skill for skill in clean_submitted_skills if skill.casefold() not in lower_text]
    mismatches = []
    if unsupported:
        mismatches.append(f"Form skills not evidenced in CV: {', '.join(unsupported[:8])}")
    # A zero extraction result is low-confidence (many CVs use date ranges rather
    # than an explicit "N years" phrase), so do not present it as a proven mismatch.
    if years > 0 and submitted_experience > years + 1:
        mismatches.append(f"Form states {submitted_experience:g} years; visible CV evidences {years:g} years")
    forced_manual = security_status != "CLEAN" or bool(mismatches)
    status = "SHORTLISTED" if normalized >= 80 and not forced_manual else "MANUAL_REVIEW"
    recommendation = "Proceed to interview (pending staff approval)." if status == "SHORTLISTED" else "Human review required; the system does not auto-reject this application."
    return {
        "source": "CV_EVIDENCE_REVIEW", "review_version": "2.0.0", "score": normalized,
        "candidate_summary": f"CV evidence matches {len(verified)} of {len(weights)} role criteria; {years:g} years of experience were detected.",
        "ai_recommendation": recommendation, "verified_skills": verified, "missing_requirements": missing,
        "score_breakdown": evidence, "cv_experience_years": years, "form_mismatches": mismatches,
        "security_status": security_status, "security_flags": security_flags, "decision": status,
    }
