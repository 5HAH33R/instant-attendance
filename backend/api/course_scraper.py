import json
import logging
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .session_store import session_store

logger = logging.getLogger(__name__)

# Load fallback course map once at module level
_COURSE_MAP_PATH = Path(__file__).parent / "course_map.json"
_FALLBACK_MAP: dict[str, str] = {}
try:
    with open(_COURSE_MAP_PATH) as f:
        _FALLBACK_MAP = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass


def _norm(code: str) -> str:
    """Normalize a course code for comparison.

    Handles CS-252 == CS252 and PDF suffixes like "CT-264 ( Opt )" -> CT264.
    """
    stripped = code.strip()
    # Prefer the leading letter+digit code token, dropping suffixes like " ( Opt )"
    m = re.match(r"([A-Za-z]{2,}-?\d+)", stripped)
    if m:
        return re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
    return re.sub(r"[^A-Z0-9]", "", stripped.upper())


# Prebuilt normalized fallback lookup: CT264 -> "Programming for Artificial Intelligence"
_FALLBACK_NORM: dict[str, str] = {_norm(k): v for k, v in _FALLBACK_MAP.items()}

_CODE_RE = re.compile(r"^[A-Z]{2,}-?\d{2,}$")
_SEMID_RE = re.compile(r"Students_Registered_Courses\.jsp\?semid=(\d+)", re.IGNORECASE)

CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours
_CACHE_PREFIX = "course_map"
_LATEST_KEY = f"{_CACHE_PREFIX}:latest"


_SMALL_WORDS = {"and", "or", "of", "for", "in", "the", "with", "to", "&"}


def _pretty_name(name: str) -> str:
    """Title-case scraped titles that are fully uppercase (portal style).

    Keeps small connecting words lowercase unless first ("Software Engineering",
    "Programming for Artificial Intelligence"). Caps length as a safeguard
    against a hostile/broken portal page storing multi-MB "titles".
    """
    if not name:
        return name
    name = name[:200]
    if not name.isupper():
        return name
    words = name.title().split(" ")
    return " ".join(
        w.lower() if i > 0 and w.lower() in _SMALL_WORDS else w
        for i, w in enumerate(words)
    )


def _extract_courses_from_html(html: str) -> dict[str, str]:
    """Parse HTML to find course code -> name mappings.

    Handles the registered-courses page table:
        S.No. | Course Code | Course Title | Course Mode
        1     | CT-264      | PROGRAMMING FOR ARTIFICIAL INTELLIGENCE | Theory/Practical
    """
    soup = BeautifulSoup(html, "html.parser")
    course_map = {}

    # Strategy 1: tables whose header contains "Course Code" + "Course Title"
    # (the registered-courses report table; skips student-info/fee tables)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_text = " ".join(
            row.get_text(" ", strip=True).lower() for row in rows[:3]
        )
        if "course code" not in header_text or "course title" not in header_text:
            continue

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            for i in range(len(cells) - 1):
                code_cell = cells[i].get_text(strip=True)
                name_cell = cells[i + 1].get_text(strip=True)

                if _CODE_RE.match(code_cell):
                    if name_cell and not _CODE_RE.match(name_cell):
                        course_map[code_cell] = _pretty_name(name_cell)

    # Strategy 2: Look for select/option elements (dropdown menus)
    for select in soup.find_all("select"):
        for option in select.find_all("option"):
            value = option.get("value", "")
            text = option.get_text(strip=True)
            if _CODE_RE.match(value) and text:
                course_map[value] = _pretty_name(text)
            match = re.match(r"^([A-Z]{2,}-?\d{2,})\s*[-:]\s*(.+)$", text)
            if match:
                course_map[match.group(1)] = _pretty_name(match.group(2).strip())

    # Strategy 3: Look for links or spans with course info
    for elem in soup.find_all(["a", "span", "div", "label", "td", "th", "li"]):
        text = elem.get_text(strip=True)
        match = re.match(r"^([A-Z]{2,}-?\d{2,})\s*[-:]\s*(.+)$", text)
        if match:
            course_map[match.group(1)] = _pretty_name(match.group(2).strip())

    # Strategy 4: Look for text patterns like "CS-252 Object Oriented Programming"
    for elem in soup.find_all(["td", "th", "span", "div", "p"]):
        text = elem.get_text(strip=True)
        match = re.search(r"([A-Z]{2,}-?\d{2,})\s+([A-Z][a-zA-Z\s&]+?)(?:\s{2,}|\s*\(|$)", text)
        if match:
            code = match.group(1)
            name = match.group(2).strip()
            if len(name) > 3 and code not in course_map:
                course_map[code] = _pretty_name(name)

    return course_map


