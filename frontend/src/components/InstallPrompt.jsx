import { useEffect, useState } from "react";
import { Download } from "lucide-react";

/**
 * Small install button that appears in the sidebar when the browser fires
 * `beforeinstallprompt`. On iOS Safari it shows a hint instead (Safari
 * does not fire the event but supports Add to Home Screen manually).
 */
export default function InstallPrompt() {
  const [deferred, setDeferred] = useState(null);
  const [installed, setInstalled] = useState(false);
  const [showIosHint, setShowIosHint] = useState(false);

  useEffect(() => {
    const isStandalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
    if (isStandalone) {
      setInstalled(true);
      return;
    }

    const onPrompt = (e) => {
      e.preventDefault();
      setDeferred(e);
    };
    const onInstalled = () => setInstalled(true);

    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);

    // iOS: no beforeinstallprompt — show manual hint
    const ua = window.navigator.userAgent || "";
    const isIos = /iPad|iPhone|iPod/.test(ua) && !window.MSStream;
    const isSafari = /^((?!chrome|android).)*safari/i.test(ua);
    if (isIos && isSafari) setShowIosHint(true);

    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (installed) return null;

  if (deferred) {
    return (
      <button
        data-testid="install-app-btn"
        onClick={async () => {
          deferred.prompt();
          try { await deferred.userChoice; } catch {}
          setDeferred(null);
        }}
        className="w-full flex items-center gap-2 px-3 py-2.5 rounded-md text-sm bg-[var(--terracotta)] text-white hover:bg-[var(--terracotta-hover)] transition-colors"
      >
        <Download size={15} strokeWidth={2} />
        <span>Install app</span>
      </button>
    );
  }

  if (showIosHint) {
    return (
      <div
        data-testid="ios-install-hint"
        className="text-xs px-3 py-2.5 rounded-md border"
        style={{ borderColor: "var(--border-warm)", background: "var(--surface-alt)", color: "var(--muted)" }}
      >
        <div className="font-medium mb-1" style={{ color: "var(--ink)" }}>Install on iPhone</div>
        Tap <span className="serif">Share</span> → <span className="serif">Add to Home Screen</span>.
      </div>
    );
  }

  return null;
}
