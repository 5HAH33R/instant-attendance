from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import dotenv, httpx, json, os, uuid, upstash_redis

dotenv.load_dotenv()

redis = upstash_redis.Redis(
    url=os.getenv("REDIS_URL"),
    token=os.getenv("REDIS_TOKEN")
)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reuse one outbound client per warm function instance.
    app.state.http = httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
    )
    yield
    await app.state.http.aclose()


app = FastAPI(lifespan=lifespan)
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
    client = app.state.http
    captcha_res = await client.get(CAPTCHA)
    session_id = captcha_res.cookies.get(SESSION_ID)

    if not session_id:
        raise HTTPException(status_code=500, detail="Could not retrieve SESSION ID")

    token = str(uuid.uuid4())
    redis.setex(key=token, value=session_id, seconds=300)

    response = Response(content=captcha_res.content, media_type="image/png")
    response.headers["X-Session-Token"] = token
    return response

@app.post("/attendance")
async def login(
    data: LoginData,
    request: Request
):
    client = request.app.state.http
    SESSION = redis.get(data.token)
    REQUEST_DATA = json.loads(REQUEST % (data.userID, data.password, data.captcha))

    if not SESSION:
        raise HTTPException(status_code=400, detail="Session expired :(")
    
    request_cookies = {SESSION_ID: SESSION}

    login_res = await client.post(PORTAL, data=REQUEST_DATA, cookies=request_cookies)

    if b"Please provide correct" in login_res.content:
        raise HTTPException(status_code=401, detail="Invalid credentials or CAPTCHA :/")

    pdf_cookies = dict(request_cookies)
    pdf_cookies.update(login_res.cookies)

    pdf_req = client.build_request("GET", PDF % data.userID, cookies=pdf_cookies)
    pdf_res = await client.send(pdf_req, stream=True)

    if pdf_res.status_code >= 400:
        await pdf_res.aclose()
        raise HTTPException(status_code=404, detail="Can't find attendance D:")

    if pdf_res.headers.get("content-length") == "0":
        await pdf_res.aclose()
        raise HTTPException(status_code=404, detail="Can't find attendance D:")

    async def iter_pdf():
        try:
            async for chunk in pdf_res.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await pdf_res.aclose()

    return StreamingResponse(iter_pdf(), media_type="application/pdf")