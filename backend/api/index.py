from fastapi import FastAPI, Form, HTTPException, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import dotenv, httpx, json, os, uuid

from .pdf_parser import parse_attendance_pdf, compute_stats
from .course_scraper import scrape_course_names, resolve_course_name
from .session_store import session_store as redis

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

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://ned-attendance.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Token"]
)

@app.get("/captcha")
async def get_captcha():
    async with httpx.AsyncClient(timeout=30.0) as client:
        captcha_res = await client.get(CAPTCHA)
        session_id = captcha_res.cookies.get(SESSION_ID)

        if not session_id:
            raise HTTPException(status_code=500, detail="Could not retrieve SESSION ID")

        token = str(uuid.uuid4())
        redis.setex(key=token, value=session_id, seconds=300)

        response = Response(content=captcha_res.content, media_type="image/png")
        response.headers["X-Session-Token"] = token
        return response


async def _login_and_fetch_pdf(client: httpx.AsyncClient, x_token: str, x_user_id: str, x_password: str, x_captcha: str) -> bytes:
    """Shared logic: validate session, login to portal, fetch attendance PDF.

    Uses the caller-provided client. Returns the PDF bytes.
    The client remains open for the caller to reuse (e.g., scraping).
    """
    SESSION = redis.get(x_token)
    if not SESSION:
        raise HTTPException(status_code=400, detail="Session expired :(")

    client.cookies.set(SESSION_ID, SESSION)

    REQUEST_DATA = json.loads(REQUEST % (x_user_id, x_password, x_captcha))

    login_res = await client.post(PORTAL, data=REQUEST_DATA)

    if b"Please provide correct" in login_res.content:
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


@app.get("/attendance")
async def get_attendance(
    x_token: str = Header(...),
    x_user_id: str = Header(...),
    x_password: str = Header(...),
    x_captcha: str = Header(...),
):
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            pdf_content = await _login_and_fetch_pdf(client, x_token, x_user_id, x_password, x_captcha)

        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=attendance.pdf"},
        )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Portal timed out D: Try again later :)"
        )

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Portal request failed: {str(e)}, please try again later :)"
        )

    except HTTPException:
        raise

    except Exception as e:
        print("Internal Server Error:", e)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong O_O, please try again later :)"
        )


@app.get("/stats")
async def get_stats(
    x_token: str = Header(...),
    x_user_id: str = Header(...),
    x_password: str = Header(...),
    x_captcha: str = Header(...),
):
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

    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Portal request failed: {str(e)}, please try again later :)"
        )

    except HTTPException:
        raise

    except Exception as e:
        print("Internal Server Error:", e)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong O_O, please try again later :)"
        )