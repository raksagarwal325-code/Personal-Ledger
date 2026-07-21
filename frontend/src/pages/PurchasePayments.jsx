import { useEffect, useState, useMemo } from "react";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../components/ui/select";
import { Plus, Pencil, Trash2, Wallet, Search, Zap } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "../components/ui/dialog";
import { toast } from "sonner";

const emptyForm = () => ({
  vendor_name: "",
  date: new Date().toISOString().substring(0, 10),
  amount: 0,
  mode: "UPI",
  account_id: "",
  account_name: "",
  reference: "",
  remarks: "",
  allocations: [],
  paid_by_party_id: "",
  paid_by_party_name: "",
  split_paid_by_amount: "",
});

export default function PurchasePayments() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendors, setVendors] = useState([]);
  const [meta, setMeta] = useState({ payment_modes: ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"], accounts: [] });
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState("all");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [outstanding, setOutstanding] = useState([]);
  const [parties, setParties] = useState([]);   // for "Paid by" selector

  const load = () => {
    setLoading(true);
    const params = {};
    if (search) params.vendor_name = search;
    if (mode !== "all") params.mode = mode;
    api.get("/purchase-payments", { params }).then((r) => setRows(r.data))
       .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [mode]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);
  useEffect(() => {
    api.get("/vendors").then((r) => setVendors(r.data));
    api.get("/meta").then((r) => setMeta((m) => ({ ...m, ...r.data })));
    api.get("/party-ledger-v2/parties").then((r) => {
      // Only parties that could act as a payer for Rakshit (Father's Firm, others)
      const list = (r.data.parties || []).filter(
        (p) => p.type === "fathers_firm" || p.type === "other"
      );
      setParties(list);
    }).catch(() => setParties([]));
  }, []);

  const totals = useMemo(() => rows.reduce(
    (a, p) => ({
      total: a.total + (p.amount || 0),
      allocated: a.allocated + (p.allocated_total || 0),
      advance: a.advance + (p.unallocated || 0),
    }),
    { total: 0, allocated: 0, advance: 0 },
  ), [rows]);

  // ---- fetch outstanding purchases when vendor is chosen ----
  useEffect(() => {
    if (!dialogOpen || !form.vendor_name) { setOutstanding([]); return; }
    api.get(`/vendors/${encodeURIComponent(form.vendor_name)}/outstanding-purchases`)
       .then((r) => setOutstanding(r.data))
       .catch(() => setOutstanding([]));
  }, [dialogOpen, form.vendor_name]);

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
    setOutstanding([]);
    setDialogOpen(true);
  };
  const openEdit = async (p) => {
    try {
      const r = await api.get(`/purchase-payments/${p.id}`);
      const doc = r.data;
      setEditing(doc);
      setForm({
        ...emptyForm(),
        ...doc,
        date: doc.date ? doc.date.substring(0, 10) : "",
        allocations: doc.allocations || [],
      });
      setDialogOpen(true);
    } catch { toast.error("Could not load payment"); }
  };

  const allocSum = form.allocations.reduce((s, a) => s + (Number(a.amount) || 0), 0);
  const unalloc = Math.max(0, Number(form.amount || 0) - allocSum);

  const setAllocation = (purchase_id, amount) => {
    setForm((f) => {
      const others = f.allocations.filter((a) => a.purchase_id !== purchase_id);
      if (amount > 0) return { ...f, allocations: [...others, { purchase_id, amount }] };
      return { ...f, allocations: others };
    });
  };

  const autoAllocateFIFO = () => {
    let remaining = Number(form.amount || 0);
    const next = [];
    for (const p of outstanding) {
      if (remaining <= 0) break;
      const take = Math.min(remaining, p.outstanding_balance);
      if (take > 0) {
        next.push({ purchase_id: p.id, amount: Math.round(take * 100) / 100 });
        remaining -= take;
      }
    }
    setForm((f) => ({ ...f, allocations: next }));
  };

  const save = async (e) => {
    e.preventDefault();
    if (!form.vendor_name.trim()) return toast.error("Choose a vendor.");
    if (!(Number(form.amount) > 0)) return toast.error("Enter a payment amount.");
    if (allocSum > Number(form.amount || 0) + 0.5)
      return toast.error("Allocations cannot exceed payment amount.");
    try {
      const acct = (meta.accounts || []).find((a) => a.id === form.account_id);
      const paidByParty = parties.find((p) => p.id === form.paid_by_party_id);
      const payload = {
        ...form,
        account_name: acct ? acct.name : (form.account_name || ""),
        date: form.date ? new Date(form.date).toISOString() : null,
        paid_by_party_id: form.paid_by_party_id || null,
        paid_by_party_name: paidByParty ? paidByParty.name : null,
        split_paid_by_amount: form.split_paid_by_amount
          ? parseFloat(form.split_paid_by_amount) : null,
      };
      if (editing?.id) {
        await api.put(`/purchase-payments/${editing.id}`, payload);
        toast.success("Payment updated");
      } else {
        await api.post("/purchase-payments", payload);
        toast.success("Payment recorded");
      }
      setDialogOpen(false);
      load();
    } catch (err) {
      console.error(err);
      toast.error("Failed to save payment");
    }
  };

  const remove = async (p) => {
    if (!confirm("Delete this payment? Its allocations will be reversed on affected purchases.")) return;
    try {
      await api.delete(`/purchase-payments/${p.id}`);
      toast.success("Payment deleted");
      load();
    } catch { toast.error("Failed to delete"); }
  };

  const paymentModes = meta.payment_modes || ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"];

  return (
    <div data-testid="purchase-payments-page">
      <PageHeader
        eyebrow="Vendor payouts"
        title="Purchase payments"
        subtitle="Money paid out to vendors — with allocations against unpaid bills and any advance balances."
        actions={
          <Button onClick={openNew} data-testid="add-pp-btn"
                  className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md">
            <Plus size={16} /> New payment
          </Button>
        }
      />

      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input value={search} data-testid="pp-filter-vendor"
                 onChange={(e) => setSearch(e.target.value)} placeholder="Search vendor…"
                 className="pl-9 bg-white border-[var(--border-warm)]" />
        </div>
        <Select value={mode} onValueChange={setMode}>
          <SelectTrigger data-testid="pp-filter-mode" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Mode" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All modes</SelectItem>
            {paymentModes.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Payments</div>
          <div className="serif text-2xl num mt-1" data-testid="pp-count">{rows.length}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Total paid</div>
          <div className="serif text-2xl num mt-1" data-testid="pp-total">{fmtINR(totals.total)}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Allocated to bills</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--sage)" }}
               data-testid="pp-allocated">
            {fmtINR(totals.allocated)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Vendor advances</div>
          <div className="serif text-2xl num mt-1"
               style={{ color: totals.advance > 0.5 ? "var(--terracotta)" : "var(--sage)" }}
               data-testid="pp-advance">
            {fmtINR(totals.advance)}
          </div>
        </div>
      </div>

      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="ledger-table w-full min-w-[900px]" data-testid="pp-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Vendor</th>
                <th>Mode</th>
                <th>Account</th>
                <th className="num">Amount</th>
                <th className="num">Allocated</th>
                <th className="num">Advance</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-sm" style={{ color: "var(--muted)" }}>
                    <Wallet size={22} className="inline-block mb-2" strokeWidth={1.5} />
                    <div>No payments yet. Click "New payment" to record one.</div>
                  </td>
                </tr>
              )}
              {rows.map((p) => (
                <tr key={p.id} data-testid={`pp-row-${p.id}`}>
                  <td className="whitespace-nowrap">{fmtDate(p.date)}</td>
                  <td className="font-medium">{p.vendor_name}</td>
                  <td style={{ color: "var(--muted)" }}>{p.mode}</td>
                  <td style={{ color: "var(--muted)" }}>{p.account_name || "—"}</td>
                  <td className="num font-medium">{fmtINR(p.amount)}</td>
                  <td className="num" style={{ color: "var(--sage)" }}>{fmtINR(p.allocated_total)}</td>
                  <td className="num" style={{ color: p.unallocated > 0.5 ? "var(--terracotta)" : "var(--muted)" }}>
                    {fmtINR(p.unallocated)}
                  </td>
                  <td className="text-right whitespace-nowrap">
                    <button onClick={() => openEdit(p)} data-testid={`edit-pp-${p.id}`}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                      <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                    </button>
                    <button onClick={() => remove(p)} data-testid={`delete-pp-${p.id}`}
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

      {/* Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[92vh] overflow-y-auto" data-testid="pp-dialog">
          <DialogHeader>
            <DialogTitle className="serif text-3xl">{editing ? "Edit payment" : "New payment to vendor"}</DialogTitle>
            <DialogDescription className="text-xs">
              Record a payout and (optionally) allocate it to specific unpaid bills. Anything unallocated becomes a vendor advance.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-5 mt-2">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div className="md:col-span-2">
                <Label className="text-[11px] label-caps">Vendor*</Label>
                <Input list="vendor-list-pp" value={form.vendor_name}
                       data-testid="pp-vendor"
                       onChange={(e) => setForm({ ...form, vendor_name: e.target.value, allocations: [] })}
                       className="mt-1 bg-white border-[var(--border-warm)]"
                       placeholder="Type or select…" required />
                <datalist id="vendor-list-pp">
                  {vendors.map((v) => <option key={v.id} value={v.name} />)}
                </datalist>
              </div>
              <div>
                <Label className="text-[11px] label-caps">Date</Label>
                <Input type="date" data-testid="pp-date" value={form.date}
                       onChange={(e) => setForm({ ...form, date: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[11px] label-caps">Amount</Label>
                <Input type="number" step="0.01" value={form.amount}
                       data-testid="pp-amount"
                       onChange={(e) => setForm({ ...form, amount: parseFloat(e.target.value) || 0 })}
                       className="mt-1 bg-white border-[var(--border-warm)] num" />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <Label className="text-[11px] label-caps">Mode</Label>
                <Select value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v })}>
                  <SelectTrigger data-testid="pp-mode" className="mt-1 bg-white border-[var(--border-warm)]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {paymentModes.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[11px] label-caps">Account</Label>
                <Select value={form.account_id || "none"}
                        onValueChange={(v) => setForm({ ...form, account_id: v === "none" ? "" : v })}>
                  <SelectTrigger data-testid="pp-account" className="mt-1 bg-white border-[var(--border-warm)]">
                    <SelectValue placeholder="Account" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">— None —</SelectItem>
                    {(meta.accounts || []).map((a) =>
                      <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[11px] label-caps">Reference</Label>
                <Input data-testid="pp-reference" value={form.reference}
                       onChange={(e) => setForm({ ...form, reference: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
            </div>

            {/* Paid by (party-ledger linkage) */}
            <div className="card-warm p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="label-caps">Paid by</div>
                  <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                    Leave blank if Rakshit paid directly. Otherwise pick the party who
                    fronted the money — a linked entry will be posted on their ledger.
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <Label className="text-[11px] label-caps">Paid by (default: Rakshit)</Label>
                  <Select
                    value={form.paid_by_party_id || "self"}
                    onValueChange={(v) => setForm({
                      ...form,
                      paid_by_party_id: v === "self" ? "" : v,
                      split_paid_by_amount: v === "self" ? "" : form.split_paid_by_amount,
                    })}
                  >
                    <SelectTrigger data-testid="pp-paid-by" className="mt-1 bg-white border-[var(--border-warm)]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="self">Rakshit (me)</SelectItem>
                      {parties.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-[11px] label-caps">Split — paid_by portion (optional)</Label>
                  <Input
                    type="number" step="0.01" value={form.split_paid_by_amount}
                    onChange={(e) => setForm({ ...form, split_paid_by_amount: e.target.value })}
                    disabled={!form.paid_by_party_id}
                    data-testid="pp-split"
                    placeholder={form.amount ? `Full ${form.amount}` : "Full amount"}
                    className="mt-1 bg-white border-[var(--border-warm)] num"
                  />
                  <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
                    Leave blank if the paid_by party covers the full amount.
                  </div>
                </div>
              </div>
              {form.paid_by_party_id && (
                <div className="text-[11px] mt-2" style={{ color: "var(--muted)" }}>
                  Vendor payable reduces by ₹{Number(form.amount || 0).toLocaleString("en-IN")}. Linked party
                  ledger will shift by +₹{Number(
                    form.split_paid_by_amount ? form.split_paid_by_amount : form.amount || 0
                  ).toLocaleString("en-IN")}.
                </div>
              )}
            </div>

            {/* Outstanding bills allocation */}
            {form.vendor_name && (
              <div className="card-warm p-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="label-caps">Allocate to unpaid bills</div>
                    <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                      Anything unallocated is kept as a vendor advance.
                    </div>
                  </div>
                  {outstanding.length > 0 && (
                    <Button type="button" size="sm" onClick={autoAllocateFIFO}
                            data-testid="pp-auto-fifo"
                            className="bg-white border h-8 text-xs gap-1.5"
                            style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                      <Zap size={12} /> Auto FIFO
                    </Button>
                  )}
                </div>
                {outstanding.length === 0 ? (
                  <div className="text-xs py-4 rounded text-center"
                       style={{ background: "var(--surface-alt)", color: "var(--muted)" }}>
                    No unpaid bills for this vendor. Payment will be a full advance.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {outstanding.map((p) => {
                      const alloc = form.allocations.find((a) => a.purchase_id === p.id);
                      return (
                        <div key={p.id} className="grid grid-cols-6 gap-3 items-center text-sm py-2 border-b last:border-b-0"
                             style={{ borderColor: "var(--border-warm)" }}
                             data-testid={`pp-alloc-row-${p.id}`}>
                          <div className="col-span-2">
                            <div className="font-medium">{p.invoice_no || "—"}</div>
                            <div className="text-xs" style={{ color: "var(--muted)" }}>{fmtDate(p.purchase_date)}</div>
                          </div>
                          <div className="num text-xs">Inv {fmtINR(p.invoice_total)}</div>
                          <div className="num text-xs" style={{ color: "var(--sage)" }}>Paid {fmtINR(p.total_paid)}</div>
                          <div className="num text-xs" style={{ color: "var(--terracotta)" }}>
                            Due {fmtINR(p.outstanding_balance)}
                          </div>
                          <Input type="number" step="0.01"
                                 value={alloc ? alloc.amount : 0}
                                 data-testid={`pp-alloc-input-${p.id}`}
                                 onChange={(e) => setAllocation(p.id, parseFloat(e.target.value) || 0)}
                                 className="bg-white border-[var(--border-warm)] num h-8" />
                        </div>
                      );
                    })}
                  </div>
                )}
                <div className="grid grid-cols-3 gap-3 mt-3 pt-3 border-t text-sm"
                     style={{ borderColor: "var(--border-warm)" }}>
                  <div>
                    <div className="label-caps">Amount</div>
                    <div className="serif text-base num mt-0.5">{fmtINR(Number(form.amount || 0))}</div>
                  </div>
                  <div>
                    <div className="label-caps">Allocated</div>
                    <div className="serif text-base num mt-0.5" style={{ color: "var(--sage)" }}>
                      {fmtINR(allocSum)}
                    </div>
                  </div>
                  <div>
                    <div className="label-caps">Advance</div>
                    <div className="serif text-base num mt-0.5"
                         style={{ color: unalloc > 0.5 ? "var(--terracotta)" : "var(--muted)" }}
                         data-testid="pp-advance-amt">
                      {fmtINR(unalloc)}
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div>
              <Label className="text-[11px] label-caps">Remarks</Label>
              <Textarea data-testid="pp-remarks" value={form.remarks} rows={2}
                        onChange={(e) => setForm({ ...form, remarks: e.target.value })}
                        className="mt-1 bg-white border-[var(--border-warm)]" />
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}
                      className="border-[var(--border-warm)]">Cancel</Button>
              <Button type="submit" data-testid="pp-save-btn"
                      className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
                {editing ? "Update payment" : "Record payment"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
