import { useEffect, useState, useMemo } from "react";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../components/ui/select";
import {
  Search, ArrowLeft, User, Building2, ShoppingBag, Landmark, UserRound,
  Plus, ArrowUpRight, ArrowDownLeft, MinusCircle, PlusCircle, RotateCcw, Download,
} from "lucide-react";
import QuickEntryDialog from "../components/QuickEntryDialog";
import PartyOpeningDialog from "../components/PartyOpeningDialog";
import { toast } from "sonner";

const TYPE_META = {
  self:         { icon: UserRound, label: "Rakshit",       color: "var(--muted)" },
  fathers_firm: { icon: Landmark,  label: "Father's Firm", color: "var(--terracotta)" },
  vendor:       { icon: ShoppingBag, label: "Vendor",      color: "var(--ochre-strong, #8a5a2c)" },
  customer:     { icon: User,      label: "Customer",      color: "var(--sage)" },
  other:        { icon: Building2, label: "Other",         color: "var(--muted)" },
};

const STATUS_STYLE = {
  "You Pay":     { bg: "rgba(188,71,73,0.12)",  fg: "var(--danger)",     label: "You Pay" },
  "You Receive": { bg: "rgba(58,90,64,0.12)",   fg: "var(--sage)",       label: "You Receive" },
  "Settled":     { bg: "rgba(122,117,113,0.15)", fg: "var(--muted)",     label: "Settled" },
};

