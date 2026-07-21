import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// ── Bearer token auth ──────────────────────────────────────────────────────
// The backend accepts EITHER an httpOnly cookie OR an "Authorization: Bearer
// <token>" header. We use Bearer tokens stored in localStorage to sidestep
// the CORS+credentials edge case (a response with Access-Control-Allow-Origin:
// "*" AND Access-Control-Allow-Credentials: true is rejected by browsers and
// surfaces in axios as "Network Error"). Bearer tokens work over any origin
// without needing credentials mode.

const ACCESS_TOKEN_KEY = "artisan.access_token";

export const getAccessToken = () => {
  try { return localStorage.getItem(ACCESS_TOKEN_KEY) || ""; } catch { return ""; }
};
export const setAccessToken = (t) => {
  try {
    if (t) localStorage.setItem(ACCESS_TOKEN_KEY, t);
    else localStorage.removeItem(ACCESS_TOKEN_KEY);
  } catch { /* ignore quota / privacy-mode errors */ }
};
export const clearAccessToken = () => setAccessToken("");

export const api = axios.create({ baseURL: API });

// Attach Bearer token on every outgoing request when present.
api.interceptors.request.use((config) => {
  const tok = getAccessToken();
  if (tok) {
    config.headers = config.headers || {};
    config.headers["Authorization"] = `Bearer ${tok}`;
  }
  return config;
});

// Auto-clear on 401 so the app falls back to /login cleanly.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      // Only clear if we actually had a token (avoid clobbering during
      // the very first /auth/me check that happens before login).
      if (getAccessToken()) clearAccessToken();
    }
    return Promise.reject(err);
  }
);

export const fmtINR = (n) => {
  const val = Number(n || 0);
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(val);
};

export const fmtNum = (n) =>
  new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Number(n || 0));

export const fmtDate = (d) => {
  if (!d) return "—";
  try {
    const dt = new Date(d);
    return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return d;
  }
};

export const toISO = (d) => {
  if (!d) return null;
  if (typeof d === "string") return d;
  return new Date(d).toISOString();
};

export const CATEGORIES = [
  "Chandelier", "Hanging Light", "Wall Light", "Table Lamp",
  "Ceiling Light", "Floor Lamp", "Candle Stand", "Glass",
];

export const MODES = ["RHUF", "ICICI", "UPI", "Cash", "Raks"];
