import { useEffect, useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { api, fmtINR, fmtDate, MODES } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Plus, Search, Trash2, Pencil, ArrowUpRight, ArrowDownRight } from "lucide-react";
import PaymentDialog from "../components/PaymentDialog";
import { toast } from "sonner";

export default function Payments() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [mode, setMode] = useState("all");
  const [search, setSearch] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setEditing(null);
      setDialogOpen(true);
      searchParams.delete("new");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const load = () => {
    setLoading(true);
    const params = {};
    if (mode !== "all") params.mode = mode;
    if (search) params.party = search;
    if (startDate) params.start_date = new Date(startDate).toISOString();
    if (endDate) params.end_date = new Date(endDate).toISOString();
    api.get("/payments", { params })
      .then((r) => setItems(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [mode, startDate, endDate]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);

  // Running balance calc
  const rowsWithBalance = useMemo(() => {
    let bal = 0;
    return items.map((p) => {
      const received = (p.received_by_me || 0) + (p.received_by_fac || 0);
      const paid = (p.payment_by_me || 0) + (p.payment_by_fac || 0);
      bal += received - paid;
      return { ...p, received, paid, balance: bal };
    });
  }, [items]);

  const totals = useMemo(() => {
    return rowsWithBalance.reduce(
      (acc, r) => {
        acc.received += r.received;
        acc.paid += r.paid;
        return acc;
      },
      { received: 0, paid: 0 }
    );
  }, [rowsWithBalance]);

  const handleDelete = async (id) => {
    if (!confirm("Delete this payment?")) return;
    await api.delete(`/payments/${id}`);
    toast.success("Payment deleted");
    load();
  };

  return (
    <div>
      <PageHeader
        eyebrow="Cash flow"
        title="Payments & Ledger"
        subtitle="Track money in, money out, party-wise, across your accounts."
        actions={
          <Button
            onClick={() => { setEditing(null); setDialogOpen(true); }}
            data-testid="add-payment-btn"
            className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md"
          >
            <Plus size={16} /> New payment
          </Button>
        }
      />

      {/* Filters */}
      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input
            data-testid="pay-filter-search"
            placeholder="Search party…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-white border-[var(--border-warm)]"
          />
        </div>
        <Select value={mode} onValueChange={setMode}>
          <SelectTrigger data-testid="pay-filter-mode" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Mode" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All modes</SelectItem>
            {MODES.map((m) => (<SelectItem key={m} value={m}>{m}</SelectItem>))}
          </SelectContent>
        </Select>
        <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
               data-testid="pay-start" className="bg-white border-[var(--border-warm)]" />
        <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
               data-testid="pay-end" className="bg-white border-[var(--border-warm)]" />
      </div>

      {/* Totals */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card-warm px-5 py-4">
          <div className="label-caps flex items-center gap-1"><ArrowDownRight size={12} /> Received</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--sage)" }} data-testid="total-received">
            {fmtINR(totals.received)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps flex items-center gap-1"><ArrowUpRight size={12} /> Paid</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--terracotta)" }} data-testid="total-paid">
            {fmtINR(totals.paid)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Net Balance</div>
          <div className="serif text-2xl num mt-1"
               style={{ color: totals.received - totals.paid >= 0 ? "var(--sage)" : "var(--danger)" }}
               data-testid="net-balance">
            {fmtINR(totals.received - totals.paid)}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto max-h-[70vh]">
          <table className="ledger-table w-full min-w-[900px]" data-testid="payments-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Party</th>
                <th>Mode</th>
                <th className="num">Received</th>
                <th className="num">Paid</th>
                <th className="num">Balance</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="7" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rowsWithBalance.length === 0 && (
                <tr><td colSpan="7" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>
                  No payments yet.
                </td></tr>
              )}
              {rowsWithBalance.map((p) => (
                <tr key={p.id}>
                  <td className="whitespace-nowrap">{fmtDate(p.date)}</td>
                  <td className="max-w-[240px] truncate">{p.party}</td>
                  <td>
                    <span className="inline-block px-2 py-0.5 rounded-full text-xs"
                          style={{ background: "var(--surface-alt)", color: "var(--ink)" }}>
                      {p.mode}
                    </span>
                  </td>
                  <td className="num" style={{ color: p.received > 0 ? "var(--sage)" : "var(--muted)" }}>
                    {p.received ? fmtINR(p.received) : "—"}
                  </td>
                  <td className="num" style={{ color: p.paid > 0 ? "var(--terracotta)" : "var(--muted)" }}>
                    {p.paid ? fmtINR(p.paid) : "—"}
                  </td>
                  <td className="num font-medium"
                      style={{ color: p.balance >= 0 ? "var(--sage)" : "var(--danger)" }}>
                    {fmtINR(p.balance)}
                  </td>
                  <td className="text-right whitespace-nowrap">
                    <button onClick={() => { setEditing(p); setDialogOpen(true); }}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                      <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                    </button>
                    <button onClick={() => handleDelete(p.id)} data-testid={`del-pay-${p.id}`}
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

      <PaymentDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        payment={editing}
        onSaved={() => { setDialogOpen(false); load(); }}
      />
    </div>
  );
}