function StatusPill({ status, amount, size = "md" }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.Settled;
  const pad = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${pad}`}
      style={{ background: s.bg, color: s.fg }}
      data-testid="party-status-pill"
    >
      {status === "You Pay" && <ArrowUpRight size={12} strokeWidth={2} />}
      {status === "You Receive" && <ArrowDownLeft size={12} strokeWidth={2} />}
      {status}
      {status !== "Settled" && <span className="num">{fmtINR(Math.abs(amount || 0))}</span>}
    </span>
  );
}

// ---------- List view -----------------------------------------------
function PartyListView({ onOpen, onNewParty, onQuickEntry }) {
  const [parties, setParties] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [type, setType] = useState("all");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");   // all / you_pay / you_receive / settled
  const [exportMenuOpen, setExportMenuOpen] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      api.get("/party-ledger-v2/parties", { params: { include_settled: true } }),
      api.get("/party-ledger-v2/summary"),
    ])
      .then(([r1, r2]) => {
        setParties(r1.data.parties || []);
        setSummary(r2.data || {});
      })
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const rows = useMemo(() => {
    let list = parties;
    if (type !== "all") list = list.filter((p) => p.type === type);
    if (status !== "all") {
      list = list.filter((p) => {
        if (status === "you_pay") return p.status === "You Pay";
        if (status === "you_receive") return p.status === "You Receive";
        return p.status === "Settled";
      });
    }
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((p) => (p.name || "").toLowerCase().includes(q));
    }
    return list;
  }, [parties, type, status, search]);

  return (
    <div>
      <PageHeader
        eyebrow="Accounting"
        title="Party Ledger"
        subtitle="Every counterparty in one place — vendors, customers, Father's Firm. Balances shown as You Pay, You Receive or Settled."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => setExportMenuOpen((v) => !v)}
              data-testid="pl-export-btn"
              className="border-[var(--border-warm)] gap-1.5 relative"
            >
              <Download size={14} /> Export
            </Button>
            {exportMenuOpen && (
              <div className="absolute right-6 mt-40 z-40 rounded-md shadow-lg border bg-white p-2 min-w-[240px]"
                   style={{ borderColor: "var(--border-warm)" }}
                   data-testid="pl-export-menu"
                   onMouseLeave={() => setExportMenuOpen(false)}>
                {[
                  { label: "Summary CSV",                path: "/api/party-ledger-v2/exports/summary.csv" },
                  { label: "All vendor balances CSV",    path: "/api/party-ledger-v2/exports/vendors.csv" },
                  { label: "All customer balances CSV",  path: "/api/party-ledger-v2/exports/customers.csv" },
                  { label: "Father's Firm ledger CSV",   path: "/api/party-ledger-v2/exports/fathers-firm.csv" },
                ].map((it) => (
                  <a key={it.path}
                     href={`${process.env.REACT_APP_BACKEND_URL || ""}${it.path}`}
                     className="block px-3 py-2 text-sm rounded hover:bg-[var(--surface-alt)]"
                     data-testid={`pl-export-${it.label.toLowerCase().replace(/[^a-z]+/g, '-')}`}
                     onClick={() => setExportMenuOpen(false)}>
                    {it.label}
                  </a>
                ))}
              </div>
            )}
            <Button
              variant="outline"
              onClick={onNewParty}
              data-testid="pl-new-party"
              className="border-[var(--border-warm)] gap-1.5"
            >
              <Plus size={14} /> New party
            </Button>
            <Button
              onClick={() => onQuickEntry(null)}
              data-testid="pl-quick-entry"
              className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5"
            >
              <PlusCircle size={14} /> Quick entry
            </Button>
          </div>
        }
      />

      {/* SUMMARY CARDS */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6" data-testid="pl-summary">
        <SumCard label="You Pay Father's Firm"
                 value={summary.fathers_firm_you_pay}
                 tone="danger"
                 onClick={() => setType("fathers_firm") + setStatus("you_pay")} />
        <SumCard label="You Receive from Father's Firm"
                 value={summary.fathers_firm_you_receive}
                 tone="sage"
                 onClick={() => { setType("fathers_firm"); setStatus("you_receive"); }} />
        <SumCard label="Total vendor payables"
                 value={summary.vendor_you_pay}
                 tone="danger"
                 onClick={() => { setType("vendor"); setStatus("you_pay"); }} />
        <SumCard label="Vendor advances (with them)"
                 value={summary.vendor_advances_you_receive}
                 tone="sage"
                 onClick={() => { setType("vendor"); setStatus("you_receive"); }} />
        <SumCard label="Customer receivables"
                 value={summary.customer_you_receive}
                 tone="sage"
                 onClick={() => { setType("customer"); setStatus("you_receive"); }} />
        <SumCard label="Net settlement position"
                 value={Math.abs(summary.net_position || 0)}
                 tone={(summary.net_position || 0) >= 0 ? "danger" : "sage"}
                 sub={(summary.net_position || 0) >= 0 ? "You Pay overall" : "You Receive overall"} />
      </div>

      {/* FILTERS */}
      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search party name…"
            data-testid="pl-search"
            className="pl-9 bg-white border-[var(--border-warm)]"
          />
        </div>
        <Select value={type} onValueChange={setType}>
          <SelectTrigger data-testid="pl-type" className="bg-white border-[var(--border-warm)]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All party types</SelectItem>
            <SelectItem value="fathers_firm">Father's Firm</SelectItem>
            <SelectItem value="vendor">Vendors</SelectItem>
            <SelectItem value="customer">Customers</SelectItem>
            <SelectItem value="other">Others</SelectItem>
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger data-testid="pl-status" className="bg-white border-[var(--border-warm)]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All balances</SelectItem>
            <SelectItem value="you_pay">You Pay</SelectItem>
            <SelectItem value="you_receive">You Receive</SelectItem>
            <SelectItem value="settled">Settled</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          onClick={load}
          className="border-[var(--border-warm)] gap-1.5"
          data-testid="pl-refresh"
        >
          <RotateCcw size={13} /> Refresh
        </Button>
      </div>

      {/* PARTY TABLE */}
      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto max-h-[65vh]">
          <table className="ledger-table w-full min-w-[900px]" data-testid="pl-table">
            <thead>
              <tr>
                <th>Party</th>
                <th>Type</th>
                <th>Last activity</th>
                <th className="num">Entries</th>
                <th>Status</th>
                <th className="num">Amount</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="7" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan="7" className="text-center py-12 text-sm" style={{ color: "var(--muted)" }}>
                    No parties match these filters.
                  </td>
                </tr>
              )}
              {rows.map((p) => {
                const meta = TYPE_META[p.type] || TYPE_META.other;
                const Icon = meta.icon;
                return (
                  <tr
                    key={p.id}
                    className="cursor-pointer"
                    onClick={() => onOpen(p)}
                    data-testid={`pl-row-${p.id}`}
                  >
                    <td>
                      <div className="flex items-center gap-2.5">
                        <span
                          className="w-8 h-8 rounded-full flex items-center justify-center"
                          style={{ background: "var(--surface-alt)", color: meta.color }}
                        >
                          <Icon size={14} strokeWidth={1.75} />
                        </span>
                        <div>
                          <div className="font-medium">{p.name}</div>
                          {p.is_system && (
                            <div className="text-[10px] uppercase tracking-wider" style={{ color: "var(--muted)" }}>
                              System
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="text-xs" style={{ color: "var(--muted)" }}>{meta.label}</td>
                    <td className="text-xs" style={{ color: "var(--muted)" }}>{fmtDate(p.last_activity)}</td>
                    <td className="num text-xs" style={{ color: "var(--muted)" }}>{p.entries_count}</td>
                    <td><StatusPill status={p.status} amount={p.net_balance} size="sm" /></td>
                    <td className="num font-medium"
                        style={{ color: p.status === "You Pay" ? "var(--danger)"
                                        : p.status === "You Receive" ? "var(--sage)"
                                        : "var(--muted)" }}>
                      {p.status === "Settled" ? "—" : fmtINR(Math.abs(p.net_balance))}
                    </td>
                    <td className="text-right">
                      <button
                        onClick={(e) => { e.stopPropagation(); onQuickEntry(p); }}
                        data-testid={`pl-quick-for-${p.id}`}
                        title="Quick entry for this party"
                        className="p-1.5 rounded hover:bg-[var(--surface-alt)]"
                      >
                        <PlusCircle size={14} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function SumCard({ label, value, tone = "muted", sub, onClick }) {
  const color = tone === "danger" ? "var(--danger)" : tone === "sage" ? "var(--sage)" : "var(--ink)";
  return (
    <button
      type="button"
      onClick={onClick}
      className="card-warm px-4 py-3 text-left hover:shadow-md transition-shadow"
    >
      <div className="label-caps text-[10px] leading-tight" style={{ color: "var(--muted)" }}>{label}</div>
      <div className="serif text-2xl num mt-1.5" style={{ color }}>{fmtINR(value || 0)}</div>
      {sub && <div className="text-[10px] mt-0.5" style={{ color: "var(--muted)" }}>{sub}</div>}
    </button>
  );
}

// ---------- Detail view -----------------------------------------------
function PartyDetailView({ partyId, onBack, onQuickEntry, onEditOpening }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showReversed, setShowReversed] = useState(false);

  const load = () => {
    setLoading(true);
    api.get(`/party-ledger-v2/parties/${partyId}`, {
      params: { include_reversed: showReversed },
    }).then((r) => setData(r.data)).finally(() => setLoading(false));
  };
  useEffect(load, [partyId, showReversed]);

  const doReverse = async (txnRef) => {
    if (!confirm("Reverse this transaction? An offsetting entry will be added to the audit trail.")) return;
    try {
      await api.delete(`/party-ledger-v2/transactions/${txnRef}`);
      toast.success("Transaction reversed");
      load();
    } catch {
      toast.error("Could not reverse transaction");
    }
  };

  if (loading || !data) return (
    <div className="text-center py-16 text-sm" style={{ color: "var(--muted)" }}>Loading party ledger…</div>
  );

  const meta = TYPE_META[data.party.type] || TYPE_META.other;
  const Icon = meta.icon;
  const entries = data.entries || [];
  // aggregate totals for the summary strip
  const totals = entries.reduce((a, e) => {
    if (!e.counts_in_balance) return a;
    const c = e.category;
    if (c === "sale_invoice") a.invoiced += e.amount;
    else if (c === "customer_payment") a.received += e.amount;
    else if (c === "purchase" || c === "packing") a.purchased += e.amount;
    else if (c === "vendor_payment") a.paid += e.amount;
    else if (c === "advance") a.advances += e.amount;
    else a.adjustments += Math.abs(e.delta_you_pay);
    return a;
  }, { invoiced: 0, received: 0, purchased: 0, paid: 0, advances: 0, adjustments: 0 });

  return (
    <div>
      <button
        onClick={onBack}
        data-testid="party-detail-back"
        className="mb-4 inline-flex items-center gap-2 text-sm hover:underline"
        style={{ color: "var(--muted)" }}
      >
        <ArrowLeft size={14} /> Back to party list
      </button>

      <div className="card-warm p-6 mb-6" data-testid="party-detail-card">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-4">
            <span
              className="w-14 h-14 rounded-full flex items-center justify-center"
              style={{ background: "var(--surface-alt)", color: meta.color }}
            >
              <Icon size={22} strokeWidth={1.5} />
            </span>
            <div>
              <div className="label-caps">{meta.label}</div>
              <h1 className="serif text-3xl sm:text-4xl leading-tight">{data.party.name}</h1>
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <StatusPill status={data.status} amount={data.net_balance} />
                <span className="text-xs" style={{ color: "var(--muted)" }}>
                  · {entries.length} {entries.length === 1 ? "entry" : "entries"}
                </span>
                {data.party.opening_balance ? (
                  <span className="text-xs" style={{ color: "var(--muted)" }}>
                    · Opening {fmtINR(Math.abs(data.party.opening_balance))} {data.party.opening_balance > 0 ? "(you owed)" : "(they owed)"}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <a
              href={`${process.env.REACT_APP_BACKEND_URL || ""}/api/party-ledger-v2/parties/${data.party.id}/ledger.csv`}
              data-testid="party-export-csv"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm hover:bg-[var(--surface-alt)]"
              style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}
            >
              <Download size={13} /> Export CSV
            </a>
            <Button
              variant="outline"
              onClick={() => onEditOpening(data.party)}
              data-testid="party-edit-opening"
              className="border-[var(--border-warm)] gap-1.5"
            >
              Edit opening
            </Button>
            <Button
              onClick={() => onQuickEntry(data.party)}
              data-testid="party-quick-entry"
              className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5"
            >
              <PlusCircle size={14} /> Quick entry
            </Button>
          </div>
        </div>

        {/* Aggregate strip */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 mt-6">
          <MiniStat label="Purchases / Invoices" value={data.party.type === "customer" ? totals.invoiced : totals.purchased} />
          <MiniStat label="Payments" value={data.party.type === "customer" ? totals.received : totals.paid} tone="sage" />
          <MiniStat label="Advances" value={totals.advances} tone="ochre" />
          <MiniStat label="Adjustments" value={totals.adjustments} />
          <MiniStat label="You Pay side" value={data.you_pay} tone="danger" />
          <MiniStat label="You Receive side" value={data.you_receive} tone="sage" />
        </div>
      </div>

      {/* CHRONOLOGICAL LEDGER */}
      <div className="card-warm overflow-hidden">
        <div className="px-5 py-3 border-b flex items-center justify-between"
             style={{ borderColor: "var(--border-warm)" }}>
          <div className="label-caps">Chronological ledger</div>
          <label className="flex items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
            <input type="checkbox" checked={showReversed}
                   data-testid="party-show-reversed"
                   onChange={(e) => setShowReversed(e.target.checked)} />
            Show reversed / audit
          </label>
        </div>
        <div className="overflow-x-auto max-h-[65vh]">
          <table className="ledger-table w-full min-w-[900px]" data-testid="party-ledger-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Category</th>
                <th>Description</th>
                <th className="num">Amount</th>
                <th>Effect</th>
                <th className="num">Running balance</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.length === 0 && (
                <tr>
                  <td colSpan="7" className="text-center py-12 text-sm" style={{ color: "var(--muted)" }}>
                    No entries yet. Use <b>Quick entry</b> to record a transaction.
                  </td>
                </tr>
              )}
              {entries.map((e) => {
                const impact = e.delta_you_pay || 0;
                const isReversal = e.origin === "reversal";
                const isReversed = !!e.reversed_at;
                return (
                  <tr key={e.id} className={isReversal || isReversed ? "opacity-60" : ""}
                      data-testid={`ledger-row-${e.id}`}>
                    <td className="whitespace-nowrap">{fmtDate(e.date)}</td>
                    <td className="text-xs">
                      <span className="inline-block px-2 py-0.5 rounded-full"
                            style={{ background: "var(--surface-alt)", color: "var(--muted)" }}>
                        {e.category_label}
                      </span>
                      {isReversal && (
                        <span className="ml-1 text-[10px]" style={{ color: "var(--danger)" }}>REV</span>
                      )}
                    </td>
                    <td className="max-w-[280px]">
                      <div className="text-sm truncate">{e.notes || e.description || "—"}</div>
                      {e.account_name && (
                        <div className="text-[10px]" style={{ color: "var(--muted)" }}>{e.account_name}</div>
                      )}
                    </td>
                    <td className="num text-xs" style={{ color: "var(--muted)" }}>{fmtINR(e.amount)}</td>
                    <td className="text-xs">
                      {impact > 0 ? (
                        <span style={{ color: "var(--danger)" }}>You Pay +{fmtINR(impact)}</span>
                      ) : impact < 0 ? (
                        <span style={{ color: "var(--sage)" }}>You Receive +{fmtINR(-impact)}</span>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>—</span>
                      )}
                    </td>
                    <td className="num font-medium"
                        style={{ color: e.running_balance > 0 ? "var(--danger)"
                                        : e.running_balance < 0 ? "var(--sage)"
                                        : "var(--muted)" }}>
                      {e.running_status === "Settled" ? "Settled" :
                        <>
                          <span className="text-[10px] mr-1" style={{ color: "var(--muted)" }}>
                            {e.running_status}
                          </span>
                          {fmtINR(Math.abs(e.running_balance))}
                        </>}
                    </td>
                    <td className="text-right">
                      {e.origin === "manual" && !isReversed && (
                        <button
                          onClick={() => doReverse(e.txn_ref)}
                          data-testid={`reverse-${e.id}`}
                          title="Reverse (creates audit entry)"
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)]"
                        >
                          <MinusCircle size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value, tone = "muted" }) {
  const color = tone === "danger" ? "var(--danger)"
              : tone === "sage" ? "var(--sage)"
              : tone === "ochre" ? "#8a5a2c"
              : "var(--ink)";
  return (
    <div>
      <div className="label-caps text-[10px]" style={{ color: "var(--muted)" }}>{label}</div>
      <div className="serif text-lg num mt-0.5" style={{ color }}>{fmtINR(value || 0)}</div>
    </div>
  );
}

// ---------- Page shell ------------------------------------------------
export default function PartyLedger() {
  const [selected, setSelected] = useState(null);   // party object
  const [quickEntryFor, setQuickEntryFor] = useState(null); // { party } or true
  const [openingFor, setOpeningFor] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  const handleQuickEntrySaved = () => {
    setQuickEntryFor(null);
    setReloadKey((k) => k + 1);
  };

  return (
    <div key={reloadKey}>
      {selected
        ? <PartyDetailView
            partyId={selected.id}
            onBack={() => setSelected(null)}
            onQuickEntry={(p) => setQuickEntryFor({ party: p })}
            onEditOpening={(p) => setOpeningFor(p)}
          />
        : <PartyListView
            onOpen={setSelected}
            onNewParty={() => setOpeningFor({})}
            onQuickEntry={(p) => setQuickEntryFor({ party: p })}
          />}

      <QuickEntryDialog
        open={!!quickEntryFor}
        onOpenChange={(v) => !v && setQuickEntryFor(null)}
        prefilledParty={quickEntryFor?.party}
        onSaved={handleQuickEntrySaved}
      />

      <PartyOpeningDialog
        open={!!openingFor}
        onOpenChange={(v) => !v && setOpeningFor(null)}
        party={openingFor}
        onSaved={() => { setOpeningFor(null); setReloadKey((k) => k + 1); }}
      />
    </div>
  );
}
