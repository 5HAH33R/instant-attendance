import io
import math
import re
from datetime import datetime
import pdfplumber


def extract_student_info(pdf_bytes: bytes) -> dict:
    """Extract student name and roll number from the attendance PDF.

    Looks for patterns like: Student Name : MUHAMMAD SHAHEER KHAN Roll No. : CT-182
    Returns dict with 'name' and 'roll_no' keys.
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Match student name
            name_match = re.search(r"Student\s*Name\s*:\s*(.+?)(?:\s*Roll|$)", text, re.IGNORECASE)
            roll_match = re.search(r"Roll\s*No\.?\s*:\s*(\S+)", text, re.IGNORECASE)

            name = name_match.group(1).strip() if name_match else ""
            roll_no = roll_match.group(1).strip() if roll_match else ""

            if name or roll_no:
                return {"name": name, "roll_no": roll_no}

    return {"name": "", "roll_no": ""}


def generate_attendance_filename(roll_no: str) -> str:
    """Generate a filename like Name(roll-no)-attendance-date.pdf.

    Uses roll_no from the header since we can't get the name without
    fetching the PDF first. The name will be added by the caller.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    return f"attendance-{roll_no}-{date_str}.pdf"


def _clean_number(val) -> int:
    """Convert a value to int, handling strings, floats, and edge cases."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    val = str(val).strip().replace(",", "")
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 0


def _clean_percentage(val) -> float:
    """Convert a value to float percentage, handling '84.44%' format."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip().replace("%", "")
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _find_header_row(table: list[list]) -> dict[str, int] | None:
    """Identify the header row and map column names to indices.

    Returns a dict mapping semantic names to column indices, or None if
    no recognizable header is found.
    """
    for row in table:
        if not row:
            continue
        # Normalize cells to lowercase strings for matching
        cells = [str(c).strip().lower() if c else "" for c in row]

        col_map = {}

        for i, cell in enumerate(cells):
            if not cell:
                continue
            if "course" in cell or "subject" in cell:
                col_map["course_code"] = i
            elif cell in ("section", "sec"):
                col_map["section"] = i
            elif "total" in cell and ("class" in cell or "lec" in cell or "held" in cell):
                col_map["total_classes"] = i
            elif ("attended" in cell or "present" in cell or "taken" in cell) and (
                "class" in cell or "lec" in cell
            ):
                col_map["attended_classes"] = i
            elif cell in ("%", "percentage", "perc", "attendance", "att %", "att%"):
                col_map["percentage"] = i

        # Need at minimum course_code and total_classes to be useful
        if "course_code" in col_map and "total_classes" in col_map:
            return col_map

    return None


def _detect_neduet_table(table: list[list]) -> bool:
    """Check if this table matches the NEDUET attendance PDF format.

    NEDUET format has multi-row headers with Theory/Practical split columns.
    Example header rows:
      ['', None, None, None, None, None, None, None, None, None]
      ['S.No.', 'Course Code', None, 'Credit Hrs', 'Theory', None, None, 'Practical', None, 'Percentage']
      [None, None, None, None, 'Present', None, 'Held', 'Present', 'Held', None]
    """
    if len(table) < 3:
        return False

    # Scan first 4 rows for NEDUET-specific headers
    for row in table[:4]:
        if not row:
            continue
        cells = [str(c).strip().lower() if c else "" for c in row]
        if "course code" in cells or ("course" in " ".join(cells) and "s.no" in " ".join(cells)):
            # Found the main header row - check if next row has Present/Held
            idx = table.index(row)
            if idx + 1 < len(table) and table[idx + 1]:
                next_cells = [str(c).strip().lower() if c else "" for c in table[idx + 1]]
                if "present" in next_cells and "held" in next_cells:
                    return True
            # Also check if this row itself has Theory/Practical
            if "theory" in cells and "practical" in cells:
                return True

    return False


