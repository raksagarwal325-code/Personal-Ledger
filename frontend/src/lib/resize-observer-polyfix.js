/**
 * ResizeObserver rAF-scheduling wrapper.
 *
 * Root-cause fix for the benign browser warning:
 *   "ResizeObserver loop completed with undelivered notifications"
 *
 * Why the warning happens:
 *   Some libraries (notably @floating-ui/dom, used by @radix-ui/react-popper
 *   which powers Radix Select / Popover / Dropdown positioning) invoke
 *   `update()` — a function that both reads and writes layout — SYNCHRONOUSLY
 *   from inside a ResizeObserver callback. If that write nudges the observed
 *   element's border box, the observer fires again in the same layout pass
 *   and the browser aborts delivery, dispatching an ErrorEvent on window with
 *   the "loop completed with undelivered notifications" message. React /
 *   webpack-dev-server's error overlay then surfaces that ErrorEvent as if it
 *   were a runtime exception.
 *
 * The fix:
 *   Wrap ResizeObserver so its callback is invoked inside requestAnimationFrame.
 *   The layout-write triggered by the callback then happens in the *next*
 *   frame, i.e. after the browser has finished delivering all notifications
 *   for the current one. The loop physically cannot form, so the warning is
 *   never emitted. Semantics are preserved: entries are still delivered, just
 *   one frame later — which is what floating-ui, Radix, react-resizable-panels
 *   etc. already assume internally on other code paths.
 *
 * This must run before any library instantiates a ResizeObserver, so it is
 * imported as the very first side-effect in src/index.js.
 */

if (typeof window !== "undefined" && typeof window.ResizeObserver === "function") {
  const NativeResizeObserver = window.ResizeObserver;

  class RafResizeObserver {
    constructor(callback) {
      let scheduled = false;
      let lastEntries = [];
      let lastObserver = null;

      this._native = new NativeResizeObserver((entries, observer) => {
        lastEntries = entries;
        lastObserver = observer;
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(() => {
          scheduled = false;
          try {
            callback(lastEntries, lastObserver);
          } catch (err) {
            // Preserve original throw semantics: report but don't swallow.
            // eslint-disable-next-line no-console
            console.error(err);
          }
        });
      });
    }
    observe(target, options) { this._native.observe(target, options); }
    unobserve(target) { this._native.unobserve(target); }
    disconnect() { this._native.disconnect(); }
  }

  // Preserve prototype identity checks that some libs use.
  RafResizeObserver.prototype.constructor = RafResizeObserver;

  window.ResizeObserver = RafResizeObserver;
}
