"""
search.py
---------
Scrapes job listings and saves matches to apply.json.

Every job board has different HTML, so this uses a "site adapter"
pattern: each adapter knows how to search one site and yield
normalized job dicts. Add a new adapter class per site you want to
support, and register it in ADAPTERS at the bottom.

Only a couple of adapters are stubbed out here with the CSS
selectors left as TODOs -- you'll need to open devtools on the
target site and fill those in, since selectors change often and
scraping logic that "just works" across arbitrary sites doesn't
really exist.
"""

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator

from playwright.sync_api import sync_playwright, Page

APPLY_JSON_PATH = Path("apply.json")

# ---- Search configuration -------------------------------------------------

ROLES = [
    "Software Developer",
    "Web Developer",
    "Game Developer",
]

LOCATIONS = [
    "Japan",
    "USA",
    "Switzerland",
]

MAX_RESULTS_PER_SITE = 30


@dataclass
class JobListing:
    company: str
    role: str
    salary: str
    apply_link: str
    country: str
    address: str

    def dedupe_key(self) -> str:
        return f"{self.company}::{self.role}::{self.apply_link}"


# ---- Site adapters ----------------------------------------------------------

class BaseAdapter:
    name = "base"
    base_url = ""

    def search(self, page: Page, role: str, location: str) -> Iterator[JobListing]:
        raise NotImplementedError


class LinkedInAdapter(BaseAdapter):
    """
    NOTE: LinkedIn actively blocks automated scraping and requires login.
    Prefer their official Jobs API / partner feeds where possible, and
    respect their Terms of Service and robots.txt. Treat this as a
    starting point you'll need to adapt (and likely rate-limit heavily,
    or handle login/2FA manually) rather than a drop-in scraper.
    """
    name = "linkedin"
    base_url = "https://www.linkedin.com/jobs/search"

    def search(self, page: Page, role: str, location: str) -> Iterator[JobListing]:
        query = f"{self.base_url}/?keywords={role}&location={location}"
        page.goto(query, wait_until="domcontentloaded")
        time.sleep(2)

        # TODO: update these selectors to match the current LinkedIn DOM.
        cards = page.query_selector_all("div.job-search-card")
        for card in cards[:MAX_RESULTS_PER_SITE]:
            try:
                company = card.query_selector(".base-search-card__subtitle").inner_text().strip()
                title = card.query_selector(".base-search-card__title").inner_text().strip()
                link_el = card.query_selector("a.base-card__full-link")
                link = link_el.get_attribute("href") if link_el else None
                address = card.query_selector(".job-search-card__location")
                address_text = address.inner_text().strip() if address else location

                if not link:
                    continue

                yield JobListing(
                    company=company,
                    role=title,
                    salary="Negotiable",
                    apply_link=link,
                    country=location,
                    address=address_text,
                )
            except Exception as e:
                print(f"[search][linkedin] skipped a card: {e}")


class IndeedAdapter(BaseAdapter):
    name = "indeed"
    base_url = "https://www.indeed.com/jobs"

    def search(self, page: Page, role: str, location: str) -> Iterator[JobListing]:
        query = f"{self.base_url}?q={role}&l={location}"
        page.goto(query, wait_until="domcontentloaded")
        time.sleep(2)

        # TODO: update these selectors to match the current Indeed DOM.
        cards = page.query_selector_all("div.job_seen_beacon")
        for card in cards[:MAX_RESULTS_PER_SITE]:
            try:
                company_el = card.query_selector("span.companyName")
                title_el = card.query_selector("h2.jobTitle a")
                salary_el = card.query_selector("div.salary-snippet-container")
                address_el = card.query_selector("div.companyLocation")

                if not title_el:
                    continue

                relative_link = title_el.get_attribute("href")
                link = f"https://www.indeed.com{relative_link}" if relative_link else None
                if not link:
                    continue

                yield JobListing(
                    company=company_el.inner_text().strip() if company_el else "Unknown",
                    role=title_el.inner_text().strip(),
                    salary=salary_el.inner_text().strip() if salary_el else "Negotiable",
                    apply_link=link,
                    country=location,
                    address=address_el.inner_text().strip() if address_el else location,
                )
            except Exception as e:
                print(f"[search][indeed] skipped a card: {e}")


ADAPTERS = [
    IndeedAdapter(),
    LinkedInAdapter(),
    # Add more adapters here, e.g. a SquareEnixCareersAdapter for
    # company-specific career pages.
]


# ---- Orchestration ----------------------------------------------------------

def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            existing = json.load(f)
        except json.JSONDecodeError:
            return {}
    return {JobListing(**j).dedupe_key(): j for j in existing}


def save_results(path: Path, jobs_by_key: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(jobs_by_key.values()), f, indent=2, ensure_ascii=False)


def run_search():
    seen = load_existing(APPLY_JSON_PATH)
    new_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headed, so CAPTCHAs are visible if they appear
        context = browser.new_context()
        page = context.new_page()

        for adapter in ADAPTERS:
            for role in ROLES:
                for location in LOCATIONS:
                    print(f"[search] {adapter.name}: '{role}' in '{location}'")
                    try:
                        for job in adapter.search(page, role, location):
                            key = job.dedupe_key()
                            if key not in seen:
                                seen[key] = asdict(job)
                                new_count += 1
                    except Exception as e:
                        print(f"[search] adapter {adapter.name} failed for "
                              f"{role}/{location}: {e}")
                    time.sleep(1.5)  # be polite between queries

        browser.close()

    save_results(APPLY_JSON_PATH, seen)
    print(f"[search] Done. {new_count} new listings added, "
          f"{len(seen)} total in {APPLY_JSON_PATH}.")


if __name__ == "__main__":
    run_search()