def _parse_neduet_table(table: list[list]) -> list[dict]:
    """Parse NEDUET-style attendance table with Theory/Practical split columns.

    Data rows look like:
      ['1', '', 'CS-252', '3 Th + 1 Pr', '45', None, '45', '30', '36', '95.83']
    Columns: S.No, (empty), Course Code, Credit Hrs, Theory Present, (gap), Theory Held, Practical Present, Practical Held, Percentage
    """
    courses = []

    # Find the main header row (contains 'Course Code')
    header_idx = None
    for idx, row in enumerate(table[:4]):
        if not row:
            continue
        cells = [str(c).strip().lower() if c else "" for c in row]
        if "course code" in cells or ("course" in " ".join(cells) and "s.no" in " ".join(cells)):
            header_idx = idx
            break

    if header_idx is None:
        return []

    header_row = [str(c).strip().lower() if c else "" for c in table[header_idx]]

    # Find course code column and percentage column from header
    course_col = None
    pct_col = None
    for i, cell in enumerate(header_row):
        if "course" in cell:
            course_col = i
        if "percentage" in cell or cell == "%":
            pct_col = i

    if course_col is None:
        return []

    # If percentage not in header row, check next row
    if pct_col is None and header_idx + 1 < len(table) and table[header_idx + 1]:
        next_row = [str(c).strip().lower() if c else "" for c in table[header_idx + 1]]
        for i, cell in enumerate(next_row):
            if "percentage" in cell or cell == "%":
                pct_col = i

    # Default percentage to last column
    if pct_col is None:
        pct_col = len(table[header_idx]) - 1

    # Find Theory Present, Theory Held, Practical Present, Practical Held columns
    # The row after the main header has 'Present'/'Held' labels
    theory_present_col = None
    theory_held_col = None
    practical_present_col = None
    practical_held_col = None

    present_held_row_idx = header_idx + 1
    if present_held_row_idx < len(table) and table[present_held_row_idx]:
        present_held_row = [str(c).strip().lower() if c else "" for c in table[present_held_row_idx]]
        # Track which section (Theory/Practical) each column belongs to using header row
        in_theory = False
        in_practical = False
        for i, cell in enumerate(header_row):
            if "theory" in cell:
                in_theory = True
                in_practical = False
            elif "practical" in cell:
                in_theory = False
                in_practical = True

            if i < len(present_held_row):
                if present_held_row[i] == "present":
                    if in_theory:
                        theory_present_col = i
                    elif in_practical:
                        practical_present_col = i
                elif present_held_row[i] == "held":
                    if in_theory:
                        theory_held_col = i
                    elif in_practical:
                        practical_held_col = i

    # Parse data rows (skip header rows)
    data_start = present_held_row_idx + 1 if present_held_row_idx < len(table) else header_idx + 1
    for row in table[data_start:]:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        # Try the header-indicated column first, then search nearby columns
        course_code = str(row[course_col] or "").strip()
        if not course_code or len(course_code) < 2:
            # The header column might be off by one - search adjacent columns
            for offset in [1, -1, 2]:
                try_idx = course_col + offset
                if 0 <= try_idx < len(row):
                    candidate = str(row[try_idx] or "").strip()
                    if candidate and len(candidate) >= 2 and re.match(r"^[A-Z]{2,}[-]?\d+", candidate):
                        course_code = candidate
                        break
        if not course_code or len(course_code) < 2:
            continue

        # Skip header/footer rows
        lower = course_code.lower()
        if lower in ("course", "subject", "total", "s.no", "sr#", "sr.", "average"):
            continue

        # Extract Theory and Practical values
        theory_present = _clean_number(row[theory_present_col]) if theory_present_col is not None and theory_present_col < len(row) else 0
        theory_held = _clean_number(row[theory_held_col]) if theory_held_col is not None and theory_held_col < len(row) else 0
        practical_present = _clean_number(row[practical_present_col]) if practical_present_col is not None and practical_present_col < len(row) else 0
        practical_held = _clean_number(row[practical_held_col]) if practical_held_col is not None and practical_held_col < len(row) else 0

        # Total = Theory Held + Practical Held; Attended = Theory Present + Practical Present
        total_classes = theory_held + practical_held
        attended_classes = theory_present + practical_present

        # If no practical columns found, try theory-only values
        if total_classes == 0 and theory_held > 0:
            total_classes = theory_held
            attended_classes = theory_present

        # Always calculate percentage from actual data (don't trust PDF column
        # which may show theory-only percentage instead of combined)
        percentage = round((attended_classes / total_classes) * 100, 2) if total_classes > 0 else 0.0

        if total_classes > 0:
            theory_pct = round((theory_present / theory_held) * 100, 2) if theory_held > 0 else 0.0
            practical_pct = round((practical_present / practical_held) * 100, 2) if practical_held > 0 else 0.0

            courses.append({
                "course_code": course_code,
                "section": "",
                "theory": {"present": theory_present, "held": theory_held, "percentage": theory_pct},
                "practical": {"present": practical_present, "held": practical_held, "percentage": practical_pct},
                "total_classes": total_classes,
                "attended_classes": attended_classes,
                "percentage": percentage,
            })

    return courses



