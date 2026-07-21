import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";
import { toast } from "sonner";
import { AlertTriangle, Download, ShieldAlert, Database, FlaskConical, History, Trash2, Loader2, ShieldCheck, ChevronDown, ChevronRight, Copy, RefreshCcw } from "lucide-react";

const PHRASE = {
  clear_transaction_data: "CLEAR TRANSACTION DATA",
  full_reset: "FULL RESET SAMRAT GLASS ERP",
};
const LABEL = {
  clear_transaction_data: "Clear Transaction Data",
  full_reset: "Full Application Reset",
};

function ScopeCard({ scope, danger = false, onPreview }) {
  return (
    <div className="card-warm p-6"
         style={danger ? { borderColor: "var(--danger)", borderWidth: 1.5 } : {}}
         data-testid={`dm-scope-card-${scope}`}>
      <div className="flex items-start gap-3">
        {danger ? <ShieldAlert size={22} style={{ color: "var(--danger)" }} />
                : <Database size={22} style={{ color: "var(--terracotta)" }} />}
        <div className="flex-1 min-w-0">
          <div className="serif text-xl">{LABEL[scope]}</div>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
            {scope === "clear_transaction_data"
              ? "Removes orders, purchases, payments, cash-book, transfers and party-ledger transactions. Keeps customers, vendors, products, accounts, admin users and settings."
              : "Removes nearly all business data and returns the ERP to a fresh state. Only the currently authenticated admin, audit logs and backups are preserved."}
          </p>
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <Button variant="outline"
                data-testid={scope === "clear_transaction_data" ? "dm-preview-clear-btn" : "dm-preview-full-btn"}
                onClick={() => onPreview(scope)}
                className="border-[var(--border-warm)]">
          Preview
        </Button>
        <Button variant="outline"
                data-testid={scope === "clear_transaction_data" ? "dm-clear-btn" : "dm-full-btn"}
                onClick={() => onPreview(scope, true)}
                style={danger ? { color: "var(--danger)", borderColor: "var(--danger)" } : {}}
                className="border-[var(--border-warm)]">
          {danger ? "Reset entire ERP…" : "Clear transactions…"}
        </Button>
      </div>
    </div>
  );
}

// ─── Phase 5 — Reconciliation card ────────────────────────────────────────

