import json
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

# Load fallback course map once at module level
_COURSE_MAP_PATH = Path(__file__).parent / "course_map.json"
_FALLBACK_MAP: dict[str, str] = {}
try:
    with open(_COURSE_MAP_PATH) as f:
        _FALLBACK_MAP = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass


def _extract_courses_from_html(html: str) -> dict[str, str]:
    """Parse HTML to find course code -> name mappings.

    Looks for tables or list elements containing course codes and names.
    NEDUET portal pages typically have tables with rows like:
        CS301 | Computer Architecture | Section A | ...
    """
    soup = BeautifulSoup(html, "html.parser")
    course_map = {}

    # Course code pattern: CS-252, CT-261, EA-218, etc. (with optional hyphen)
    code_pattern = re.compile(r"^[A-Z]{2,}-?\d{2,}$")

    # Strategy 1: Look for tables with course data
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            for i in range(len(cells) - 1):
                code_cell = cells[i].get_text(strip=True)
                name_cell = cells[i + 1].get_text(strip=True)

                if code_pattern.match(code_cell):
                    if name_cell and not code_pattern.match(name_cell):
                        course_map[code_cell] = name_cell

    # Strategy 2: Look for select/option elements (dropdown menus)
    for select in soup.find_all("select"):
        for option in select.find_all("option"):
            value = option.get("value", "")
            text = option.get_text(strip=True)
            if code_pattern.match(value) and text:
                course_map[value] = text
            match = re.match(r"^([A-Z]{2,}-?\d{2,})\s*[-:]\s*(.+)$", text)
            if match:
                course_map[match.group(1)] = match.group(2).strip()

    # Strategy 3: Look for links or spans with course info
    for elem in soup.find_all(["a", "span", "div", "label", "td", "th", "li"]):
        text = elem.get_text(strip=True)
        match = re.match(r"^([A-Z]{2,}-?\d{2,})\s*[-:]\s*(.+)$", text)
        if match:
            course_map[match.group(1)] = match.group(2).strip()

    # Strategy 4: Look for text patterns like "CS-252 Object Oriented Programming"
    for elem in soup.find_all(["td", "th", "span", "div", "p"]):
        text = elem.get_text(strip=True)
        # Match course code followed by course name
        match = re.search(r"([A-Z]{2,}-?\d{2,})\s+([A-Z][a-zA-Z\s&]+?)(?:\s{2,}|\s*\(|$)", text)
        if match:
            code = match.group(1)
            name = match.group(2).strip()
            if len(name) > 3 and code not in course_map:
                course_map[code] = name

    return course_map


async def scrape_course_names(client) -> dict[str, str]:
    """Attempt to scrape course code -> name mappings from the NEDUET portal.

    Uses the already-authenticated httpx client session.
    Tries multiple portal pages that might list enrolled courses.
    Returns empty dict silently if all attempts fail.
    """
    portal_base = os.getenv("PORTAL", "")
    if not portal_base:
        return {}

    # Extract base URL from portal login URL
    # e.g., "https://pl.neduet.edu.pk/index.jsp" -> "https://pl.neduet.edu.pk"
    base_match = re.match(r"(https?://[^/]+)", portal_base)
    if not base_match:
        return {}
    base_url = base_match.group(1)

    # Common paths that might list courses on NEDUET portal
    candidate_paths = [
        "/undergrad/dashboard.jsp",
        "/undergrad/registered-courses.jsp",
        "/undergrad/timetable.jsp",
        "/undergrad/courses.jsp",
        "/undergrad/student-courses.jsp",
        "/undergrad/course-teacher.jsp",
        "/undergrad/attendance.jsp",
        "/undergrad/registration.jsp",
        "/undergrad/enrollment.jsp",
        "/undergrad/home.jsp",
        "/student/student-course-teacher",
        "/student/student-registered-course",
        "/student/course-teacher",
        "/student/registered-courses",
        "/student/courses",
        "/student/timetable",
        "/attendance",
        "/home",
    ]

    course_map = {}

    for path in candidate_paths:
        try:
            url = f"{base_url}{path}"
            resp = await client.get(url, follow_redirects=True, timeout=10.0)

            if resp.status_code != 200:
                continue

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                continue

            html = resp.text
            # Skip if redirected back to login
            if "login" in resp.url.path.lower() and "student" not in resp.url.path.lower():
                continue

            found = _extract_courses_from_html(html)
            if found:
                course_map.update(found)
                # If we found enough courses, we can stop early
                if len(course_map) >= 5:
                    break

        except Exception:
            continue

    return course_map


def resolve_course_name(course_code: str, scraped_map: dict[str, str] | None = None) -> str:
    """Resolve a course code to its human-readable name.

    Priority: scraped_map > fallback_map > raw code
    """
    if scraped_map and course_code in scraped_map:
        return scraped_map[course_code]
    if course_code in _FALLBACK_MAP:
        return _FALLBACK_MAP[course_code]
    return course_code
