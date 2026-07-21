import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "../components/ui/dropdown-menu";
import {
  Plus, Search, ArrowUpRight, ArrowDownRight, ArrowLeftRight,
  ExternalLink, Pencil, Trash2, ChevronDown,
} from "lucide-react";
import CashBookEntryDialog from "../components/CashBookEntryDialog";
import { toast } from "sonner";

const SOURCE_TAG_STYLE = {
  "Sales Payments":            { bg: "#EDF3ED", fg: "#3A5A40" },  // sage
  "Purchase Payments":         { bg: "#FBEEEA", fg: "#C55B43" },  // terracotta
  "Cash Book":                 { bg: "#F5F3EC", fg: "#7A7571" },  // stone
  "Cash Book (Legacy Shim)":   { bg: "#F5F3EC", fg: "#7A7571" },
  "Migration":                 { bg: "#F5F3EC", fg: "#A99885" },
  "Transfer":                  { bg: "#EEF2F5", fg: "#5B7180" },
};

function SourceTag({ label }) {
  const s = SOURCE_TAG_STYLE[label] || SOURCE_TAG_STYLE["Cash Book"];
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[11px] tracking-wide"
          style={{ background: s.bg, color: s.fg }}>
      {label}
    </span>
  );
}

function KindIcon({ kind }) {
  const size = 14;
  const s = 1.75;
  if (kind === "customer_payment" || kind === "general_income")
    return <ArrowDownRight size={size} strokeWidth={s} style={{ color: "var(--sage)" }} />;
  if (kind === "vendor_payment" || kind === "general_expense")
    return <ArrowUpRight size={size} strokeWidth={s} style={{ color: "var(--terracotta)" }} />;
  if (kind === "transfer")
    return <ArrowLeftRight size={size} strokeWidth={s} style={{ color: "#5B7180" }} />;
  return <ArrowDownRight size={size} strokeWidth={s} style={{ color: "var(--muted)" }} />;
}