def parse_attendance_pdf(pdf_bytes: bytes) -> list[dict]:
    """Parse attendance PDF bytes and extract course attendance data.

    Returns a list of dicts, each with keys:
        course_code, section, total_classes, attended_classes, percentage
    """
    courses = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()

            if not tables:
                # Fallback: try text-based parsing
                text = page.extract_text() or ""
                courses.extend(_parse_text_lines(text))
                continue

            for table in tables:
                # Check if this is a NEDUET-style table with Theory/Practical split
                if _detect_neduet_table(table):
                    courses.extend(_parse_neduet_table(table))
                    continue

                col_map = _find_header_row(table)
                if not col_map:
                    # Try treating the whole table as data if it has enough columns
                    continue

                # Find the header row index to skip it
                header_idx = None
                for idx, row in enumerate(table):
                    if not row:
                        continue
                    cells = [str(c).strip().lower() if c else "" for c in row]
                    if any("course" in c or "subject" in c for c in cells):
                        header_idx = idx
                        break

                data_start = (header_idx + 1) if header_idx is not None else 0

                for row in table[data_start:]:
                    if not row or all(c is None or str(c).strip() == "" for c in row):
                        continue

                    course_code_idx = col_map.get("course_code")
                    if course_code_idx is None or course_code_idx >= len(row):
                        continue

                    course_code = str(row[course_code_idx] or "").strip()
                    if not course_code or len(course_code) < 2:
                        continue

                    # Skip rows that look like headers or footers
                    lower = course_code.lower()
                    if lower in ("course", "subject", "total", "s.no", "sr#", "sr."):
                        continue

                    section_idx = col_map.get("section")
                    total_idx = col_map.get("total_classes")
                    attended_idx = col_map.get("attended_classes")
                    pct_idx = col_map.get("percentage")

                    section = str(row[section_idx] or "").strip() if section_idx is not None and section_idx < len(row) else ""
                    total_classes = _clean_number(row[total_idx]) if total_idx is not None and total_idx < len(row) else 0
                    attended_classes = _clean_number(row[attended_idx]) if attended_idx is not None and attended_idx < len(row) else 0
                    percentage = _clean_percentage(row[pct_idx]) if pct_idx is not None and pct_idx < len(row) else 0.0

                    # Calculate percentage if not provided
                    if percentage == 0.0 and total_classes > 0:
                        percentage = round((attended_classes / total_classes) * 100, 2)

                    # Skip rows with no meaningful data
                    if total_classes == 0:
                        continue

                    courses.append({
                        "course_code": course_code,
                        "section": section,
                        "theory": {"present": 0, "held": 0, "percentage": 0.0},
                        "practical": {"present": 0, "held": 0, "percentage": 0.0},
                        "total_classes": total_classes,
                        "attended_classes": attended_classes,
                        "percentage": percentage,
                    })

    return courses


