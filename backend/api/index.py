import logging
import re
import dotenv, httpx, json, os, uuid
from fastapi import FastAPI, Form, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .pdf_parser import parse_attendance_pdf, compute_stats, extract_student_info
from .course_scraper import scrape_course_names, resolve_course_name
from .session_store import session_store as redis

# Logging - redact sensitive fields
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _redact(value: str, show: int = 4) -> str:
    """Redact a string, showing only the last `show` characters."""
    if not value or len(value) <= show:
        return "***"
    return "*" * (len(value) - show) + value[-show:]

dotenv.load_dotenv()

class LoginData(BaseModel):
    token: str
    userID: str
    password: str
    captcha: str

# Load environment variables
CAPTCHA = os.getenv("CAPTCHA")
PORTAL = os.getenv("PORTAL")
REQUEST = os.getenv("REQUEST")
PDF = os.getenv("PDF")
SESSION_ID = os.getenv("SESSION_ID")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "https://pl-neduet.vercel.app").split(",") if o.strip()]

app = FastAPI()

# CORS - restricted to known origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Token", "X-User-Id", "X-Password", "X-Captcha"],
    expose_headers=["X-Session-Token"],
)

# Security headers
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Rate limiting (in-memory, per-IP)
import time
from collections import defaultdict
_rate_limits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_REQUESTS = 30  # per window

def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if rate-limited."""
    now = time.time()
    window = _rate_limits[ip]
    # Prune old entries
    _rate_limits[ip] = [t for t in window if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[ip]) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    _rate_limits[ip].append(now)
    return True

# Input validation
_USER_ID_RE = re.compile(r"^[A-Za-z0-9\-_]{1,30}$")

def _validate_user_id(user_id: str) -> str:
    """Validate student ID format."""
    if not _USER_ID_RE.match(user_id):
        raise HTTPException(status_code=400, detail="Invalid student ID format")
    return user_id

def _sanitize_filename(name: str) -> str:
    """Remove characters unsafe for Content-Disposition filenames."""
    return re.sub(r'[^\w\s\-.()]', '', name).strip()[:100]

@app.get("/api/captcha")
async def get_captcha(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        captcha_res = await client.get(CAPTCHA)
        session_id = captcha_res.cookies.get(SESSION_ID)

        if not session_id:
            logger.error("Failed to retrieve session ID from portal captcha")
            raise HTTPException(status_code=500, detail="Could not retrieve SESSION ID")

        token = str(uuid.uuid4())
        redis.setex(key=token, value=session_id, seconds=300)

        logger.info(f"Captcha issued to {client_ip}")
        response = Response(content=captcha_res.content, media_type="image/png")
        response.headers["X-Session-Token"] = token
        return response


async def _login_and_fetch_pdf(client: httpx.AsyncClient, x_token: str, x_user_id: str, x_password: str, x_captcha: str) -> bytes:
    """Shared logic: validate session, login to portal, fetch attendance PDF.

    Uses the caller-provided client. Returns the PDF bytes.
    The client remains open for the caller to reuse (e.g., scraping).
    """
    x_user_id = _validate_user_id(x_user_id)

    SESSION = redis.get(x_token)
    if not SESSION:
        raise HTTPException(status_code=400, detail="Session expired :(")

    client.cookies.set(SESSION_ID, SESSION)

    REQUEST_DATA = json.loads(REQUEST % (x_user_id, x_password, x_captcha))

    login_res = await client.post(PORTAL, data=REQUEST_DATA)

    if b"Please provide correct" in login_res.content:
        logger.warning(f"Failed login attempt for user {_redact(x_user_id)}")
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials or CAPTCHA :/"
        )

    pdf_res = await client.get(PDF % x_user_id)

    if not pdf_res.content:
        raise HTTPException(
            status_code=404,
            detail="Can't find attendance D:"
        )

    return pdf_res.content


@app.get("/api/attendance")
async def get_attendance(
    request: Request,
    x_token: str = Header(...),
    x_user_id: str = Header(...),
    x_password: str = Header(...),
    x_captcha: str = Header(...),
):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait.")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            pdf_content = await _login_and_fetch_pdf(client, x_token, x_user_id, x_password, x_captcha)

        # Extract student name for filename (sanitized for Content-Disposition)
        info = extract_student_info(pdf_content)
        student_name = _sanitize_filename(info.get("name", "").replace(" ", "_")) or "Student"
        roll_no = _sanitize_filename(info.get("roll_no", "")) or x_user_id
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{student_name}({roll_no})-attendance-{date_str}.pdf"

        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Portal timed out D: Try again later :)"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Portal request failed, please try again later :)"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Internal error in /api/attendance: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong O_O, please try again later :)"
        )


@app.get("/api/stats")
async def get_stats(
    request: Request,
    x_token: str = Header(...),
    x_user_id: str = Header(...),
    x_password: str = Header(...),
    x_captcha: str = Header(...),
):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait.")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            pdf_bytes = await _login_and_fetch_pdf(client, x_token, x_user_id, x_password, x_captcha)

            # Try to scrape course names from the portal using the same session
            try:
                scraped_names = await scrape_course_names(client)
            except Exception:
                scraped_names = {}

        # Parse the PDF and compute stats
        courses = parse_attendance_pdf(pdf_bytes)

        if not courses:
            raise HTTPException(
                status_code=422,
                detail="Could not parse attendance data from PDF"
            )

        stats = compute_stats(courses)

        # Enrich with course names
        for course in stats["courses"]:
            course["course_name"] = resolve_course_name(
                course["course_code"], scraped_names
            )

        return stats

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Portal timed out D: Try again later :)"
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="Portal request failed, please try again later :)"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Internal error in /api/stats: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong O_O, please try again later :)"
        )


@app.post("/api/logout")
async def logout(request: Request):
    """Invalidate a session token."""
    x_token = request.headers.get("X-Token", "")
    if x_token:
        try:
            redis.delete(x_token)
        except Exception:
            pass
    logger.info("Session invalidated on logout")
    return {"ok": True}