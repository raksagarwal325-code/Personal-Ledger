import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api, setAccessToken } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { toast } from "sonner";

export default function Login() {
  const { user, ready, status, refresh, login } = useAuth();
  const nav = useNavigate();
  const [mode, setMode] = useState("login");       // "login" | "bootstrap"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    if (ready && user) nav("/", { replace: true });
  }, [ready, user, nav]);

  useEffect(() => {
    if (ready && !status.has_admin) setMode("bootstrap");
  }, [ready, status.has_admin]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErrorMsg("");
    try {
      if (mode === "bootstrap") {
        const r = await api.post("/admin/bootstrap", { email, password, name });
        if (r?.data?.access_token) setAccessToken(r.data.access_token);
        toast.success("First admin created — welcome.");
      } else {
        await login(email, password);
        toast.success("Signed in.");
      }
      await refresh();
      nav("/", { replace: true });
    } catch (err) {
      const msg = err?.response?.data?.detail || err.message || "Failed.";
      const finalMsg = typeof msg === "string" ? msg : "Failed.";
      setErrorMsg(finalMsg);
      toast.error(finalMsg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center"
         style={{ background: "var(--paper)" }}
         data-testid="login-page">
      <div className="w-full max-w-md px-6">
        <div className="mb-8 text-center">
          <h1 className="serif text-5xl">Artisan<span style={{ color: "var(--terracotta)" }}>.</span></h1>
          <div className="label-caps mt-2">Personal Ledger</div>
        </div>

        <div className="card-warm p-7 md:p-8">
          <div className="mb-5">
            <h2 className="serif text-2xl" data-testid="login-title">
              {mode === "bootstrap" ? "Create the first admin" : "Sign in"}
            </h2>
            <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
              {mode === "bootstrap"
                ? "This device has no admin yet. Set up the first admin account to continue."
                : "Enter your admin credentials to open the ledger."}
            </p>
          </div>

          <form className="space-y-4" onSubmit={submit}>
            {errorMsg && (
              <div
                data-testid="login-error"
                role="alert"
                className="text-xs px-3 py-2 rounded border"
                style={{
                  color: "#8a1f1f",
                  background: "#fdecec",
                  borderColor: "#f5c1c1",
                }}
              >
                {errorMsg}
              </div>
            )}
            {mode === "bootstrap" && (
              <div>
                <Label className="label-caps text-xs">Name (optional)</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)}
                       data-testid="login-name"
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
            )}
            <div>
              <Label className="label-caps text-xs">Email</Label>
              <Input type="email" value={email} required autoFocus
                     onChange={(e) => setEmail(e.target.value)}
                     data-testid="login-email"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs">Password</Label>
              <Input type="password" value={password} required minLength={6}
                     onChange={(e) => setPassword(e.target.value)}
                     data-testid="login-password"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <Button type="submit" disabled={busy}
                    data-testid="login-submit"
                    className="w-full bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {busy ? "Please wait…" : mode === "bootstrap" ? "Create admin & sign in" : "Sign in"}
            </Button>
          </form>

          <div className="mt-5 text-xs text-center" style={{ color: "var(--muted)" }}>
            Environment: <b>{status.environment}</b>
            {" · "}
            Reset {status.reset_enabled ? <b>enabled</b> : "disabled"}
          </div>
        </div>
      </div>
    </div>
  );
}
