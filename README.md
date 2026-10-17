# NEDUET Instant Attendance
This is a FastAPI + React application that logs into the NEDUET undergraduate portal for you and serves your attendance — as a readable stats dashboard and as the original PDF — right in your web browser.

### Why?
The official portal makes it difficult to view your attendance without downloading a file and renaming it (Fairly difficult on mobile). This program simply displays your attendance without all the extra work — and adds per-course stats like theory/practical breakdowns and how many classes you can still skip while staying above 75%.

## Tech Stack
- Python, FastAPI, httpx, pdfplumber, BeautifulSoup4
- React 19, TypeScript, Vite
- Upstash Redis (session + course-map cache)
- Vercel

## Installation
1. Clone the repository
```
git clone <your-fork-url>
cd instant-attendance
```
2. Backend setup
```
cd backend
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
python -m pip install -r requirements.txt
```
3. Configure `backend/.env` with the portal endpoints and (optionally) Upstash Redis credentials:
```
CAPTCHA=<portal captcha image URL>
PORTAL=<portal login URL>
REQUEST=<login form JSON template>
PDF=<attendance PDF URL template>
SESSION_ID=<portal session cookie name>
UPSTASH_REDIS_REST_URL=<optional, for production sessions/cache>
UPSTASH_REDIS_REST_TOKEN=<optional>
```
Without Redis credentials, an in-memory session store is used (local dev only).

4. Frontend setup
```
cd frontend
npm install
```

5. Run locally (two terminals)
```
# Backend (terminal 1)
cd backend
source venv/bin/activate
python -m uvicorn api.index:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm run dev
```
The Vite dev server proxies `/api/*` to `http://localhost:8000`.

## How to use?
Simply login to the portal using the ID and password you use in the official portal. Once you've logged in, the app fetches your attendance and shows:
- **Stats tab** — overall attendance, per-course cards with theory/practical breakdowns, status (safe/warning/danger), and how many classes you can skip while staying above the 75% requirement. Course titles are scraped live from your registered-courses page (with a built-in fallback map) and cached for 6 hours.
- **PDF tab** — the original attendance PDF, viewable inline and downloadable with a proper filename.

## How does it work?
> This application does not have access to official databases and is done through requests!

- Fetches the portal CAPTCHA and keeps the portal session in Redis (or memory locally)
- Logs in for you on the official portal using your credentials + CAPTCHA
- Downloads your attendance PDF and parses it (theory/practical splits included)
- Scrapes your course titles from the portal's Registered Courses page (cached)
- Serves the stats dashboard and the PDF through your browser
- Logout invalidates the server-side session; passwords are never stored

# License
This project is released under the [MIT License](LICENSE).

Feel free to modify and adapt it for your institution or personal use.
