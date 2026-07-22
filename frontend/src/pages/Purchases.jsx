import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "../components/ui/select";
import { Plus, Pencil, Trash2, ShoppingBag, Search, Trash, AlertTriangle, ExternalLink } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "../components/ui/dialog";
import { toast } from "sonner";

const PAY_STYLE = {
  Unpaid:  { bg: "rgba(197,91,67,0.14)", fg: "#8a3b26" },
  Partial: { bg: "rgba(212,163,115,0.24)", fg: "#8a5a2c" },
  Paid:    { bg: "rgba(58,90,64,0.18)",   fg: "#2e4d32" },
};

const emptyItem = () => ({
  category: "", description: "", qty: 1, rate: 0, amount: 0,
});
const emptyPurchase = () => ({
  vendor_name: "",
  purchase_date: new Date().toISOString().substring(0, 10),
  invoice_no: "",
  items: [emptyItem()],
  freight: 0,
  other_charges: 0,
  tax_applicable: false,
  tax_type: "GST",
  tax_percent: 18,
  tax_amount: 0,
  tax_amount_manual: false,
  notes: "",
  payment_status: "Unpaid",
});

export default function Purchases() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendors, setVendors] = useState([]);
  const [parties, setParties] = useState([]);     // canonical vendor parties (id ↔ name)
  const [meta, setMeta] = useState({});
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyPurchase());

  const load = () => {
    setLoading(true);
    const params = {};
    if (search) params.vendor_name = search;
    if (status !== "all") params.payment_status = status;
    api.get("/purchases", { params })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [status]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);
  useEffect(() => {
    api.get("/vendors").then((r) => setVendors(r.data));
    api.get("/meta").then((r) => setMeta(r.data));
    // Canonical vendor parties — used to (a) resolve current display names
    // by vendor_party_id and (b) navigate to the vendor's Party Ledger via
    // the stable party id. Financial linkage keys off vendor_party_id;
    // vendor_name is denormalised for display only.
    api.get("/party-ledger-v2/parties", { params: { type: "vendor" } })
      .then((r) => {
        // Endpoint shape: { count, parties: [...] }.
        const list = Array.isArray(r.data?.parties) ? r.data.parties
                   : (Array.isArray(r.data) ? r.data : []);
        setParties(list);
      })
      .catch(() => setParties([]));
  }, []);

  // Fast lookup: party_id → canonical current name (post-rename safe).
  const partyById = useMemo(() => {
    const m = {};
    (parties || []).forEach((p) => { m[p.id] = p; });
    return m;
  }, [parties]);

  // Open the Party Ledger for a given canonical vendor party id.
  const openVendorLedger = (partyId) => {
    if (!partyId) return;
    navigate(`/party-ledger?party_id=${encodeURIComponent(partyId)}`);
  };

  const totals = useMemo(() => rows.reduce(
    (a, p) => ({
      invoice: a.invoice + (p.invoice_total || 0),
      paid: a.paid + (p.total_paid || 0),
      outstanding: a.outstanding + (p.outstanding_balance || 0),
    }),
    { invoice: 0, paid: 0, outstanding: 0 },
  ), [rows]);

  // ---- form helpers ----
  const openNew = () => {
    setEditing(null);
    setForm(emptyPurchase());
    setDialogOpen(true);
  };
  const openEdit = (p) => {
    setEditing(p);
    setForm({
      ...emptyPurchase(),
      ...p,
      purchase_date: p.purchase_date ? p.purchase_date.substring(0, 10) : "",
      items: (p.items && p.items.length) ? p.items : [emptyItem()],
    });
    setDialogOpen(true);
  };

  const updateItem = (idx, patch) => {
    setForm((f) => {
      const items = f.items.map((it, i) => {
        if (i !== idx) return it;
        const next = { ...it, ...patch };
        if ("qty" in patch || "rate" in patch) {
          next.amount = (Number(next.qty) || 0) * (Number(next.rate) || 0);
        }
        return next;
      });
      return { ...f, items };
    });
  };
  const addItem = () => setForm((f) => ({ ...f, items: [...f.items, emptyItem()] }));
  const removeItem = (idx) => setForm((f) => ({ ...f, items: f.items.filter((_, i) => i !== idx) }));

  const summary = useMemo(() => {
    const subtotal = form.items.reduce(
      (s, it) => s + ((Number(it.qty) || 0) * (Number(it.rate) || 0)),
      0,
    );
    const base = subtotal + Number(form.freight || 0) + Number(form.other_charges || 0);
    let tax = 0;
    if (form.tax_applicable) {
      tax = form.tax_amount_manual
        ? Number(form.tax_amount || 0)
        : Math.round(base * Number(form.tax_percent || 0)) / 100;
    }
    return { subtotal, base, tax, invoice: base + tax };
  }, [form]);

  const save = async (e) => {
    e.preventDefault();
    if (!form.vendor_name.trim()) return toast.error("Please select or enter a vendor.");
    if (form.items.filter((i) => i.description.trim()).length === 0)
      return toast.error("Add at least one line item.");
    try {
      const payload = {
        ...form,
        items: form.items.filter((i) => i.description.trim()),
        purchase_date: form.purchase_date ? new Date(form.purchase_date).toISOString() : null,
      };
      if (editing?.id) {
        await api.put(`/purchases/${editing.id}`, payload);
        toast.success("Purchase updated");
      } else {
        await api.post("/purchases", payload);
        toast.success("Purchase added");
      }
      setDialogOpen(false);
      load();
    } catch (err) {
      console.error(err);
      toast.error("Failed to save purchase");
    }
  };

  const remove = async (p) => {
    if (!confirm(`Delete this purchase (${p.invoice_no || "no invoice"})? This will also detach any payment allocations.`)) return;
    try {
      await api.delete(`/purchases/${p.id}`);
      toast.success("Purchase deleted");
      load();
    } catch { toast.error("Failed to delete"); }
  };

  return (
    <div data-testid="purchases-page">
      <PageHeader
        eyebrow="Accounts payable"
        title="Purchase bills"
        subtitle="Vendor bills, GST and outstanding payables — the buy-side counterpart to Orders."
        actions={
          <Button onClick={openNew} data-testid="add-purchase-btn"
                  className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md">
            <Plus size={16} /> New purchase
          </Button>
        }
      />

      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input value={search} data-testid="filter-vendor"
                 onChange={(e) => setSearch(e.target.value)} placeholder="Search vendor…"
                 className="pl-9 bg-white border-[var(--border-warm)]" />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger data-testid="filter-status" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Payment status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="Unpaid">Unpaid</SelectItem>
            <SelectItem value="Partial">Partial</SelectItem>
            <SelectItem value="Paid">Paid</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Bills</div>
          <div className="serif text-2xl num mt-1" data-testid="purch-count">{rows.length}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Invoice value</div>
          <div className="serif text-2xl num mt-1" data-testid="purch-invoice">{fmtINR(totals.invoice)}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Paid</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--sage)" }}
               data-testid="purch-paid">
            {fmtINR(totals.paid)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Outstanding</div>
          <div className="serif text-2xl num mt-1"
               style={{ color: totals.outstanding > 0.5 ? "var(--terracotta)" : "var(--sage)" }}
               data-testid="purch-outstanding">
            {fmtINR(totals.outstanding)}
          </div>
        </div>
      </div>

      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="ledger-table w-full min-w-[900px]" data-testid="purchases-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Vendor</th>
                <th>Bill no</th>
                <th className="num">Items</th>
                <th className="num">Invoice</th>
                <th className="num">Paid</th>
                <th className="num">Outstanding</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={9} className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-sm" style={{ color: "var(--muted)" }}>
                    <ShoppingBag size={22} className="inline-block mb-2" strokeWidth={1.5} />
                    <div>No purchase bills yet. Click "New purchase" to record one.</div>
                  </td>
                </tr>
              )}
              {rows.map((p) => {
                const s = PAY_STYLE[p.payment_status] || PAY_STYLE.Unpaid;
                // Canonical vendor party — resolve current display name
                // through party_id so vendor RENAMES are honoured in the
                // table even before the purchase row is re-saved.
                const party = p.vendor_party_id ? partyById[p.vendor_party_id] : null;
                const displayName = party?.name || p.vendor_name;
                const hasLinkage = !!p.vendor_party_id;
                return (
                  <tr key={p.id} data-testid={`purchase-row-${p.id}`}>
                    <td className="whitespace-nowrap">{fmtDate(p.purchase_date)}</td>
                    <td className="font-medium">
                      {hasLinkage ? (
                        <button
                          type="button"
                          onClick={() => openVendorLedger(p.vendor_party_id)}
                          data-testid={`vendor-link-${p.id}`}
                          className="inline-flex items-center gap-1 hover:underline focus:outline-none focus:underline"
                          style={{ color: "var(--foreground)" }}
                          title={`Open ${displayName} in Party Ledger`}
                        >
                          {displayName}
                          <ExternalLink size={11} strokeWidth={1.75}
                                        style={{ color: "var(--muted)" }} />
                        </button>
                      ) : (
                        <span className="inline-flex items-center gap-1"
                              data-testid={`vendor-unlinked-${p.id}`}
                              title="This purchase is not linked to a canonical vendor party. Edit and save to link it.">
                          {displayName}
                          <AlertTriangle size={12} strokeWidth={1.75}
                                         style={{ color: "var(--terracotta)" }} />
                        </span>
                      )}
                    </td>
                    <td className="num" style={{ color: "var(--muted)" }}>{p.invoice_no || "—"}</td>
                    <td className="num">{(p.items || []).length}</td>
                    <td className="num font-medium">{fmtINR(p.invoice_total)}</td>
                    <td className="num" style={{ color: "var(--sage)" }}>{fmtINR(p.total_paid)}</td>
                    <td className="num"
                        style={{ color: (p.outstanding_balance || 0) > 0.5 ? "var(--terracotta)" : "var(--muted)" }}>
                      {fmtINR(p.outstanding_balance)}
                    </td>
                    <td>
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium"
                            style={{ background: s.bg, color: s.fg }}>
                        {p.payment_status}
                      </span>
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <button onClick={() => openEdit(p)} data-testid={`edit-purchase-${p.id}`}
                              className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                        <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                      </button>
                      <button onClick={() => remove(p)} data-testid={`delete-purchase-${p.id}`}
                              className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1">
                        <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {rows.length > 0 && !loading && (
              <tfoot>
                <tr style={{ background: "var(--surface-alt)", fontWeight: 600, borderTop: "2px solid var(--border-warm)" }}
                    data-testid="purchases-footer-totals">
                  <td colSpan={4} className="py-3 px-3 label-caps" style={{ fontSize: 11 }}>
                    Totals · {rows.length} bills
                  </td>
                  <td className="num py-3">{fmtINR(totals.invoice)}</td>
                  <td className="num py-3" style={{ color: "var(--sage)" }}>{fmtINR(totals.paid)}</td>
                  <td className="num py-3"
                      style={{ color: totals.outstanding > 0.5 ? "var(--terracotta)" : "var(--sage)" }}>
                    {fmtINR(totals.outstanding)}
                  </td>
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[92vh] overflow-y-auto" data-testid="purchase-dialog">
          <DialogHeader>
            <DialogTitle className="serif text-3xl">{editing ? "Edit purchase" : "New purchase"}</DialogTitle>
            <DialogDescription className="text-xs">
              Record a vendor bill. GST is optional and never affects order profit — this is purely a payable ledger.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-6 mt-2">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="md:col-span-2">
                <Label className="text-[11px] label-caps">Vendor*</Label>
                <Input list="vendor-list" value={form.vendor_name}
                       data-testid="p-vendor"
                       onChange={(e) => setForm({ ...form, vendor_name: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]"
                       placeholder="Type or select…" required />
                {/* Canonical vendor parties first (stable party_id linkage);
                    fall back to the legacy vendors master for any names not
                    yet migrated. Free text is still allowed — the backend
                    calls get_or_create_vendor_party on save to quick-create
                    a canonical party for new names. */}
                <datalist id="vendor-list">
                  {parties.map((v) => <option key={`p-${v.id}`} value={v.name} />)}
                  {vendors
                    .filter((v) => !parties.some((p) => p.name === v.name))
                    .map((v) => <option key={`v-${v.id}`} value={v.name} />)}
                </datalist>
                {editing && editing.vendor_party_id ? (
                  <button type="button"
                          onClick={() => { setDialogOpen(false); openVendorLedger(editing.vendor_party_id); }}
                          className="text-[10px] mt-1 hover:underline inline-flex items-center gap-1"
                          data-testid="p-vendor-open-ledger"
                          style={{ color: "var(--terracotta)" }}>
                    <ExternalLink size={10} strokeWidth={1.75} />
                    Open in Party Ledger
                  </button>
                ) : null}
              </div>
              <div>
                <Label className="text-[11px] label-caps">Bill date</Label>
                <Input type="date" data-testid="p-date" value={form.purchase_date}
                       onChange={(e) => setForm({ ...form, purchase_date: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[11px] label-caps">Bill / Invoice no</Label>
                <Input data-testid="p-invoice-no" value={form.invoice_no}
                       onChange={(e) => setForm({ ...form, invoice_no: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
            </div>

            {/* Line items */}
            <div className="card-warm p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="label-caps">Line items</div>
                <Button type="button" size="sm" onClick={addItem} data-testid="add-item-btn"
                        className="bg-white border h-8 text-xs gap-1.5"
                        style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                  <Plus size={12} /> Add item
                </Button>
              </div>
              <div className="overflow-x-auto">
                <table className="ledger-table w-full min-w-[720px]">
                  <thead>
                    <tr>
                      <th style={{ width: "40%" }}>Description</th>
                      <th>Category</th>
                      <th className="num">Qty</th>
                      <th className="num">Rate</th>
                      <th className="num">Amount</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.items.map((it, idx) => (
                      <tr key={idx}>
                        <td>
                          <Input value={it.description} data-testid={`item-desc-${idx}`}
                                 onChange={(e) => updateItem(idx, { description: e.target.value })}
                                 className="bg-white border-[var(--border-warm)]" />
                        </td>
                        <td>
                          <Input value={it.category} data-testid={`item-cat-${idx}`}
                                 onChange={(e) => updateItem(idx, { category: e.target.value })}
                                 placeholder="Optional"
                                 className="bg-white border-[var(--border-warm)]" />
                        </td>
                        <td>
                          <Input type="number" step="0.01" value={it.qty}
                                 data-testid={`item-qty-${idx}`}
                                 onChange={(e) => updateItem(idx, { qty: parseFloat(e.target.value) || 0 })}
                                 className="bg-white border-[var(--border-warm)] num" />
                        </td>
                        <td>
                          <Input type="number" step="0.01" value={it.rate}
                                 data-testid={`item-rate-${idx}`}
                                 onChange={(e) => updateItem(idx, { rate: parseFloat(e.target.value) || 0 })}
                                 className="bg-white border-[var(--border-warm)] num" />
                        </td>
                        <td className="num font-medium">
                          {fmtINR((Number(it.qty) || 0) * (Number(it.rate) || 0))}
                        </td>
                        <td>
                          {form.items.length > 1 && (
                            <button type="button" onClick={() => removeItem(idx)}
                                    data-testid={`item-remove-${idx}`}
                                    className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                              <Trash size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Charges + tax */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="card-warm p-4">
                <div className="label-caps mb-3">Charges</div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-[11px] label-caps">Freight</Label>
                    <Input type="number" step="0.01" value={form.freight}
                           data-testid="p-freight"
                           onChange={(e) => setForm({ ...form, freight: parseFloat(e.target.value) || 0 })}
                           className="mt-1 bg-white border-[var(--border-warm)] num" />
                  </div>
                  <div>
                    <Label className="text-[11px] label-caps">Other charges</Label>
                    <Input type="number" step="0.01" value={form.other_charges}
                           data-testid="p-other"
                           onChange={(e) => setForm({ ...form, other_charges: parseFloat(e.target.value) || 0 })}
                           className="mt-1 bg-white border-[var(--border-warm)] num" />
                  </div>
                </div>
              </div>
              <div className="card-warm p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="label-caps">Tax (input GST)</div>
                  <label className="flex items-center gap-2 text-xs">
                    <input type="checkbox" checked={!!form.tax_applicable}
                           data-testid="p-tax-toggle"
                           onChange={(e) => setForm({ ...form, tax_applicable: e.target.checked })} />
                    Applicable
                  </label>
                </div>
                {form.tax_applicable && (
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label className="text-[11px] label-caps">Type</Label>
                      <Select value={form.tax_type}
                              onValueChange={(v) => setForm({ ...form, tax_type: v })}>
                        <SelectTrigger data-testid="p-tax-type" className="mt-1 bg-white border-[var(--border-warm)]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(meta.tax_types || ["GST", "IGST", "CGST_SGST", "None"]).map((t) =>
                            <SelectItem key={t} value={t}>{t}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label className="text-[11px] label-caps">Rate %</Label>
                      <Input type="number" step="0.01" value={form.tax_percent}
                             data-testid="p-tax-percent"
                             onChange={(e) => setForm({
                               ...form, tax_percent: parseFloat(e.target.value) || 0,
                               tax_amount_manual: false,
                             })}
                             className="mt-1 bg-white border-[var(--border-warm)] num" />
                    </div>
                  </div>
                )}
                {form.tax_applicable && (
                  <div className="mt-3 text-xs" style={{ color: "var(--muted)" }}>
                    Tax amount: <span className="num" style={{ color: "var(--ink)" }}>
                      {fmtINR(summary.tax)}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div className="card-warm p-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <div className="label-caps">Subtotal</div>
                  <div className="serif text-lg num mt-1" data-testid="p-sum-subtotal">{fmtINR(summary.subtotal)}</div>
                </div>
                <div>
                  <div className="label-caps">Freight + Other</div>
                  <div className="serif text-lg num mt-1">
                    {fmtINR(Number(form.freight || 0) + Number(form.other_charges || 0))}
                  </div>
                </div>
                <div>
                  <div className="label-caps">Tax</div>
                  <div className="serif text-lg num mt-1">{fmtINR(summary.tax)}</div>
                </div>
                <div>
                  <div className="label-caps">Invoice total</div>
                  <div className="serif text-lg num mt-1" style={{ color: "var(--terracotta)" }}
                       data-testid="p-sum-invoice">
                    {fmtINR(summary.invoice)}
                  </div>
                </div>
              </div>
            </div>

            <div>
              <Label className="text-[11px] label-caps">Notes</Label>
              <Textarea data-testid="p-notes" value={form.notes} rows={2}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })}
                        className="mt-1 bg-white border-[var(--border-warm)]" />
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}
                      className="border-[var(--border-warm)]">Cancel</Button>
              <Button type="submit" data-testid="p-save-btn"
                      className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
                {editing ? "Update purchase" : "Add purchase"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
