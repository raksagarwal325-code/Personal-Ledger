import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

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
