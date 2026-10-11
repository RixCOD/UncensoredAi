"""
fillform.py
-----------
Reads apply.json, opens each apply_link, and fills the application form
with data from cv.json.

By default this runs in SEMI-AUTOMATIC mode (SUBMIT = False): it fills
the form fields and then pauses so you can review, handle any
CAPTCHA/MFA, upload role-specific attachments, and click submit
yourself. This matches the README's "best practice: semi-automation"
note and avoids blindly submitting to sites you haven't reviewed.

Flip SUBMIT = True only once you've verified an adapter's field mapping
is correct and you're comfortable auto-submitting.
"""

import json
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page

CV_JSON_PATH = Path("cv.json")
APPLY_JSON_PATH = Path("apply.json")
DONE_APPLY_JSON_PATH = Path("doneapply.json")

SUBMIT = False  # set True to auto-submit once you trust the field mapping
PAUSE_FOR_REVIEW_SECONDS = 120  # how long to wait for manual review/submit


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def fill_generic_form(page: Page, cv: dict) -> bool:
    """
    Attempts to fill common ATS-style fields by matching input
    name/placeholder/label text. Works on a decent chunk of simple
    forms; complex multi-step ATS flows (Workday, Greenhouse, Lever)
    usually need a dedicated adapter -- add one below following this
    same pattern if a site keeps failing here.
    """
    contact = cv.get("contact", {})
    field_map = {
        "name": cv.get("name"),
        "full name": cv.get("name"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedin": contact.get("linkedin"),
        "github": contact.get("github"),
    }

    filled_any = False
    for label_fragment, value in field_map.items():
        if not value:
            continue
        # Try input[name=...] and input[placeholder*=...] as loose matches.
        selectors = [
            f"input[name*='{label_fragment}' i]",
            f"input[placeholder*='{label_fragment}' i]",
            f"input[id*='{label_fragment}' i]",
        ]
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    el.fill(str(value))
                    filled_any = True
                    break
            except Exception:
                continue

    # Resume/CV file upload, if the form has a file input.
    try:
        file_input = page.query_selector("input[type='file']")
        cv_pdf = Path("cv.pdf")
        if file_input and cv_pdf.exists():
            file_input.set_input_files(str(cv_pdf))
            filled_any = True
    except Exception as e:
        print(f"[fillform] file upload skipped: {e}")

    return filled_any


def apply_to_job(page: Page, job: dict, cv: dict) -> Optional[str]:
    """Returns a status string: 'submitted', 'filled_pending_review', or 'failed'."""
    link = job.get("apply_link")
    if not link:
        return "failed"

    print(f"[fillform] Opening {job.get('company')} - {job.get('role')}")
    page.goto(link, wait_until="domcontentloaded")
    time.sleep(2)

    try:
        filled = fill_generic_form(page, cv)
    except Exception as e:
        print(f"[fillform] error while filling: {e}")
        return "failed"

    if not filled:
        print("[fillform] No recognizable fields found -- needs a site-specific "
              "adapter or manual application.")
        return "failed"

    # Note in README: role-specific documents (e.g. a quest scenario for
    # Square Enix) must be attached manually -- this tool won't guess
    # those uploads.

    if SUBMIT:
        try:
            submit_btn = page.query_selector(
                "button[type='submit'], input[type='submit']"
            )
            if submit_btn:
                submit_btn.click()
                time.sleep(2)
                return "submitted"
            print("[fillform] No submit button found; leaving for manual review.")
            return "filled_pending_review"
        except Exception as e:
            print(f"[fillform] submit failed: {e}")
            return "failed"
    else:
        print(f"[fillform] Filled. Review and submit manually "
              f"(waiting {PAUSE_FOR_REVIEW_SECONDS}s) ...")
        time.sleep(PAUSE_FOR_REVIEW_SECONDS)
        return "filled_pending_review"


def run_fillform():
    cv = load_json(CV_JSON_PATH, {})
    if not cv:
        print(f"[fillform] {CV_JSON_PATH} not found or empty -- run cv2json.py first.")
        return

    jobs = load_json(APPLY_JSON_PATH, [])
    if not jobs:
        print(f"[fillform] {APPLY_JSON_PATH} not found or empty -- run search.py first.")
        return

    done = load_json(DONE_APPLY_JSON_PATH, [])
    done_links = {d.get("apply_link") for d in done}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        for job in jobs:
            if job.get("apply_link") in done_links:
                continue

            status = apply_to_job(page, job, cv)
            record = {**job, "status": status}
            done.append(record)
            save_json(DONE_APPLY_JSON_PATH, done)  # save progress incrementally

        browser.close()

    submitted = sum(1 for d in done if d.get("status") == "submitted")
    pending = sum(1 for d in done if d.get("status") == "filled_pending_review")
    failed = sum(1 for d in done if d.get("status") == "failed")
    print(f"[fillform] Done. submitted={submitted}, pending_review={pending}, failed={failed}")


if __name__ == "__main__":
    run_fillform()