export default function Payments() {
  const nav = useNavigate();

  const [rows, setRows] = useState([]);
  const [count, setCount] = useState(0);
  const [totals, setTotals] = useState({ total_received: 0, total_paid: 0, net: 0 });
  const [loading, setLoading] = useState(true);

  const [source, setSource] = useState("all");
  const [kind, setKind] = useState("all");
  const [party, setParty] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [includeMigration, setIncludeMigration] = useState(true);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogKind, setDialogKind] = useState("general_expense");
  const [editing, setEditing] = useState(null);

  const load = () => {
    setLoading(true);
    const params = { limit: 500, include_migration: includeMigration };
    if (source !== "all") params.source_module = source;
    if (kind !== "all") params.kind = kind;
    if (party) params.party = party;
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    api.get("/cash-book", { params })
      .then((r) => {
        setRows(r.data.rows || []);
        setCount(r.data.count || 0);
        setTotals({
          total_received: r.data.total_received || 0,
          total_paid: r.data.total_paid || 0,
          net: r.data.net || 0,
        });
      })
      .catch((e) => { console.error(e); toast.error("Failed to load Cash Book"); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [source, kind, includeMigration, startDate, endDate]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [party]);

  const openNew = (k) => { setEditing(null); setDialogKind(k); setDialogOpen(true); };

  const openSource = (row) => {
    if (!row?.source_document) return;
    const doc = row.source_document;
    // Every canonical module knows how to open its own record — Cash Book only
    // navigates. It never edits customer/vendor payments in place.
    if (doc.collection === "customer_payments") {
      nav(`/sales-payments?open=${doc.id}`);
    } else if (doc.collection === "purchase_payments") {
      nav(`/purchase-payments?open=${doc.id}`);
    } else if (doc.collection === "cash_book_entries") {
      if (row.editable) {
        setEditing(row);
        setDialogKind(row.kind);
        setDialogOpen(true);
      } else {
        toast.info("Legacy entry — read-only.");
      }
    } else if (doc.collection === "orders") {
      nav(`/orders?open=${doc.id}`);
    } else if (doc.collection === "payments") {
      toast.info("Legacy migration row — read-only historic entry.");
    }
  };

  const removeEntry = async (row) => {
    if (!row.editable) return;
    if (!confirm("Delete this Cash Book entry?")) return;
    try {
      await api.delete(`/cash-book-entries/${row.event_id}`);
      toast.success("Entry deleted");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to delete");
    }
  };

  const grouped = useMemo(() => {
    const g = new Map();
    for (const r of rows) {
      const key = (r.date || "").substring(0, 10) || "—";
      if (!g.has(key)) g.set(key, []);
      g.get(key).push(r);
    }
    return Array.from(g.entries());
  }, [rows]);

  return (
    <div>
      <PageHeader
        eyebrow="Cash flow"
        title="Cash Book"
        subtitle="Unified timeline of every money movement — sales, purchase, cash-book and transfers."
        actions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                data-testid="cashbook-add-btn"
                className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md"
              >
                <Plus size={16} /> New entry <ChevronDown size={14} />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem data-testid="cashbook-add-income" onClick={() => openNew("general_income")}>
                <ArrowDownRight size={14} className="mr-2" style={{ color: "var(--sage)" }} />
                General Income
              </DropdownMenuItem>
              <DropdownMenuItem data-testid="cashbook-add-expense" onClick={() => openNew("general_expense")}>
                <ArrowUpRight size={14} className="mr-2" style={{ color: "var(--terracotta)" }} />
                General Expense
              </DropdownMenuItem>
              <DropdownMenuItem data-testid="cashbook-add-transfer" onClick={() => openNew("transfer")}>
                <ArrowLeftRight size={14} className="mr-2" style={{ color: "#5B7180" }} />
                Transfer between accounts
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />

      {/* Helper note */}
      <div className="card-warm p-4 md:p-5 mb-6 flex items-start gap-3"
           style={{ background: "var(--surface-alt)" }} data-testid="cashbook-origin-note">
        <div className="text-xs" style={{ color: "var(--muted)" }}>
          <span className="serif text-base block mb-1" style={{ color: "var(--ink)" }}>
            Cash Book is a timeline, not a data-entry surface for orders or purchases.
          </span>
          Customer receipts flow from <b>Sales Payments</b>. Vendor payments flow from <b>Purchase Payments</b>. Cash Book itself only records genuine general income, general expense and inter-account transfers.
        </div>
      </div>

      {/* Filters */}
      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input
            data-testid="cashbook-filter-party"
            placeholder="Search party…"
            value={party}
            onChange={(e) => setParty(e.target.value)}
            className="pl-9 bg-white border-[var(--border-warm)]"
          />
        </div>
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger data-testid="cashbook-filter-source" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Source" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All sources</SelectItem>
            <SelectItem value="Sales Payments">Sales Payments</SelectItem>
            <SelectItem value="Purchase Payments">Purchase Payments</SelectItem>
            <SelectItem value="Cash Book">Cash Book</SelectItem>
            <SelectItem value="Migration">Migration</SelectItem>
          </SelectContent>
        </Select>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger data-testid="cashbook-filter-kind" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Kind" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All kinds</SelectItem>
            <SelectItem value="customer_payment">Customer Payment</SelectItem>
            <SelectItem value="vendor_payment">Vendor Payment</SelectItem>
            <SelectItem value="general_income">General Income</SelectItem>
            <SelectItem value="general_expense">General Expense</SelectItem>
            <SelectItem value="transfer">Transfer</SelectItem>
            <SelectItem value="legacy">Legacy</SelectItem>
          </SelectContent>
        </Select>
        <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
               data-testid="cashbook-start" className="bg-white border-[var(--border-warm)]" />
        <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
               data-testid="cashbook-end" className="bg-white border-[var(--border-warm)]" />
      </div>

      {/* Totals */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card-warm px-5 py-4">
          <div className="label-caps flex items-center gap-1"><ArrowDownRight size={12} /> Received</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--sage)" }} data-testid="cashbook-total-received">
            {fmtINR(totals.total_received)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps flex items-center gap-1"><ArrowUpRight size={12} /> Paid</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--terracotta)" }} data-testid="cashbook-total-paid">
            {fmtINR(totals.total_paid)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Net</div>
          <div className="serif text-2xl num mt-1"
               style={{ color: totals.net >= 0 ? "var(--sage)" : "var(--danger)" }}
               data-testid="cashbook-net">
            {fmtINR(totals.net)}
          </div>
        </div>
      </div>

      {/* Migration toggle */}
      <div className="mb-3 flex items-center gap-2 text-xs" style={{ color: "var(--muted)" }}>
        <label className="flex items-center gap-1.5 cursor-pointer" data-testid="cashbook-include-migration">
          <input type="checkbox" checked={includeMigration}
                 onChange={(e) => setIncludeMigration(e.target.checked)} />
          Include pre-refactor migration rows (read-only historic)
        </label>
        <span className="ml-auto">{count} events</span>
      </div>

      {/* Timeline */}
      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto max-h-[70vh]">
          <table className="ledger-table w-full min-w-[1000px]" data-testid="cashbook-table">
            <thead>
              <tr>
                <th className="w-[110px]">Date</th>
                <th>Description</th>
                <th>Source</th>
                <th>Mode</th>
                <th className="num">Received</th>
                <th className="num">Paid</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="7" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan="7" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>
                  No entries match the current filters.
                </td></tr>
              )}
              {!loading && grouped.map(([day, list]) => (
                list.map((r, idx) => (
                  <tr key={`${day}-${r.event_id}-${idx}`}
                      data-testid={`cashbook-row-${r.kind}`}
                      className="align-top">
                    <td className="whitespace-nowrap text-sm" style={{ color: "var(--ink)" }}>
                      {idx === 0 ? fmtDate(day) : <span className="text-[var(--muted)]">·</span>}
                    </td>
                    <td>
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5"><KindIcon kind={r.kind} /></span>
                        <div className="min-w-0">
                          <div className="text-sm font-medium truncate">{r.title}</div>
                          <div className="text-xs" style={{ color: "var(--muted)" }}>
                            {r.party || (r.kind === "transfer"
                              ? `${r.from_account_name || "—"} → ${r.to_account_name || "—"}`
                              : "—")}
                            {r.reference ? ` · Ref ${r.reference}` : ""}
                            {r.notes ? ` · ${r.notes}` : ""}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td><SourceTag label={r.source_module} /></td>
                    <td>
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs"
                            style={{ background: "var(--surface-alt)", color: "var(--ink)" }}>
                        {r.mode || "—"}
                      </span>
                    </td>
                    <td className="num" style={{ color: r.received > 0 ? "var(--sage)" : "var(--muted)" }}>
                      {r.received ? fmtINR(r.received) : "—"}
                    </td>
                    <td className="num" style={{ color: r.paid > 0 ? "var(--terracotta)" : "var(--muted)" }}>
                      {r.paid ? fmtINR(r.paid) : "—"}
                    </td>
                    <td className="text-right whitespace-nowrap">
                      {r.source_document?.collection && r.source_document?.collection !== "payments" && (
                        <button onClick={() => openSource(r)}
                                data-testid={`cashbook-open-source-${r.event_id}`}
                                title={`Open in ${r.source_module}`}
                                className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                          <ExternalLink size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                        </button>
                      )}
                      {r.editable && (
                        <>
                          <button onClick={() => { setEditing(r); setDialogKind(r.kind); setDialogOpen(true); }}
                                  className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1"
                                  data-testid={`cashbook-edit-${r.event_id}`}>
                            <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                          </button>
                          <button onClick={() => removeEntry(r)}
                                  className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1"
                                  data-testid={`cashbook-del-${r.event_id}`}>
                            <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <CashBookEntryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        initialKind={dialogKind}
        entry={editing ? {
          id: editing.event_id,
          date: editing.date,
          kind: editing.kind,
          amount: editing.amount,
          mode: editing.mode,
          account_name: editing.account_name,
          party_name: editing.party,
          from_account_name: editing.from_account_name,
          to_account_name: editing.to_account_name,
          reference: editing.reference,
          notes: editing.notes,
        } : null}
        onSaved={() => { setDialogOpen(false); setEditing(null); load(); }}
      />
    </div>
  );
}
