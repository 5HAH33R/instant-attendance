import { useEffect, useRef, useState } from "react";
import "./App.css";
import type { AttendanceStats } from "./types";
import StatsDashboard from "./StatsDashboard";

const getRandomNumber = (): number => {
  return Math.floor(Math.random() * 2) + 1;
};

type ViewState = "login" | "loading" | "results";
type ActiveTab = "stats" | "pdf";

// ─── PDF Viewer ───────────────────────────────────────────────────────────────

const PdfViewer = ({ pdfUrl }: { pdfUrl: string }) => {
  return (
    <div className="pdf-viewer-native">
      <object
        data={pdfUrl}
        type="application/pdf"
        width="100%"
        height="100%"
        style={{
          border: "none",
          minHeight: "80vh",
          borderRadius: "12px",
        }}
      >
        {/* Fallback for browsers that can't render PDF inline */}
        <embed
          src={pdfUrl}
          type="application/pdf"
          width="100%"
          height="100%"
          style={{
            border: "none",
            minHeight: "80vh",
            borderRadius: "12px",
          }}
        />
      </object>
    </div>
  );
};

// ─── Main Form ────────────────────────────────────────────────────────────────

const Form = () => {
  const [formData, setFormData] = useState({
    userID: "",
    password: "",
    captcha: "",
  });

  const [viewState, setViewState] = useState<ViewState>("login");
  const [activeTab, setActiveTab] = useState<ActiveTab>("stats");
  const [statsData, setStatsData] = useState<AttendanceStats | null>(null);
  const [randomizedVal] = useState(getRandomNumber());
  const [message, setMessage] = useState<string | null>(null);
  const [captchaUrl, setCaptchaUrl] = useState<string | null>(null);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [captchaLoading, setLoading] = useState(true);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const pdfUrlRef = useRef<string | null>(null);
  const credsRef = useRef<{ token: string; id: string; pass: string; captcha: string } | null>(null);

  const revokePdfUrl = () => {
    if (pdfUrlRef.current) {
      URL.revokeObjectURL(pdfUrlRef.current);
      pdfUrlRef.current = null;
    }
  };

  const loadCaptcha = async () => {
    setLoading(true);

    const res = await fetch(`/api/captcha`, {
      credentials: "omit",
    });

    const token = res.headers.get("X-Session-Token");
    const blob = await res.blob();

    setCaptchaToken(token);
    setCaptchaUrl(URL.createObjectURL(blob));
    setLoading(false);
  };

  useEffect(() => {
    loadCaptcha();
  }, []);

  useEffect(() => {
    const video = document.createElement("video");
    video.src = `/searching${randomizedVal}.mp4`;
    video.preload = "auto"; // tells browser to preload
  }, []);

  useEffect(() => {
    return () => {
      revokePdfUrl();
      if (captchaUrl) {
        URL.revokeObjectURL(captchaUrl);
      }
    };
  }, [captchaUrl]);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleForm = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setViewState("loading");
    setMessage("Fetching attendance");
    revokePdfUrl();
    setStatsData(null);
    setPdfUrl(null);

    const creds = {
      token: captchaToken || "",
      id: formData.userID,
      pass: formData.password,
      captcha: formData.captcha,
    };
    credsRef.current = creds;

    try {
      const response = await fetch(`/api/stats`, {
        method: "GET",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Token": creds.token,
          "X-User-Id": creds.id,
          "X-Password": creds.pass,
          "X-Captcha": creds.captcha,
        },
      });

      if (!response.ok) {
        const text = await response.json();
        throw new Error(text.detail);
      }

      const data: AttendanceStats = await response.json();
      setStatsData(data);
      setActiveTab("stats");
      setViewState("results");
      setMessage(null);
    } catch (err: any) {
      console.error(err);
      setViewState("login");
      setMessage(err.message || "Unable to load attendance");
      await loadCaptcha();
    }
  };

  const fetchPdf = async () => {
    if (pdfUrl || pdfLoading || !credsRef.current) return;
    setPdfLoading(true);

    try {
      const creds = credsRef.current;
      const response = await fetch(`/api/attendance`, {
        method: "GET",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Token": creds.token,
          "X-User-Id": creds.id,
          "X-Password": creds.pass,
          "X-Captcha": creds.captcha,
        },
      });

      if (!response.ok) {
        const text = await response.json();
        throw new Error(text.detail);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      pdfUrlRef.current = url;
      setPdfUrl(url);
    } catch (err: any) {
      console.error("PDF fetch error:", err);
      setMessage(err.message || "Unable to load PDF");
    } finally {
      setPdfLoading(false);
    }
  };

  const handleBackToLogin = async () => {
    revokePdfUrl();
    setPdfUrl(null);
    setStatsData(null);
    setViewState("login");
    setMessage(null);
    setFormData({
      userID: "",
      password: "",
      captcha: "",
    });
    credsRef.current = null;
    await loadCaptcha();
  };

  const handleTabChange = (tab: ActiveTab) => {
    setActiveTab(tab);
    if (tab === "pdf") {
      fetchPdf();
    }
  };

  return (
    <div className="container">
      {viewState !== "results" && (
        <div
          className="github-banner"
          onClick={() =>
            window.open(
              "https://github.com/muhammadrafayasif/instant-attendance",
              "_blank",
            )
          }
        >
          <img src="/github.webp" alt="GH" />
          View on GitHub
        </div>
      )}

      {viewState === "results" ? (
        <section className="results-shell">
          <div className="results-toolbar">
            <button
              type="button"
              className="back-button"
              onClick={handleBackToLogin}
            >
              Go Back
            </button>
            <div className="tab-bar">
              <button
                className={`tab-button ${activeTab === "stats" ? "active" : ""}`}
                onClick={() => handleTabChange("stats")}
              >
                Stats
              </button>
              <button
                className={`tab-button ${activeTab === "pdf" ? "active" : ""}`}
                onClick={() => handleTabChange("pdf")}
              >
                PDF
              </button>
            </div>
            {pdfUrl && (
              <button
                type="button"
                className="open-button"
                onClick={() => window.open(pdfUrl, "_blank")}
              >
                Open PDF
              </button>
            )}
          </div>

          {activeTab === "stats" && statsData && (
            <StatsDashboard stats={statsData} />
          )}

          {activeTab === "pdf" && (
            <>
              {pdfLoading ? (
                <div className="pdf-loading">
                  <div className="spinner" />
                  <p>Loading PDF...</p>
                </div>
              ) : pdfUrl ? (
                <PdfViewer pdfUrl={pdfUrl} />
              ) : (
                <div className="pdf-loading">
                  <p>Failed to load PDF</p>
                </div>
              )}
            </>
          )}
        </section>
      ) : (
        <form className="form" onSubmit={handleForm}>
          <h5 style={{ textAlign: "center", color: "blue", fontSize: "0.875rem", margin: "0 0 0.5rem 0", border: "2px solid blue", borderRadius: "6px", padding: "0.5rem" }}>
            Coming Soon: Instant Transcript
          </h5>
          <h2 style={{ textAlign: "center" }}>NED Instant Attendance</h2>
          <p>Login to your undergraduate portal to view your attendance.</p>

          <label>Student ID</label>
          <input
            type="username"
            name="userID"
            value={formData.userID}
            onChange={handleChange}
            required
            placeholder="Enter Portal ID"
          />

          {viewState !== "loading" && (
            <>
              <label>Password</label>
              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                required
                placeholder="Enter Password"
              />

              <label>CAPTCHA</label>
              <div className="captcha-container">
                {captchaLoading ? (
                  <img
                    src="/loading.gif"
                    height={25}
                    alt="Loading CAPTCHA..."
                  />
                ) : (
                  <img
                    src={captchaUrl || "/error.png"}
                    height={25}
                    alt="CAPTCHA"
                    onClick={() => loadCaptcha()}
                    style={{ cursor: "pointer" }}
                  />
                )}
              </div>
              <input
                type="captcha"
                name="captcha"
                value={formData.captcha}
                onChange={handleChange}
                required
                placeholder="Enter CAPTCHA"
              />
            </>
          )}

          <button type="submit" disabled={viewState === "loading"}>
            {viewState === "loading" ? "Fetching..." : "Login"}
          </button>

          {viewState === "loading" && (
            <>
              <p className="status-message loading">
                Searching for your attendance...
              </p>
              <video
                src={`/searching${randomizedVal}.mp4`}
                autoPlay
                loop
                muted
                playsInline
                style={{ width: "100%" }}
                className="loading-illustration"
              />
            </>
          )}

          {message && viewState === "login" && (
            <p className="status-message error">{message}</p>
          )}
        </form>
      )}
    </div>
  );
};

export default Form;