def _cache_get(key: str) -> dict[str, str] | None:
    """Read a cached course map. Returns None on miss or error."""
    try:
        raw = session_store.get(key)
    except Exception as e:
        logger.warning(f"Course map cache read failed: {type(e).__name__}")
        return None

    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) and data else None


def _cache_set(key: str, course_map: dict[str, str]) -> None:
    """Write a course map to cache. Failures are logged, never raised."""
    try:
        session_store.setex(key=key, value=json.dumps(course_map), seconds=CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Course map cache write failed: {type(e).__name__}")


def _cache_semester(semid: str, course_map: dict[str, str]) -> None:
    """Cache under the concrete semester key and a 'latest' alias."""
    _cache_set(f"{_CACHE_PREFIX}:{semid}", course_map)
    _cache_set(_LATEST_KEY, course_map)


async def scrape_course_names(client) -> dict[str, str]:
    """Resolve course code -> name mappings, preferring the session-store cache.

    Warm path: return the cached map (`course_map:latest`, 6h TTL) immediately
    with zero portal requests.

    Cold path (cache miss):
    1. GET the dashboard and discover the current semester's
       Students_Registered_Courses.jsp?semid=N link.
    2. GET that page and parse the registered-courses table.
    3. Cache the result in the session store (Redis in prod) for 6 hours.

    On any failure, falls back to the last cached map (if any), else {}.
    Uses the already-authenticated httpx client session.
    """
    cached = _cache_get(_LATEST_KEY)
    if cached:
        return cached

    portal_base = os.getenv("PORTAL", "")
    if not portal_base:
        return {}

    # Extract base URL from portal login URL
    # e.g., "https://pl.neduet.edu.pk/index.jsp" -> "https://pl.neduet.edu.pk"
    base_match = re.match(r"(https?://[^/]+)", portal_base)
    if not base_match:
        return {}
    base_url = base_match.group(1)
    undergrad_base = f"{base_url}/undergrad"

    try:
        # Step 1: discover current semid from the dashboard
        dashboard = await client.get(f"{undergrad_base}/dashboard.jsp", follow_redirects=True, timeout=10.0)
        if dashboard.status_code != 200 or "text/html" not in dashboard.headers.get("content-type", ""):
            logger.warning(f"Dashboard fetch failed (status={dashboard.status_code}), using cached course map")
            return _cache_get(_LATEST_KEY) or {}

        semids = _SEMID_RE.findall(dashboard.text)
        if not semids:
            logger.warning("No Students_Registered_Courses semid link found on dashboard, using cached course map")
            return _cache_get(_LATEST_KEY) or {}

        semid = max(semids, key=int)

        # Step 2: fetch the registered courses page for that semester
        courses_url = f"{undergrad_base}/Students_Registered_Courses.jsp?semid={semid}"
        courses_res = await client.get(courses_url, follow_redirects=True, timeout=10.0)
        if courses_res.status_code != 200 or "text/html" not in courses_res.headers.get("content-type", ""):
            logger.warning(f"Registered courses fetch failed (status={courses_res.status_code}), using cached course map")
            return _cache_get(_LATEST_KEY) or {}

        course_map = _extract_courses_from_html(courses_res.text)
        if not course_map:
            logger.warning(f"No courses parsed from {courses_url}, using cached course map")
            return _cache_get(_LATEST_KEY) or {}

        # Step 3: cache for future requests
        _cache_semester(semid, course_map)
        logger.info(f"Scraped {len(course_map)} courses for semid={semid}")
        return course_map

    except Exception as e:
        logger.warning(f"Course scrape failed ({type(e).__name__}), using cached course map")
        return _cache_get(_LATEST_KEY) or {}


def resolve_course_name(course_code: str, scraped_map: dict[str, str] | None = None) -> str:
    """Resolve a course code to its human-readable name.

    Priority: scraped_map > fallback_map > raw code.
    Codes are compared with hyphens/punctuation stripped (CS-252 == CS252).
    """
    key = _norm(course_code)

    if scraped_map:
        scraped_norm = {_norm(k): v for k, v in scraped_map.items()}
        if key in scraped_norm:
            return scraped_norm[key]

    if key in _FALLBACK_NORM:
        return _FALLBACK_NORM[key]

    return course_code