function ReconciliationCard({ report, last, busy, onRun, expanded, onToggle }) {
  const summary = report?.summary || last?.extra?.summary;
  const healthy = report ? report.healthy : (last?.extra?.healthy ?? null);
  const lastRunAt = last?.at;
  const fmtCount = (n, tone) => (
    <span className="serif text-xl num" style={{ color: tone }}>{n ?? 0}</span>
  );

  const copyOffenders = async (inv) => {
    const ids = (inv.offenders || []).map((o) =>
      o.id || o.order_id || o.payment_id || o.purchase_id || o.vendor_id || JSON.stringify(o)
    );
    try {
      await navigator.clipboard.writeText(ids.join("\n"));
      toast.success(`Copied ${ids.length} offender id(s).`);
    } catch (_) {
      toast.error("Clipboard blocked.");
    }
  };

  return (
    <div className="card-warm p-6 mb-6" data-testid="dm-reconcile-card">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-3">
          {healthy === true ? (
            <ShieldCheck size={22} style={{ color: "var(--sage)" }} />
          ) : healthy === false ? (
            <ShieldAlert size={22} style={{ color: "var(--danger)" }} />
          ) : (
            <ShieldCheck size={22} style={{ color: "var(--muted)" }} />
          )}
          <div>
            <div className="serif text-xl flex items-center gap-2">
              Reconciliation
              {healthy === true && (
                <span className="text-xs px-2 py-0.5 rounded-full"
                      style={{ background: "var(--sage-tint, #E7EFE6)", color: "var(--sage)" }}
                      data-testid="dm-reconcile-healthy-badge">
                  HEALTHY
                </span>
              )}
              {healthy === false && (
                <span className="text-xs px-2 py-0.5 rounded-full"
                      style={{ background: "var(--danger-tint, #F7E1DA)", color: "var(--danger)" }}
                      data-testid="dm-reconcile-unhealthy-badge">
                  ISSUES FOUND
                </span>
              )}
            </div>
            <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}
                 data-testid="dm-reconcile-last-run">
              {lastRunAt
                ? `Last run: ${new Date(lastRunAt).toLocaleString()}${report?.duration_ms ? ` · ${Math.round(report.duration_ms)}ms` : ""}`
                : "Never run in this session — click Run Reconciliation to check integrity."}
            </div>
          </div>
        </div>
        <Button variant="outline" onClick={onRun} disabled={busy}
                data-testid="dm-reconcile-run-btn"
                className="border-[var(--border-warm)]">
          {busy ? <Loader2 className="animate-spin" size={16} /> : <RefreshCcw size={16} />}
          <span className="ml-2">{busy ? "Running…" : "Run Reconciliation"}</span>
        </Button>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4"
             data-testid="dm-reconcile-counters">
          <div className="rounded-md p-3 border" style={{ borderColor: "var(--border-warm)" }}>
            <div className="label-caps">Total</div>
            {fmtCount(summary.total, "var(--ink)")}
          </div>
          <div className="rounded-md p-3 border" style={{ borderColor: "var(--border-warm)" }}>
            <div className="label-caps">Passed</div>
            {fmtCount(summary.passed, "var(--sage)")}
          </div>
          <div className="rounded-md p-3 border" style={{ borderColor: "var(--border-warm)" }}>
            <div className="label-caps">Failed</div>
            {fmtCount(summary.failed, summary.failed > 0 ? "var(--danger)" : "var(--muted)")}
          </div>
          <div className="rounded-md p-3 border" style={{ borderColor: "var(--border-warm)" }}>
            <div className="label-caps">Warnings</div>
            {fmtCount(summary.warnings, summary.warnings > 0 ? "var(--terracotta)" : "var(--muted)")}
          </div>
          <div className="rounded-md p-3 border" style={{ borderColor: "var(--border-warm)" }}>
            <div className="label-caps">Errors</div>
            {fmtCount(summary.errors, summary.errors > 0 ? "var(--danger)" : "var(--muted)")}
          </div>
        </div>
      )}

      {report?.warnings?.length > 0 && (
        <div className="text-xs mb-3 p-2.5 rounded"
             style={{ background: "var(--warn-tint, #FFF3E1)", color: "var(--terracotta)" }}
             data-testid="dm-reconcile-warnings">
          {report.warnings.map((w, i) => (
            <div key={i}><b>{w.code}:</b> {w.message}</div>
          ))}
        </div>
      )}

      {report?.invariants && (
        <div className="space-y-2" data-testid="dm-reconcile-invariants">
          {report.invariants
            .filter((inv) => inv.status !== "passed")
            .map((inv) => {
              const isOpen = expanded[inv.id];
              const color = inv.status === "failed" ? "var(--danger)"
                          : inv.status === "error" ? "var(--danger)"
                          : "var(--terracotta)";
              return (
                <div key={inv.id} className="rounded-md border"
                     style={{ borderColor: "var(--border-warm)" }}
                     data-testid={`dm-reconcile-inv-${inv.id}`}>
                  <button type="button"
                          className="w-full flex items-center gap-2 px-3 py-2 text-left"
                          onClick={() => onToggle(inv.id)}>
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <span className="text-xs font-medium" style={{ color }}>
                      {inv.status.toUpperCase()}
                    </span>
                    <span className="text-xs" style={{ color: "var(--muted)" }}>
                      {inv.phase} · {inv.id}
                    </span>
                    <span className="text-sm flex-1 truncate ml-2">{inv.description}</span>
                    {inv.offender_count > 0 && (
                      <span className="text-xs px-1.5 py-0.5 rounded"
                            style={{ background: "var(--surface-alt)" }}>
                        {inv.offender_count} offender{inv.offender_count === 1 ? "" : "s"}
                        {inv.truncated ? "+" : ""}
                      </span>
                    )}
                  </button>
                  {isOpen && (
                    <div className="px-3 pb-3 text-xs space-y-1"
                         style={{ color: "var(--muted)" }}>
                      <div><b>Expected:</b> {String(inv.expected)}</div>
                      <div><b>Actual:</b> {String(inv.actual)}</div>
                      <div><b>Difference:</b> {String(inv.difference)}</div>
                      <div><b>Tolerance:</b> {inv.tolerance} · <b>Checked:</b> {inv.checked_count} · <b>Took:</b> {inv.duration_ms}ms</div>
                      {inv.offenders?.length > 0 && (
                        <div>
                          <div className="flex items-center gap-2 mt-1">
                            <b>Offenders:</b>
                            <button type="button"
                                    className="text-xs px-2 py-0.5 border rounded flex items-center gap-1"
                                    style={{ borderColor: "var(--border-warm)" }}
                                    onClick={() => copyOffenders(inv)}
                                    data-testid={`dm-reconcile-copy-${inv.id}`}>
                              <Copy size={11} /> Copy ids
                            </button>
                            {inv.truncated && (
                              <span style={{ color: "var(--terracotta)" }}>
                                (truncated — showing 50 of {inv.offender_count})
                              </span>
                            )}
                          </div>
                          <pre className="mt-1 p-2 rounded text-[11px] overflow-x-auto max-h-48"
                               style={{ background: "var(--surface-alt)", color: "var(--ink)" }}>
                            {JSON.stringify(inv.offenders, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          {report.invariants.every((inv) => inv.status === "passed") && (
            <div className="text-xs p-3 rounded"
                 style={{ background: "var(--sage-tint, #E7EFE6)", color: "var(--sage)" }}
                 data-testid="dm-reconcile-all-green">
              All {report.summary.total} invariants passed — data is healthy.
            </div>
          )}
        </div>
      )}
    </div>
  );
}



export default function AdminDataManagement() {
  const { user, status } = useAuth();
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [scope, setScope] = useState("clear_transaction_data");
  const [wantExecute, setWantExecute] = useState(false);

  // Confirm dialog inputs
  const [pw, setPw] = useState("");
  const [phrase, setPhrase] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [countdown, setCountdown] = useState(5);
  const [createBackup, setCreateBackup] = useState(true);
  const [keepAccounts, setKeepAccounts] = useState(true);
  const [busy, setBusy] = useState(false);

  // Backup history + audit log
  const [backups, setBackups] = useState([]);
  const [audit, setAudit] = useState([]);
  const [ds, setDs] = useState(null);           // most recent test dataset id

  // Phase 5 — reconciliation
  const [reconcile, setReconcile] = useState(null);        // full report
  const [reconcileLast, setReconcileLast] = useState(null); // last audit summary
  const [reconcileBusy, setReconcileBusy] = useState(false);
  const [expandedInvariants, setExpandedInvariants] = useState({});

  const reloadHistory = async () => {
    try {
      const [b, a, last] = await Promise.all([
        api.get("/admin/backups"),
        api.get("/admin/audit-logs?limit=50"),
        api.get("/admin/reconcile/last").catch(() => ({ data: null })),
      ]);
      setBackups(b.data || []);
      setAudit(a.data || []);
      setReconcileLast(last?.data || null);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load history.");
    }
  };

  const runReconcile = async () => {
    setReconcileBusy(true);
    try {
      const r = await api.post("/reconcile/run");
      setReconcile(r.data);
      setExpandedInvariants({});
      // Refresh the audit-log summary card too.
      const last = await api.get("/admin/reconcile/last").catch(() => ({ data: null }));
      setReconcileLast(last?.data || null);
      if (r.data.audit_warning) toast.warning(r.data.audit_warning);
      else toast.success(r.data.healthy
        ? `Reconciliation passed — ${r.data.summary.passed}/${r.data.summary.total} invariants.`
        : `Reconciliation found issues — ${r.data.summary.failed} failed, ${r.data.summary.errors} errored.`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reconciliation failed to run.");
    } finally {
      setReconcileBusy(false);
    }
  };

  useEffect(() => { reloadHistory(); }, []);

  // Countdown timer
  useEffect(() => {
    if (!previewOpen || !wantExecute) return;
    setCountdown(5);
    const iv = setInterval(() => {
      setCountdown((c) => (c > 0 ? c - 1 : 0));
    }, 1000);
    return () => clearInterval(iv);
  }, [previewOpen, wantExecute, scope]);

  const openPreview = async (scopeName, executeNext = false) => {
    setScope(scopeName);
    setWantExecute(executeNext);
    setPw(""); setPhrase(""); setUnderstood(false); setCountdown(5);
    try {
      const r = await api.post("/admin/data-reset/preview", { scope: scopeName, keep_accounts: keepAccounts });
      setPreviewData(r.data);
      setPreviewOpen(true);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load preview.");
    }
  };

  const canExecute = useMemo(() => {
    if (!wantExecute) return false;
    if (!pw) return false;
    if ((phrase || "").trim() !== (previewData?.required_phrase || PHRASE[scope])) return false;
    if (!understood) return false;
    if (countdown > 0) return false;
    if (!previewData?.reset_enabled) return false;
    return true;
  }, [wantExecute, pw, phrase, previewData, scope, understood, countdown]);

  const execute = async () => {
    setBusy(true);
    try {
      const r = await api.post("/admin/data-reset/execute", {
        scope,
        password: pw,
        confirmation_phrase: phrase,
        understand_checkbox: understood,
        keep_accounts: keepAccounts,
        create_backup_first: createBackup,
      });
      toast.success(`${LABEL[scope]} complete.`);
      setPreviewOpen(false);
      await reloadHistory();
      // Refresh preview counts (should now be zero-ish)
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Reset failed.");
    } finally {
      setBusy(false);
    }
  };

  const createBackupNow = async () => {
    try {
      const r = await api.post("/admin/backups", { note: "Manual backup" });
      toast.success(`Backup ${r.data.id.slice(0, 8)} created.`);
      await reloadHistory();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Backup failed.");
    }
  };

  const downloadBackup = (bid) => {
    const url = `${api.defaults.baseURL}/admin/backups/${bid}/download`;
    window.open(url, "_blank");
  };

  const deleteBackup = async (bid) => {
    if (!confirm("Delete this backup file permanently?")) return;
    try {
      await api.delete(`/admin/backups/${bid}`);
      await reloadHistory();
      toast.success("Backup deleted.");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed.");
    }
  };

  const loadTestData = async () => {
    try {
      const r = await api.post("/admin/test-dataset/load", {});
      setDs(r.data.test_dataset_id);
      toast.success(`Loaded test dataset ${r.data.test_dataset_id.slice(0, 6)}`);
      await reloadHistory();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load test data.");
    }
  };

  const removeTestData = async () => {
    if (!ds) { toast.info("No test dataset id to remove."); return; }
    try {
      const r = await api.delete(`/admin/test-dataset/${ds}`);
      toast.success(`Removed ${Object.values(r.data.deleted_counts).reduce((a, b) => a + b, 0)} test rows.`);
      setDs(null);
      await reloadHistory();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed.");
    }
  };

  return (
    <div data-testid="data-management-page">
      <PageHeader
        eyebrow="Settings · Admin Controls"
        title="Data Management — Danger Zone"
        subtitle="Reset transactional data, back up before destructive actions and load test datasets."
      />

      {/* Environment banner */}
      <div className="card-warm p-4 mb-6 flex items-center gap-3"
           style={{ background: "var(--surface-alt)" }}
           data-testid="dm-env-banner">
        <AlertTriangle size={18} style={{ color: "var(--terracotta)" }} />
        <div className="text-xs">
          Environment: <b>{status.environment}</b>
          {" · "}
          Reset endpoints: <b style={{ color: status.reset_enabled ? "var(--sage)" : "var(--danger)" }}>
            {status.reset_enabled ? "ENABLED" : "DISABLED"}
          </b>
          {!status.reset_enabled && (
            <> · Set <code>ALLOW_ADMIN_DATA_RESET="true"</code> in <code>backend/.env</code> and restart backend to enable.</>
          )}
        </div>
      </div>

      {/* Phase 5 — Reconciliation card */}
      <ReconciliationCard
        report={reconcile}
        last={reconcileLast}
        busy={reconcileBusy}
        onRun={runReconcile}
        expanded={expandedInvariants}
        onToggle={(id) => setExpandedInvariants((m) => ({ ...m, [id]: !m[id] }))}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <ScopeCard scope="clear_transaction_data" onPreview={openPreview} />
        <ScopeCard scope="full_reset" danger onPreview={openPreview} />
      </div>

      {/* Backups + test dataset + audit */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <div className="card-warm p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="serif text-lg flex items-center gap-2"><History size={16} /> Backup History</div>
            <Button variant="outline" size="sm"
                    data-testid="dm-create-backup-btn"
                    onClick={createBackupNow}
                    className="border-[var(--border-warm)]">
              Create backup
            </Button>
          </div>
          <div data-testid="dm-backup-list" className="space-y-2 max-h-72 overflow-y-auto">
            {backups.length === 0 && (
              <div className="text-xs" style={{ color: "var(--muted)" }}>No backups yet.</div>
            )}
            {backups.map((b) => (
              <div key={b.id} className="flex items-center justify-between text-xs py-1.5 border-b"
                   style={{ borderColor: "var(--border-warm)" }}>
                <div className="min-w-0">
                  <div className="font-medium truncate">{b.filename || b.id.slice(0, 8)}</div>
                  <div style={{ color: "var(--muted)" }}>
                    {new Date(b.created_at).toLocaleString()} · {Math.round((b.size_bytes || 0) / 1024)} KB · {Object.values(b.record_counts || {}).reduce((a, b) => a + b, 0)} rows
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => downloadBackup(b.id)}
                          data-testid={`dm-download-backup-${b.id}`}
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                    <Download size={14} />
                  </button>
                  <button onClick={() => deleteBackup(b.id)}
                          data-testid={`dm-del-backup-${b.id}`}
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                    <Trash2 size={14} style={{ color: "var(--danger)" }} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card-warm p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="serif text-lg flex items-center gap-2"><FlaskConical size={16} /> Test Dataset</div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm"
                      data-testid="dm-load-testdata-btn"
                      onClick={loadTestData}
                      className="border-[var(--border-warm)]">
                Load test dataset
              </Button>
              <Button variant="outline" size="sm"
                      data-testid="dm-remove-testdata-btn"
                      onClick={removeTestData}
                      disabled={!ds}
                      className="border-[var(--border-warm)]">
                Remove
              </Button>
            </div>
          </div>
          <div className="text-xs" style={{ color: "var(--muted)" }}>
            Seeds a labelled dataset (factory purchase, outside vendor, customer advance, partial shipment, Rakshit→FF transfer). All rows carry <code>is_test_data=true</code> + a shared <code>test_dataset_id</code>.
          </div>
          {ds && (
            <div className="mt-3 text-xs">
              <span className="label-caps">Last dataset id:</span> <code data-testid="dm-testdata-id">{ds}</code>
            </div>
          )}
        </div>
      </div>

      <div className="card-warm p-5 mb-8" data-testid="dm-audit-log-panel">
        <div className="serif text-lg mb-3">Audit log</div>
        <div className="max-h-72 overflow-y-auto text-xs">
          {audit.length === 0 && (
            <div style={{ color: "var(--muted)" }}>No admin actions recorded yet.</div>
          )}
          {audit.map((a) => (
            <div key={a.id} className="py-1.5 border-b flex justify-between"
                 style={{ borderColor: "var(--border-warm)" }}>
              <div className="min-w-0">
                <span className="font-medium">{a.kind}</span>
                <span style={{ color: "var(--muted)" }}> — {a.admin_email}</span>
                {a.scope && <span style={{ color: "var(--muted)" }}> — {a.scope}</span>}
                {a.error && <span style={{ color: "var(--danger)" }}> — {a.error}</span>}
              </div>
              <div style={{ color: "var(--muted)" }}>{new Date(a.at || a.started_at).toLocaleString()}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Preview + Confirm dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="dm-confirm-dialog">
          <DialogHeader>
            <DialogTitle className="serif text-2xl"
                         style={scope === "full_reset" ? { color: "var(--danger)" } : {}}>
              {wantExecute ? "Confirm — " : "Preview — "}{LABEL[scope]}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {scope === "full_reset"
                ? "This will WIPE nearly every collection. This cannot be undone without a backup."
                : "This will remove operational transactions. Setup data is preserved."}
            </DialogDescription>
          </DialogHeader>

          {previewData && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md p-3" style={{ background: "var(--surface-alt)" }}>
                  <div className="label-caps text-xs">Will be deleted</div>
                  <div className="max-h-40 overflow-y-auto mt-1 text-xs" data-testid="dm-deleted-counts">
                    {Object.entries(previewData.deleted_counts).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span>{k}</span>
                        <span className="num" style={{ color: v > 0 ? "var(--danger)" : "var(--muted)" }}>{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="rounded-md p-3" style={{ background: "var(--surface-alt)" }}>
                  <div className="label-caps text-xs">Will be preserved</div>
                  <div className="max-h-40 overflow-y-auto mt-1 text-xs" data-testid="dm-preserved-counts">
                    {Object.entries(previewData.preserved_counts).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span>{k}</span>
                        <span className="num" style={{ color: "var(--sage)" }}>{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {(previewData.warnings || []).length > 0 && (
                <div className="rounded-md p-3 text-xs"
                     style={{ background: "#FBEEEA", color: "#C55B43" }}>
                  {previewData.warnings.map((w, i) => <div key={i}>• {w}</div>)}
                </div>
              )}

              {wantExecute && (
                <div className="space-y-3 pt-3 border-t" style={{ borderColor: "var(--border-warm)" }}>
                  <div className="flex items-center gap-4 text-xs">
                    <label className="flex items-center gap-1.5" data-testid="dm-create-backup-toggle">
                      <input type="checkbox" checked={createBackup}
                             onChange={(e) => setCreateBackup(e.target.checked)} />
                      Create backup before reset
                    </label>
                    {scope === "clear_transaction_data" && (
                      <label className="flex items-center gap-1.5" data-testid="dm-keep-accounts-toggle">
                        <input type="checkbox" checked={keepAccounts}
                               onChange={(e) => setKeepAccounts(e.target.checked)} />
                        Keep accounts
                      </label>
                    )}
                  </div>

                  <div>
                    <Label className="label-caps text-xs">Confirm admin password</Label>
                    <Input type="password" value={pw} onChange={(e) => setPw(e.target.value)}
                           data-testid="dm-confirm-password-input"
                           className="mt-1.5 bg-white border-[var(--border-warm)]" />
                  </div>
                  <div>
                    <Label className="label-caps text-xs">
                      Type <code style={{ color: "var(--danger)" }}>{previewData.required_phrase}</code> to confirm
                    </Label>
                    <Input value={phrase} onChange={(e) => setPhrase(e.target.value)}
                           data-testid="dm-confirm-phrase-input"
                           className="mt-1.5 bg-white border-[var(--border-warm)] font-mono" />
                  </div>
                  <label className="flex items-start gap-2 text-xs" data-testid="dm-understand-label">
                    <input type="checkbox" checked={understood}
                           data-testid="dm-understand-checkbox"
                           onChange={(e) => setUnderstood(e.target.checked)} />
                    <span>
                      I understand that this action cannot be undone without a backup.
                    </span>
                  </label>
                  {!previewData.reset_enabled && (
                    <div className="rounded-md p-3 text-xs"
                         style={{ background: "#FBEEEA", color: "#C55B43" }}>
                      Reset is disabled by server configuration. Set <code>ALLOW_ADMIN_DATA_RESET="true"</code> and restart the backend to enable.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <DialogFooter className="mt-4">
            <Button variant="outline" onClick={() => setPreviewOpen(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            {wantExecute && (
              <Button onClick={execute} disabled={!canExecute || busy}
                      data-testid="dm-final-execute-btn"
                      style={{ background: "var(--danger)", color: "white" }}>
                {busy ? <><Loader2 size={14} className="animate-spin mr-1" /> Working…</>
                      : countdown > 0 ? `Wait ${countdown}s…`
                      : `Execute ${LABEL[scope]}`}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
