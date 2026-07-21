import { useState, useEffect, useMemo } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Switch } from "./ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "./ui/select";
import { Trash2, Plus, User, MapPin, Package, Receipt } from "lucide-react";
import { api, fmtINR } from "../lib/api";
import { toast } from "sonner";

const emptyItem = () => ({
  id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
  product_name: "",
  description: "",
  qty: 1,
  rate: 0,
  amount: 0,
});

const emptyQuotation = () => ({
  quote_number: "",
  quote_date: new Date().toISOString().substring(0, 10),
  valid_until: "",
  client_name: "",
  client_phone: "",
  client_email: "",
  billing_address: "",
  billing_city: "",
  billing_pincode: "",
  shipping_same_as_billing: true,
  shipping_address: "",
  shipping_city: "",
  shipping_pincode: "",
  items: [emptyItem()],
  gst_rate: 18,
  freight_type: "extra",
  freight_amount: 0,
  notes: "",
  terms: "Prices are valid for 30 days. Payment: 50% advance, 50% before dispatch. GST as applicable.",
  status: "Draft",
});

const GST_RATES = [0, 5, 12, 18, 28];

export default function QuotationDialog({ open, onOpenChange, quotation, onSaved }) {
  const [form, setForm] = useState(emptyQuotation());
  const [saving, setSaving] = useState(false);
  const [meta, setMeta] = useState({ clients: [] });

  useEffect(() => {
    api.get("/meta").then((r) => setMeta((m) => ({ ...m, ...r.data }))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    if (quotation) {
      setForm({
        ...emptyQuotation(),
        ...quotation,
        quote_date: quotation.quote_date ? quotation.quote_date.substring(0, 10) : "",
        valid_until: quotation.valid_until ? quotation.valid_until.substring(0, 10) : "",
        items: (quotation.items && quotation.items.length) ? quotation.items : [emptyItem()],
      });
    } else {
      // Fetch next quote number for new quotations
      api.get("/quotations/next-number").then((r) => {
        setForm({ ...emptyQuotation(), quote_number: r.data.quote_number });
      }).catch(() => setForm(emptyQuotation()));
    }
  }, [open, quotation]);

  const update = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const updateItem = (idx, patch) => setForm((f) => ({
    ...f,
    items: f.items.map((it, i) => {
      if (i !== idx) return it;
      const next = { ...it, ...patch };
      if ("qty" in patch || "rate" in patch) {
        next.amount = (Number(next.qty) || 0) * (Number(next.rate) || 0);
      }
      return next;
    }),
  }));
  const addItem = () => setForm((f) => ({ ...f, items: [...f.items, emptyItem()] }));
  const removeItem = (idx) => setForm((f) => ({
    ...f,
    items: f.items.length === 1 ? f.items : f.items.filter((_, i) => i !== idx),
  }));

  const totals = useMemo(() => {
    const subtotal = (form.items || []).reduce(
      (s, i) => s + (Number(i.qty) || 0) * (Number(i.rate) || 0), 0
    );
    const freight = form.freight_type === "extra" ? (Number(form.freight_amount) || 0) : 0;
    const taxable = subtotal + freight;
    const tax = taxable * (Number(form.gst_rate) || 0) / 100;
    const total = taxable + tax;
    return { subtotal, freight, taxable, tax, total };
  }, [form]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.client_name?.trim()) return toast.error("Enter the client name.");
    if (!form.items.length || !form.items.some((i) => i.product_name?.trim())) {
      return toast.error("Add at least one line item.");
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        quote_date: form.quote_date ? new Date(form.quote_date).toISOString() : null,
        valid_until: form.valid_until ? new Date(form.valid_until).toISOString() : null,
      };
      if (quotation?.id) {
        await api.put(`/quotations/${quotation.id}`, payload);
        toast.success("Quotation updated");
      } else {
        await api.post("/quotations", payload);
        toast.success("Quotation created");
      }
      onSaved?.();
    } catch (err) {
      console.error(err);
      toast.error("Failed to save quotation");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[92vh] overflow-y-auto" data-testid="quotation-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-3xl">
            {quotation ? `Edit ${quotation.quote_number || "quotation"}` : "New quotation"}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            Draft, share and track quotations. Totals recompute live below.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-8 mt-2">
          {/* HEADER META */}
          <section>
            <div className="label-caps mb-3 flex items-center gap-2">
              <Receipt size={13} strokeWidth={1.75} /> Quotation
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <Label className="text-[10px] label-caps">Quote #</Label>
                <Input
                  value={form.quote_number}
                  onChange={(e) => update("quote_number", e.target.value)}
                  data-testid="quot-number"
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Quote date</Label>
                <Input
                  type="date"
                  value={form.quote_date}
                  onChange={(e) => update("quote_date", e.target.value)}
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Valid until</Label>
                <Input
                  type="date"
                  value={form.valid_until}
                  onChange={(e) => update("valid_until", e.target.value)}
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Status</Label>
                <Select value={form.status} onValueChange={(v) => update("status", v)}>
                  <SelectTrigger data-testid="quot-status-input" className="mt-1.5 bg-white border-[var(--border-warm)]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {["Draft", "Sent", "Accepted", "Rejected", "Converted"].map((s) => (
                      <SelectItem key={s} value={s}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </section>

          {/* CLIENT */}
          <section>
            <div className="label-caps mb-3 flex items-center gap-2">
              <User size={13} strokeWidth={1.75} /> Client
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <Label className="text-[10px] label-caps">Client name</Label>
                <Input
                  value={form.client_name}
                  onChange={(e) => update("client_name", e.target.value)}
                  list="q-clients"
                  data-testid="quot-client"
                  placeholder="e.g. Minakshi Jain"
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
                <datalist id="q-clients">
                  {(meta.clients || []).map((c) => <option key={c} value={c} />)}
                </datalist>
              </div>
              <div>
                <Label className="text-[10px] label-caps">Phone</Label>
                <Input
                  value={form.client_phone}
                  onChange={(e) => update("client_phone", e.target.value)}
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Email</Label>
                <Input
                  value={form.client_email}
                  onChange={(e) => update("client_email", e.target.value)}
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
            </div>
          </section>

          {/* ADDRESSES */}
          <section>
            <div className="label-caps mb-3 flex items-center gap-2">
              <MapPin size={13} strokeWidth={1.75} /> Addresses
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="card-warm p-4">
                <div className="text-xs mb-2" style={{ color: "var(--muted)" }}>Billing</div>
                <Textarea
                  rows={2}
                  value={form.billing_address}
                  onChange={(e) => update("billing_address", e.target.value)}
                  placeholder="Street, area…"
                  className="bg-white border-[var(--border-warm)]"
                />
                <div className="grid grid-cols-2 gap-3 mt-3">
                  <div>
                    <Label className="text-[10px] label-caps">City</Label>
                    <Input
                      value={form.billing_city}
                      onChange={(e) => update("billing_city", e.target.value)}
                      className="mt-1.5 bg-white border-[var(--border-warm)]"
                    />
                  </div>
                  <div>
                    <Label className="text-[10px] label-caps">Pincode</Label>
                    <Input
                      value={form.billing_pincode}
                      onChange={(e) => update("billing_pincode", e.target.value)}
                      data-testid="quot-billing-pincode"
                      className="mt-1.5 bg-white border-[var(--border-warm)]"
                    />
                  </div>
                </div>
              </div>

              <div className="card-warm p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs" style={{ color: "var(--muted)" }}>Shipping</div>
                  <div className="flex items-center gap-2">
                    <Label className="text-[10px] label-caps">Same as billing</Label>
                    <Switch
                      checked={form.shipping_same_as_billing}
                      onCheckedChange={(v) => update("shipping_same_as_billing", v)}
                      data-testid="quot-ship-same"
                    />
                  </div>
                </div>
                {form.shipping_same_as_billing ? (
                  <div className="text-xs p-3 rounded" style={{ background: "var(--surface-alt)", color: "var(--muted)" }}>
                    Shipping will mirror the billing address.
                  </div>
                ) : (
                  <>
                    <Textarea
                      rows={2}
                      value={form.shipping_address}
                      onChange={(e) => update("shipping_address", e.target.value)}
                      className="bg-white border-[var(--border-warm)]"
                    />
                    <div className="grid grid-cols-2 gap-3 mt-3">
                      <div>
                        <Label className="text-[10px] label-caps">City</Label>
                        <Input
                          value={form.shipping_city}
                          onChange={(e) => update("shipping_city", e.target.value)}
                          className="mt-1.5 bg-white border-[var(--border-warm)]"
                        />
                      </div>
                      <div>
                        <Label className="text-[10px] label-caps">Pincode</Label>
                        <Input
                          value={form.shipping_pincode}
                          onChange={(e) => update("shipping_pincode", e.target.value)}
                          className="mt-1.5 bg-white border-[var(--border-warm)]"
                        />
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>

          {/* LINE ITEMS */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <div className="label-caps flex items-center gap-2">
                <Package size={13} strokeWidth={1.75} /> Line items
              </div>
              <Button
                type="button"
                onClick={addItem}
                size="sm"
                data-testid="quot-add-item"
                className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5 rounded-md h-8"
              >
                <Plus size={13} /> Add item
              </Button>
            </div>
            <div className="rounded-md overflow-hidden border bg-white" style={{ borderColor: "var(--border-warm)" }}>
              <table className="w-full text-sm">
                <thead style={{ background: "var(--surface-alt)" }}>
                  <tr>
                    <th className="text-left px-3 py-2 label-caps" style={{ fontSize: 10 }}>Product</th>
                    <th className="text-left px-3 py-2 label-caps" style={{ fontSize: 10 }}>Description</th>
                    <th className="text-right px-3 py-2 label-caps" style={{ fontSize: 10, width: 80 }}>Qty</th>
                    <th className="text-right px-3 py-2 label-caps" style={{ fontSize: 10, width: 120 }}>Rate ₹</th>
                    <th className="text-right px-3 py-2 label-caps" style={{ fontSize: 10, width: 130 }}>Amount</th>
                    <th className="px-2 py-2" style={{ width: 32 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {form.items.map((it, idx) => (
                    <tr key={it.id || idx} className="border-t" style={{ borderColor: "var(--border-warm)" }}
                        data-testid={`quot-item-${idx}`}>
                      <td className="px-2 py-1.5">
                        <Input
                          value={it.product_name}
                          onChange={(e) => updateItem(idx, { product_name: e.target.value })}
                          data-testid={`quot-item-name-${idx}`}
                          placeholder="e.g. Trophy TL — Amber Glass"
                          className="bg-white border-[var(--border-warm)] h-9"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <Input
                          value={it.description || ""}
                          onChange={(e) => updateItem(idx, { description: e.target.value })}
                          placeholder="Optional…"
                          className="bg-white border-[var(--border-warm)] h-9"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <Input
                          type="number" step="0.01"
                          value={it.qty === 0 ? "" : it.qty}
                          placeholder="0"
                          onChange={(e) => updateItem(idx, { qty: parseFloat(e.target.value) || 0 })}
                          data-testid={`quot-item-qty-${idx}`}
                          className="bg-white border-[var(--border-warm)] h-9 num text-right"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <Input
                          type="number" step="0.01"
                          value={it.rate === 0 ? "" : it.rate}
                          placeholder="0"
                          onChange={(e) => updateItem(idx, { rate: parseFloat(e.target.value) || 0 })}
                          data-testid={`quot-item-rate-${idx}`}
                          className="bg-white border-[var(--border-warm)] h-9 num text-right"
                        />
                      </td>
                      <td className="px-3 py-1.5 num text-right font-medium">
                        {fmtINR((Number(it.qty) || 0) * (Number(it.rate) || 0))}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        {form.items.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeItem(idx)}
                            data-testid={`quot-item-remove-${idx}`}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)]"
                          >
                            <Trash2 size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* TAX / FREIGHT + SUMMARY */}
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card-warm p-5">
              <div className="label-caps mb-3">Tax & freight</div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="text-[10px] label-caps">GST rate</Label>
                  <Select
                    value={String(form.gst_rate)}
                    onValueChange={(v) => update("gst_rate", parseFloat(v))}
                  >
                    <SelectTrigger data-testid="quot-gst" className="mt-1.5 bg-white border-[var(--border-warm)]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GST_RATES.map((r) => (
                        <SelectItem key={r} value={String(r)}>{r}%</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-[10px] label-caps">Freight</Label>
                  <Select
                    value={form.freight_type}
                    onValueChange={(v) => update("freight_type", v)}
                  >
                    <SelectTrigger data-testid="quot-freight-type" className="mt-1.5 bg-white border-[var(--border-warm)]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="extra">Extra (actuals)</SelectItem>
                      <SelectItem value="included">Included in rates</SelectItem>
                      <SelectItem value="none">None</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-[10px] label-caps">Freight amount</Label>
                  <div className="relative mt-1.5">
                    <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs" style={{ color: "var(--muted)" }}>₹</span>
                    <Input
                      type="number" step="0.01"
                      value={form.freight_amount === 0 ? "" : form.freight_amount}
                      placeholder="0"
                      disabled={form.freight_type !== "extra"}
                      onChange={(e) => update("freight_amount", parseFloat(e.target.value) || 0)}
                      data-testid="quot-freight-amt"
                      className="pl-6 bg-white border-[var(--border-warm)] num text-right"
                    />
                  </div>
                </div>
              </div>
              <div className="mt-4">
                <Label className="text-[10px] label-caps">Notes (internal)</Label>
                <Textarea
                  rows={2}
                  value={form.notes}
                  onChange={(e) => update("notes", e.target.value)}
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
              <div className="mt-3">
                <Label className="text-[10px] label-caps">Terms (shown on the quotation)</Label>
                <Textarea
                  rows={3}
                  value={form.terms}
                  onChange={(e) => update("terms", e.target.value)}
                  className="mt-1.5 bg-white border-[var(--border-warm)]"
                />
              </div>
            </div>

            <div className="rounded-md p-5" style={{ background: "var(--surface-alt)", border: "1px solid var(--border-warm)" }}>
              <div className="label-caps mb-4">Live summary</div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span style={{ color: "var(--muted)" }}>Subtotal</span>
                  <span className="num" data-testid="quot-subtotal">{fmtINR(totals.subtotal)}</span>
                </div>
                {form.freight_type === "extra" && (
                  <div className="flex justify-between">
                    <span style={{ color: "var(--muted)" }}>Freight</span>
                    <span className="num">{fmtINR(totals.freight)}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span style={{ color: "var(--muted)" }}>Taxable value</span>
                  <span className="num">{fmtINR(totals.taxable)}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: "var(--muted)" }}>GST @ {form.gst_rate}%</span>
                  <span className="num" data-testid="quot-tax">{fmtINR(totals.tax)}</span>
                </div>
                <div className="pt-3 mt-2 border-t flex justify-between items-center"
                     style={{ borderColor: "var(--border-warm)" }}>
                  <span className="label-caps">Total</span>
                  <span className="serif text-3xl num" style={{ color: "var(--terracotta)" }}
                        data-testid="quot-total">
                    {fmtINR(totals.total)}
                  </span>
                </div>
              </div>
            </div>
          </section>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              className="border-[var(--border-warm)]"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={saving}
              data-testid="quot-save-btn"
              className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white"
            >
              {saving ? "Saving…" : (quotation ? "Update quotation" : "Save quotation")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
