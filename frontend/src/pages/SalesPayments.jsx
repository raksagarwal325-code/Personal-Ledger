import { useEffect, useState } from "react";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Plus, Search, Pencil, Trash2 } from "lucide-react";
import CustomerPaymentDialog from "../components/CustomerPaymentDialog";
import { toast } from "sonner";

export default function SalesPayments() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState({ accounts: [], payment_modes: [] });

  const [accountId, setAccountId] = useState("all");
  const [mode, setMode] = useState("all");
  const [search, setSearch] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
  }, []);

  const load = () => {
    setLoading(true);
    const params = {};
    if (accountId !== "all") params.account_id = accountId;
    if (mode !== "all") params.mode = mode;
    if (search) params.client_name = search;
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    api.get("/sales-payments", { params })
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [accountId, mode, startDate, endDate]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);

  const handleDelete = async (id) => {
    if (!confirm("Delete this payment? Any allocations to invoices will be reversed.")) return;
    await api.delete(`/customer-payments/${id}`);
    toast.success("Payment deleted");
    load();
  };

  const openNew = () => { setEditing(null); setDialogOpen(true); };
  const openEdit = (row) => {
    // fetch full record (with allocations) — sales-payments endpoint already returns them
    setEditing({
      id: row.id,
      customer_name: row.customer_name,
      date: row.date,
      amount: row.amount,
      mode: row.mode,
      account_id: row.account_id,
      account_name: row.account_name,
      reference: row.reference,
      remarks: row.remarks,
      allocations: row.allocations || [],
    });
    setDialogOpen(true);
  };

  return (
    <div>
      <PageHeader
        eyebrow="Customer Payments"
        title="Sales Payments"
        subtitle="Log every receipt against an order or as an advance. Payments flow into the Party Ledger and Cash Book automatically."
        actions={
          <Button onClick={openNew} data-testid="new-cp-btn"
                  className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md">
            <Plus size={16} /> New payment
          </Button>
        }
      />

      {/* Filters */}
      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input value={search} data-testid="sp-search"
                 onChange={(e) => setSearch(e.target.value)} placeholder="Search customer…"
                 className="pl-9 bg-white border-[var(--border-warm)]" />
        </div>
        <Select value={accountId} onValueChange={setAccountId}>
          <SelectTrigger data-testid="sp-account" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Account" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All accounts</SelectItem>
            {(meta.accounts || []).map((a) => (
              <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={mode} onValueChange={setMode}>
          <SelectTrigger data-testid="sp-mode" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Mode" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All modes</SelectItem>
            {(meta.payment_modes || []).map((m) => (
              <SelectItem key={m} value={m}>{m}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="grid grid-cols-2 gap-2">
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                 className="bg-white border-[var(--border-warm)]" />
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
                 className="bg-white border-[var(--border-warm)]" />
        </div>
      </div>

      {/* Totals */}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <div className="card-warm px-5 py-4">
            <div className="label-caps">Payments</div>
            <div className="serif text-2xl num mt-1" data-testid="sp-count">{data.count}</div>
          </div>
          <div className="card-warm px-5 py-4">
            <div className="label-caps">Total received</div>
            <div className="serif text-2xl num mt-1" style={{ color: "var(--sage)" }}
                 data-testid="sp-total">{fmtINR(data.total)}</div>
          </div>
          <div className="card-warm px-5 py-4">
            <div className="label-caps">Held as advance</div>
            <div className="serif text-2xl num mt-1" style={{ color: "var(--terracotta)" }}
                 data-testid="sp-advance">{fmtINR(data.total_advance || 0)}</div>
          </div>
          <div className="card-warm px-5 py-4">
            <div className="label-caps">Top account</div>
            <div className="serif text-xl mt-1">
              {data.by_account[0]?.account || "—"}
            </div>
            <div className="text-xs" style={{ color: "var(--muted)" }}>
              {data.by_account[0] ? fmtINR(data.by_account[0].amount) : ""}
            </div>
          </div>
        </div>
      )}

      {data && (data.by_account.length > 0 || data.by_mode.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          <div className="card-warm p-5">
            <div className="label-caps mb-3">By account</div>
            <div className="space-y-2">
              {data.by_account.map((r) => (
                <div key={r.account} className="flex justify-between text-sm">
                  <span>{r.account}</span>
                  <span className="serif num">{fmtINR(r.amount)}
                    <span className="text-xs ml-2" style={{ color: "var(--muted)" }}>· {r.count}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="card-warm p-5">
            <div className="label-caps mb-3">By mode</div>
            <div className="space-y-2">
              {data.by_mode.map((r) => (
                <div key={r.mode} className="flex justify-between text-sm">
                  <span>{r.mode}</span>
                  <span className="serif num">{fmtINR(r.amount)}
                    <span className="text-xs ml-2" style={{ color: "var(--muted)" }}>· {r.count}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto max-h-[70vh]">
          <table className="ledger-table w-full min-w-[960px]" data-testid="sp-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Customer</th>
                <th className="num">Amount</th>
                <th className="num">Allocated</th>
                <th>Mode</th>
                <th>Account</th>
                <th>Reference</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="8" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && data && data.payments.length === 0 && (
                <tr><td colSpan="8" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>
                  No payments yet. Click "New payment" to record one.
                </td></tr>
              )}
              {data && data.payments.map((p) => (
                <tr key={p.id} data-testid={`sp-row-${p.id}`}>
                  <td className="whitespace-nowrap">{fmtDate(p.date)}</td>
                  <td className="max-w-[220px] truncate">{p.customer_name}</td>
                  <td className="num font-medium" style={{ color: "var(--sage)" }}>{fmtINR(p.amount)}</td>
                  <td className="num text-xs">
                    {fmtINR(p.allocated || 0)}
                    {(p.advance || 0) > 0 && (
                      <div className="text-[10px]" style={{ color: "var(--terracotta)" }}>
                        + Advance {fmtINR(p.advance)}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className="inline-block px-2 py-0.5 rounded-full text-xs"
                          style={{ background: "var(--surface-alt)", color: "var(--ink)" }}>
                      {p.mode || "—"}
                    </span>
                  </td>
                  <td>{p.account_name || "—"}</td>
                  <td className="text-xs" style={{ color: "var(--muted)" }}>{p.reference || "—"}</td>
                  <td className="text-right whitespace-nowrap">
                    <button onClick={() => openEdit(p)} data-testid={`sp-edit-${p.id}`}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                      <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                    </button>
                    <button onClick={() => handleDelete(p.id)} data-testid={`sp-del-${p.id}`}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1">
                      <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <CustomerPaymentDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        payment={editing}
        onSaved={() => { setDialogOpen(false); load(); }}
      />
    </div>
  );
}
