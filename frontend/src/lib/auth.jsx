import { createContext, useContext, useEffect, useState } from "react";
import { api, setAccessToken, clearAccessToken, getAccessToken } from "../lib/api";

const AuthCtx = createContext({ user: null, ready: false, refresh: () => {}, login: () => {}, logout: () => {} });

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);      // authenticated user object
  const [ready, setReady] = useState(false);   // whether the initial /me check has completed
  const [status, setStatus] = useState({ has_admin: true, environment: "development", reset_enabled: false });

  const refresh = async () => {
    try {
      const s = await api.get("/auth/status");
      setStatus(s.data);
    } catch (e) { /* no-op */ }
    // Skip /auth/me when we have no token — avoids a guaranteed 401 that
    // could clear other state and surfaces as a "Network Error" if the
    // backend is briefly unavailable.
    if (!getAccessToken()) {
      setUser(null);
      setReady(true);
      return;
    }
    try {
      const r = await api.get("/auth/me");
      setUser(r.data);
    } catch {
      setUser(null);
    } finally {
      setReady(true);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line
  }, []);

  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    // Persist the token for subsequent requests (Authorization: Bearer …).
    if (r?.data?.access_token) setAccessToken(r.data.access_token);
    setUser(r.data.user);
    return r.data.user;
  };

  const logout = async () => {
    try { await api.post("/auth/logout", {}); } catch (e) { /* ignore */ }
    clearAccessToken();
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, ready, status, refresh, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