def _parse_text_lines(text: str) -> list[dict]:
    """Fallback parser: extract attendance data from raw text lines.

    Looks for lines containing course-code-like patterns followed by numbers.
    """
    courses = []
    # Pattern: course code (letters+digits), optional section, then 3+ numbers
    pattern = re.compile(
        r"([A-Z]{2,}\d{3,})"       # course code like CS301
        r"\s+"
        r"([A-Z])?\s*"             # optional section letter
        r"(\d+)\s+"                # total classes
        r"(\d+)\s+"                # attended classes
        r"(\d+\.?\d*)",            # percentage
        re.IGNORECASE,
    )

    for line in text.split("\n"):
        match = pattern.search(line)
        if match:
            course_code = match.group(1).strip()
            section = match.group(2) or ""
            total = int(match.group(3))
            attended = int(match.group(4))
            pct = float(match.group(5))

            if total > 0:
                courses.append({
                    "course_code": course_code,
                    "section": section,
                    "theory": {"present": 0, "held": 0, "percentage": 0.0},
                    "practical": {"present": 0, "held": 0, "percentage": 0.0},
                    "total_classes": total,
                    "attended_classes": attended,
                    "percentage": pct,
                })

    return courses


def compute_stats(courses: list[dict]) -> dict:
    """Compute derived statistics from parsed course attendance data.

    Returns dict with 'courses' (enriched) and 'overall' summary.
    """
    THRESHOLD = 0.75  # 75% minimum attendance requirement
    SAFE = 85.0
    WARNING = 75.0

    enriched = []
    total_all = 0
    attended_all = 0

    for course in courses:
        total = course["total_classes"]
        attended = course["attended_classes"]
        pct = course["percentage"]

        # Classes that can be skipped while staying >= 75%
        # min_required = minimum classes you must attend to stay at 75%
        # classes_to_skip = how many of the REMAINING classes you can skip
        if THRESHOLD > 0 and total > 0:
            min_required = math.ceil(total * THRESHOLD)
            classes_to_skip = max(0, attended - min_required)
        else:
            classes_to_skip = 0

        # Theory and practical skip counts
        theory = course.get("theory", {})
        practical = course.get("practical", {})
        theory_skip = 0
        practical_skip = 0

        if theory.get("held", 0) > 0 and theory.get("present", 0) > 0:
            theory_min = math.ceil(theory["held"] * THRESHOLD)
            theory_skip = max(0, theory["present"] - theory_min)

        if practical.get("held", 0) > 0 and practical.get("present", 0) > 0:
            practical_min = math.ceil(practical["held"] * THRESHOLD)
            practical_skip = max(0, practical["present"] - practical_min)

        # Determine status
        if pct >= SAFE:
            status = "safe"
        elif pct >= WARNING:
            status = "warning"
        else:
            status = "danger"

        enriched.append({
            **course,
            "classes_to_skip": classes_to_skip,
            "theory_skip": theory_skip,
            "practical_skip": practical_skip,
            "status": status,
        })

        total_all += total
        attended_all += attended

    # Overall stats
    overall_pct = round((attended_all / total_all) * 100, 2) if total_all > 0 else 0.0
    if overall_pct >= SAFE:
        overall_status = "safe"
    elif overall_pct >= WARNING:
        overall_status = "warning"
    else:
        overall_status = "danger"

    overall_skip = 0
    if THRESHOLD > 0 and total_all > 0:
        overall_min = math.ceil(total_all * THRESHOLD)
        overall_skip = max(0, attended_all - overall_min)

    return {
        "courses": enriched,
        "overall": {
            "total_classes": total_all,
            "attended_classes": attended_all,
            "percentage": overall_pct,
            "classes_to_skip": overall_skip,
            "status": overall_status,
        },
    }
