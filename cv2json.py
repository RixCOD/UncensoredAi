"""
cv2json.py
----------
Converts cv.pdf -> cv.json (structured resume data).

Uses pdfminer.six to extract raw text, then a simple section-based
parser to structure it. For higher accuracy, plug in a real NLP/LLM
parser at the `extract_structured_fields` step (marked below).
"""

import json
import re
import sys
from pathlib import Path

from pdfminer.high_level import extract_text

CV_PDF_PATH = Path("D:/project/UncensoredAi/MyCV.pdf")
CV_JSON_PATH = Path("D:/project/UncensoredAi/cv.json")

# Section headers we try to detect in the raw CV text.
SECTION_HEADERS = [
    "summary", "profile", "objective",
    "experience", "work experience", "employment history",
    "education",
    "skills", "technical skills",
    "projects",
    "certifications",
    "languages",
    "contact",
]


def extract_raw_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(f"CV not found at {pdf_path.resolve()}")
    return extract_text(str(pdf_path))


def extract_contact_info(text: str) -> dict:
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone_match = re.search(r"(\+?\d[\d\s().-]{7,}\d)", text)
    linkedin_match = re.search(r"(linkedin\.com/in/[\w-]+)", text, re.I)
    github_match = re.search(r"(github\.com/[\w-]+)", text, re.I)

    return {
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "linkedin": linkedin_match.group(0) if linkedin_match else None,
        "github": github_match.group(0) if github_match else None,
    }


def split_into_sections(text: str) -> dict:
    """Naive section splitter based on header keywords appearing on their own line."""
    lines = text.splitlines()
    sections = {}
    current_key = "header"
    buffer = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower().rstrip(":")
        if lower in SECTION_HEADERS and len(stripped) < 40:
            sections[current_key] = "\n".join(buffer).strip()
            current_key = lower
            buffer = []
        else:
            buffer.append(line)
    sections[current_key] = "\n".join(buffer).strip()
    return sections


def extract_structured_fields(raw_text: str) -> dict:
    """
    Main structuring step. This is intentionally simple (regex + section
    splitting). Swap this out for an LLM-based extractor (e.g. call the
    Anthropic API with the raw text and ask for structured JSON) if you
    need robust parsing across many CV formats/layouts.
    """
    sections = split_into_sections(raw_text)
    contact = extract_contact_info(raw_text)

    # Try to guess the name: usually the first non-empty line of the header.
    header_lines = [l.strip() for l in sections.get("header", "").splitlines() if l.strip()]
    name = header_lines[0] if header_lines else None

    skills_raw = sections.get("skills", "") or sections.get("technical skills", "")
    skills = [s.strip() for s in re.split(r"[,\n•|]", skills_raw) if s.strip()]

    return {
        "name": name,
        "contact": contact,
        "summary": sections.get("summary") or sections.get("profile") or sections.get("objective"),
        "experience_raw": sections.get("experience") or sections.get("work experience")
        or sections.get("employment history"),
        "education_raw": sections.get("education"),
        "skills": skills,
        "projects_raw": sections.get("projects"),
        "certifications_raw": sections.get("certifications"),
        "languages_raw": sections.get("languages"),
    }


def main():
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CV_PDF_PATH
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else CV_JSON_PATH

    print(f"[cv2json] Reading {pdf_path} ...")
    raw_text = extract_raw_text(pdf_path)

    print("[cv2json] Structuring fields ...")
    data = extract_structured_fields(raw_text)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"[cv2json] Wrote {out_path.resolve()}")
    print(f"[cv2json] Detected name: {data.get('name')!r}, "
          f"email: {data['contact'].get('email')!r}, "
          f"{len(data.get('skills', []))} skills found.")


if __name__ == "__main__":
    main()
