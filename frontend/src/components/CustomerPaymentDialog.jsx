import { useState, useEffect, useMemo } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Textarea } from "./ui/textarea";
import { api, fmtINR, fmtDate } from "../lib/api";
import { toast } from "sonner";
import { Banknote, Landmark, Wand2 } from "lucide-react";

const empty = () => ({
  customer_name: "",
  date: new Date().toISOString().substring(0, 10),
  amount: 0,
  mode: "UPI",
  account_id: "",
  account_name: "",
  reference: "",
  remarks: "",
  allocations: [],
  received_by_party_id: "",
  received_by_party_name: "",
});

export default function CustomerPaymentDialog({ open, onOpenChange, payment, defaultCustomer, onSaved }) {
  const [form, setForm] = useState(empty());
  const [saving, setSaving] = useState(false);
  const [meta, setMeta] = useState({ accounts: [], payment_modes: [], clients: [] });
  const [outstanding, setOutstanding] = useState([]);
  const [loadingOrders, setLoadingOrders] = useState(false);
  const [parties, setParties] = useState([]);

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
    api.get("/party-ledger-v2/parties").then((r) => {
      const list = (r.data.parties || []).filter(
        (p) => p.type === "fathers_firm" || p.type === "other"
      );
      setParties(list);
    }).catch(() => setParties([]));
  }, []);

  useEffect(() => {
    if (!open) return;
    if (payment) {
      setForm({
        ...empty(),
        ...payment,
        date: payment.date ? payment.date.substring(0, 10) : "",
        allocations: (payment.allocations || []).map((a) => ({ ...a })),
      });
    } else {
      setForm({ ...empty(), customer_name: defaultCustomer || "" });
    }
  }, [payment, open, defaultCustomer]);

  // Load outstanding orders for chosen customer
  useEffect(() => {
    const cname = form.customer_name?.trim();
    if (!cname) { setOutstanding([]); return; }
    setLoadingOrders(true);
    api.get(`/customers/${encodeURIComponent(cname)}/outstanding-orders`)
      .then((r) => setOutstanding(r.data.orders || []))
      .catch(() => setOutstanding([]))
      .finally(() => setLoadingOrders(false));
  }, [form.customer_name, open]);

  // Auto-allocate FIFO whenever the amount or outstanding list changes, but only
  // when the user has not manually set any allocation. This fixes the common bug
  // where a payment recorded from Sales Payments never appears on the Order
  // because allocations were left empty.
  useEffect(() => {
    if (!open) return;
    if ((form.allocations || []).length > 0) return;   // respect manual entries
    if (!(Number(form.amount) > 0)) return;
    if (!outstanding.length) return;
    let bucket = Number(form.amount || 0);
    const allocs = [];
    for (const o of outstanding) {
      if (bucket <= 0.001) break;
      const take = Math.min(Math.max(0, o.outstanding || 0), bucket);
      if (take > 0.001) {
        allocs.push({ order_id: o.id, amount: Number(take.toFixed(2)) });
        bucket -= take;
      }
    }
    if (allocs.length > 0) {
      setForm((f) => ({ ...f, allocations: allocs }));
    }
    // eslint-disable-next-line
  }, [form.amount, outstanding, open]);

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const allocFor = (oid) =>
    (form.allocations || []).find((a) => a.order_id === oid)?.amount ?? 0;

  const setAlloc = (oid, val) => {
    setForm((f) => {
      const arr = [...(f.allocations || [])];
      const idx = arr.findIndex((a) => a.order_id === oid);
      if (val > 0) {
        if (idx >= 0) arr[idx] = { ...arr[idx], amount: val };
        else arr.push({ order_id: oid, amount: val });
      } else if (idx >= 0) {
        arr.splice(idx, 1);
      }
      return { ...f, allocations: arr };
    });
  };

  const totalAllocated = useMemo(
    () => (form.allocations || []).reduce((s, a) => s + Number(a.amount || 0), 0),
    [form.allocations],
  );
  const remaining = Number(form.amount || 0) - totalAllocated;

  // Auto-allocate FIFO
  const autoAllocate = () => {
    let bucket = Number(form.amount || 0);
    const allocs = [];
    for (const o of outstanding) {
      if (bucket <= 0.001) break;
      // Preserve existing allocation for editing scenario:
      const existing = payment?.allocations?.find((a) => a.order_id === o.id)?.amount || 0;
      const stillOutstanding = Math.max(0, (o.outstanding || 0) + existing);
      const take = Math.min(stillOutstanding, bucket);
      if (take > 0.001) {
        allocs.push({ order_id: o.id, amount: Number(take.toFixed(2)) });
        bucket -= take;
      }
    }
    setForm((f) => ({ ...f, allocations: allocs }));
    if (bucket > 0.5) {
      toast.message(`Advance ₹${bucket.toFixed(0)} left after allocation`);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.customer_name?.trim()) return toast.error("Choose a customer.");
    if (Number(form.amount || 0) <= 0) return toast.error("Enter payment amount.");
    if (totalAllocated > Number(form.amount || 0) + 0.01)
      return toast.error("Allocations exceed payment amount.");

    setSaving(true);
    try {
      const rcvParty = parties.find((p) => p.id === form.received_by_party_id);
      const payload = {
        customer_name: form.customer_name.trim(),
        date: form.date ? new Date(form.date).toISOString() : null,
        amount: Number(form.amount) || 0,
        mode: form.mode || "Cash",
        account_id: form.account_id || "",
        account_name: form.account_name || "",
        reference: form.reference || "",
        remarks: form.remarks || "",
        allocations: (form.allocations || [])
          .filter((a) => Number(a.amount) > 0)
          .map((a) => ({ order_id: a.order_id, amount: Number(a.amount) })),
        received_by_party_id: form.received_by_party_id || null,
        received_by_party_name: rcvParty ? rcvParty.name : null,
      };
      if (payment?.id) {
        await api.put(`/customer-payments/${payment.id}`, payload);
        toast.success("Payment updated");
      } else {
        await api.post("/customer-payments", payload);
        toast.success("Payment recorded");
      }
      onSaved?.();
    } catch (err) {
      console.error(err);
      toast.error(err?.response?.data?.detail || "Failed to save payment.");
    } finally {
      setSaving(false);
    }
  };

  const chosenAccount = (meta.accounts || []).find((a) => a.id === form.account_id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[92vh] overflow-y-auto" data-testid="customer-payment-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-3xl flex items-center gap-2">
            <Banknote size={22} strokeWidth={1.5} style={{ color: "var(--terracotta)" }} />
            {payment ? "Edit customer payment" : "New customer payment"}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            Record money received. Allocate the amount across one or more invoices — anything unallocated becomes an advance.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-6 mt-2">
          {/* Customer + amount */}
          <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="md:col-span-2">
              <Label className="text-[10px] label-caps">Customer</Label>
              <Input value={form.customer_name} onChange={(e) => setField("customer_name", e.target.value)}
                     list="cp-clients" placeholder="Type or pick customer…"
                     data-testid="cp-customer"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
              <datalist id="cp-clients">
                {(meta.clients || []).map((c) => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div>
              <Label className="text-[10px] label-caps">Amount</Label>
              <div className="relative mt-1.5">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs" style={{ color: "var(--muted)" }}>₹</span>
                <Input type="number" step="0.01" value={form.amount === 0 ? "" : form.amount} placeholder="0"
                       onChange={(e) => setField("amount", parseFloat(e.target.value) || 0)}
                       data-testid="cp-amount"
                       className="pl-6 bg-white border-[var(--border-warm)] num text-right" />
              </div>
            </div>
            <div>
              <Label className="text-[10px] label-caps">Date</Label>
              <Input type="date" value={form.date} onChange={(e) => setField("date", e.target.value)}
                     data-testid="cp-date"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </section>

          {/* Mode + Account + reference */}
          <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label className="text-[10px] label-caps">Mode</Label>
              <Select value={form.mode} onValueChange={(v) => setField("mode", v)}>
                <SelectTrigger data-testid="cp-mode" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(meta.payment_modes || []).map((m) => (<SelectItem key={m} value={m}>{m}</SelectItem>))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] label-caps flex items-center gap-1">
                <Landmark size={11} strokeWidth={2} /> Received in account
              </Label>
              <Select value={form.account_id || "__none__"}
                      onValueChange={(v) => {
                        if (v === "__none__") {
                          setForm((f) => ({ ...f, account_id: "", account_name: "" }));
                          return;
                        }
                        const acc = (meta.accounts || []).find((a) => a.id === v);
                        setForm((f) => ({ ...f, account_id: v, account_name: acc?.name || "" }));
                      }}>
                <SelectTrigger data-testid="cp-account" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue placeholder="Select account…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Unassigned</SelectItem>
                  {(meta.accounts || []).map((a) => (
                    <SelectItem key={a.id} value={a.id}>{a.name} · {a.type}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {chosenAccount && (
                <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
                  Routed to {chosenAccount.name}
                </div>
              )}
            </div>
            <div>
              <Label className="text-[10px] label-caps">Reference / UTR</Label>
              <Input value={form.reference} onChange={(e) => setField("reference", e.target.value)}
                     data-testid="cp-ref"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </section>

          {/* Received by (party-ledger linkage) */}
          <section className="card-warm p-4 md:p-5">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="label-caps">Received by</div>
                <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                  Select who actually collected the customer's payment. This automatically updates the Party Ledger if someone else collected it on your behalf.
                </div>
              </div>
            </div>
            <Select
              value={form.received_by_party_id || "self"}
              onValueChange={(v) => setField("received_by_party_id", v === "self" ? "" : v)}
            >
              <SelectTrigger data-testid="cp-received-by" className="mt-1.5 bg-white border-[var(--border-warm)]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="self">Rakshit (me)</SelectItem>
                {parties.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
            {form.received_by_party_id && (
              <div className="text-[11px] mt-2" style={{ color: "var(--muted)" }}>
                Customer receivable reduces by ₹{Number(form.amount || 0).toLocaleString("en-IN")}.
                {" "}Linked party ledger will shift by −₹{Number(form.amount || 0).toLocaleString("en-IN")} (they now owe you back).
              </div>
            )}
          </section>

          {/* Allocations */}
          <section className="card-warm p-4 md:p-5">
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="label-caps">Allocate to invoices</div>
                <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                  Unallocated amount is kept as a customer advance.
                </div>
              </div>
              <Button type="button" size="sm" onClick={autoAllocate}
                      disabled={!form.customer_name || !form.amount}
                      data-testid="cp-auto-allocate"
                      className="bg-white border h-8 text-xs gap-1.5"
                      style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                <Wand2 size={13} /> Auto-allocate FIFO
              </Button>
            </div>

            {!form.customer_name && (
              <div className="text-xs py-4 text-center" style={{ color: "var(--muted)" }}>
                Choose a customer first to see their unpaid invoices.
              </div>
            )}
            {form.customer_name && loadingOrders && (
              <div className="text-xs py-4 text-center" style={{ color: "var(--muted)" }}>Loading invoices…</div>
            )}
            {form.customer_name && !loadingOrders && outstanding.length === 0 && (
              <div className="text-xs py-4 text-center" style={{ color: "var(--muted)" }}>
                No outstanding invoices — this payment will be recorded as an advance.
              </div>
            )}
            {outstanding.length > 0 && (
              <div className="rounded-md border overflow-hidden bg-white"
                   style={{ borderColor: "var(--border-warm)" }}>
                <table className="w-full text-sm" data-testid="cp-alloc-table">
                  <thead style={{ background: "var(--surface-alt)" }}>
                    <tr>
                      <th className="text-left p-3 label-caps">Order</th>
                      <th className="text-right p-3 label-caps">Invoice Total</th>
                      <th className="text-right p-3 label-caps">Already Paid</th>
                      <th className="text-right p-3 label-caps">Balance Due</th>
                      <th className="text-right p-3 label-caps">Outstanding</th>
                      <th className="text-right p-3 label-caps">Allocate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {outstanding.map((o, idx) => {
                      const cur = allocFor(o.id);
                      const existingForEdit = payment?.allocations?.find((a) => a.order_id === o.id)?.amount || 0;
                      const remainingWithSelf = (o.outstanding || 0) + existingForEdit;
                      const balanceDue = Math.max(0, (o.invoice_total || 0) - (o.total_received || 0));
                      const outstandingAfter = Math.max(0, remainingWithSelf - Number(cur || 0));
                      return (
                        <tr key={o.id} className="border-t"
                            style={{ borderColor: "var(--border-warm)" }}
                            data-testid={`cp-alloc-row-${idx}`}>
                          <td className="p-3">
                            <div className="text-xs" style={{ color: "var(--muted)" }}>#{o.short_id}</div>
                            <div className="text-xs">{fmtDate(o.date)}</div>
                            <div className="text-[10px]" style={{ color: "var(--muted)" }}>
                              {o.status} · {o.payment_status}
                            </div>
                          </td>
                          <td className="p-3 text-right num">{fmtINR(o.invoice_total)}</td>
                          <td className="p-3 text-right num" style={{ color: "var(--sage)" }}>
                            {fmtINR(o.total_received)}
                          </td>
                          <td className="p-3 text-right num">
                            {fmtINR(balanceDue)}
                          </td>
                          <td className="p-3 text-right num" style={{ color: "var(--terracotta)" }}>
                            {fmtINR(outstandingAfter)}
                          </td>
                          <td className="p-3 text-right">
                            <div className="relative w-28 ml-auto">
                              <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs"
                                    style={{ color: "var(--muted)" }}>₹</span>
                              <Input type="number" step="0.01"
                                     value={cur === 0 ? "" : cur}
                                     placeholder="0"
                                     max={remainingWithSelf}
                                     onChange={(e) => setAlloc(o.id, parseFloat(e.target.value) || 0)}
                                     data-testid={`cp-alloc-input-${idx}`}
                                     className="pl-5 pr-1 h-8 text-right num bg-white border-[var(--border-warm)]" />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mt-4 grid grid-cols-3 gap-4 pt-3 border-t"
                 style={{ borderColor: "var(--border-warm)" }}>
              <div>
                <div className="text-[10px] label-caps">Payment</div>
                <div className="serif text-lg num mt-1">{fmtINR(form.amount)}</div>
              </div>
              <div>
                <div className="text-[10px] label-caps">Allocated</div>
                <div className="serif text-lg num mt-1" style={{ color: "var(--sage)" }}
                     data-testid="cp-allocated-total">{fmtINR(totalAllocated)}</div>
              </div>
              <div>
                <div className="text-[10px] label-caps">
                  {remaining > 0.5 ? "Advance / Unallocated" : remaining < -0.5 ? "Over-allocated" : "Balanced"}
                </div>
                <div className="serif text-lg num mt-1"
                     style={{ color: remaining < -0.5 ? "var(--danger)" : "var(--terracotta)" }}
                     data-testid="cp-advance">{fmtINR(Math.max(0, remaining))}</div>
              </div>
            </div>
          </section>

          <div>
            <Label className="text-[10px] label-caps">Remarks</Label>
            <Textarea rows={2} value={form.remarks} onChange={(e) => setField("remarks", e.target.value)}
                      data-testid="cp-remarks"
                      className="mt-1.5 bg-white border-[var(--border-warm)]" />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="cp-save-btn"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Saving…" : payment ? "Update payment" : "Record payment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
