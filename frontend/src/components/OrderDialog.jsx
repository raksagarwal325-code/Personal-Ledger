import { useState, useEffect, useMemo, useCallback } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Switch } from "./ui/switch";
import { Textarea } from "./ui/textarea";
import { api, fmtINR, fmtDate } from "../lib/api";
import { toast } from "sonner";
import { Trash2, Plus, Package, Truck, Receipt, RotateCcw, Banknote, Pencil, ChevronDown, ChevronRight, Info, Landmark, Users, Building2, Coins, Clock } from "lucide-react";
import ShipmentDialog from "./ShipmentDialog";
import CustomerPaymentDialog from "./CustomerPaymentDialog";
import PurchaseSourcesEditor from "./PurchaseSourcesEditor";

const emptyItem = () => ({
  id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
  main_category: "Chandelier",
  sub_category: "",
  product_name: "",
  qty: 0,
  rate: 0,
  product_sales: 0,
  factory_complete: 0,
  factory_glass: 0,
  factory_fitting: 0,
  outside_complete: 0,
  outside_glass: 0,
  outside_fitting: 0,
  // New unified purchases list — starts with an empty Factory row so users see
  // the familiar shape and can just type amounts. Additional rows are added
  // via "+ Add purchase source" in the editor.
  purchase_sources: [{
    id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
    supplier_id: "factory",
    supplier_name: "Factory",
    complete: 0, glass: 0, fitting: 0,
  }],
});

const emptyAdj = () => ({
  id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
  description: "",
  amount: 0,
});

const REVENUE_SUGGESTIONS = [
  "Loose Item Sale", "Discount Reversal", "Installation Charges",
  "Miscellaneous Income", "Custom Work", "Round-off",
];
const EXPENSE_SUGGESTIONS = [
  "Discount Given", "Local Transport", "Loading Charges",
  "Helper Charges", "Labour", "Installation Cost",
  "Miscellaneous Expense", "Round-off",
];

const emptyOrder = () => ({
  client_name: "",
  order_date: new Date().toISOString().substring(0, 10),
  shipped_date: "",
  payment_status: "Unpaid",
  notes: "",
  items: [emptyItem()],
  shipments: [],
  boxes_used: 0,
  cost_per_box: 0,
  packing_cost: 0,
  // Bug fix (2026-07-22) · Packing vendor linkage — when packing_cost > 0
  // and packer_name is set, the backend auto-generates a canonical
  // Purchase under this vendor (source_type='order_packing_purchase').
  // Kept distinct from `transporter` (per-shipment freight vendor).
  packer_name: "",
  boxes_shipped: 0,
  freight_charged: 0,
  freight_paid: 0,
  transporter: "",
  lr_number: "",
  packing_recovery: 0,
  other_revenue: [],
  other_expense: [],
  order_payments: [],
  tax_applicable: false,
  tax_type: "None",
  tax_percent: 0,
  tax_amount: 0,
  tax_amount_manual: false,
  packing_cost_manual: false,
});

const emptyPayment = (invoiceTotal) => ({
  id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
  amount: invoiceTotal || 0,
  mode: "UPI",
  account_id: "",
  account_name: "",
  date: new Date().toISOString().substring(0, 10),
  reference: "",
  remarks: "",
});

const Num = ({ label, value, onChange, testId, hint, prefix, suffix }) => (
  <div>
    <Label className="text-[10px] label-caps">{label}</Label>
    <div className="relative mt-1.5">
      {prefix && (
        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs"
              style={{ color: "var(--muted)" }}>{prefix}</span>
      )}
      <Input
        type="number"
        step="0.01"
        value={value === 0 ? "" : value}
        placeholder="0"
        onChange={(e) => onChange(e.target.value === "" ? 0 : parseFloat(e.target.value) || 0)}
        data-testid={testId}
        className={`bg-white border-[var(--border-warm)] ${prefix ? "pl-6" : ""} ${suffix ? "pr-8" : ""}`}
      />
      {suffix && (
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs"
              style={{ color: "var(--muted)" }}>{suffix}</span>
      )}
    </div>
    {hint && <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>{hint}</div>}
  </div>
);

function AdjustmentsCard({ title, subtitle, testId, tone, rows, suggestions, onAdd, onUpdate, onRemove, total }) {
  const dlId = `dl-${testId}`;
  return (
    <div className="card-warm p-5" data-testid={testId}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="label-caps" style={{ color: tone }}>{title}</div>
          <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>{subtitle}</div>
        </div>
        <Button type="button" onClick={onAdd} size="sm"
                data-testid={`${testId}-add`}
                className="bg-white border h-8 text-xs gap-1.5"
                style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
          <Plus size={13} /> Add
        </Button>
      </div>

      <datalist id={dlId}>
        {suggestions.map((s) => <option key={s} value={s} />)}
      </datalist>

      {rows.length === 0 ? (
        <div className="text-xs py-4 text-center" style={{ color: "var(--muted)" }}>
          No entries yet. Click Add to include one.
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((r, idx) => (
            <div key={r.id || idx} className="flex items-center gap-2"
                 data-testid={`${testId}-row-${idx}`}>
              <Input value={r.description} placeholder="Description"
                     list={dlId}
                     onChange={(e) => onUpdate(idx, { description: e.target.value })}
                     data-testid={`${testId}-desc-${idx}`}
                     className="flex-1 bg-white border-[var(--border-warm)] h-9" />
              <div className="relative w-32">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs"
                      style={{ color: "var(--muted)" }}>₹</span>
                <Input type="number" step="0.01"
                       value={r.amount === 0 ? "" : r.amount}
                       placeholder="0"
                       onChange={(e) => onUpdate(idx, { amount: parseFloat(e.target.value) || 0 })}
                       data-testid={`${testId}-amt-${idx}`}
                       className="pl-6 bg-white border-[var(--border-warm)] h-9 num text-right" />
              </div>
              <button type="button" onClick={() => onRemove(idx)}
                      data-testid={`${testId}-remove-${idx}`}
                      className="p-2 rounded hover:bg-white transition-colors">
                <Trash2 size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="mt-4 pt-3 border-t flex items-center justify-between"
           style={{ borderColor: "var(--border-warm)" }}>
        <div className="text-xs" style={{ color: "var(--muted)" }}>Total</div>
        <div className="serif text-xl num" style={{ color: tone }}
             data-testid={`${testId}-total`}>{fmtINR(total)}</div>
      </div>
    </div>
  );
}

export default function OrderDialog({ open, onOpenChange, order, onSaved }) {
  const [form, setForm] = useState(emptyOrder());
  const [saving, setSaving] = useState(false);
  // When user opens the dialog to CREATE a new order and then clicks "Add shipment" or "Record payment"
  // BEFORE hitting the main Save button, we auto-save the draft order and keep this internal reference
  // so subsequent shipment/payment dialogs can be attached to a real order id.
  const [savedOrder, setSavedOrder] = useState(null);
  const effectiveOrder = order || savedOrder;
  const [meta, setMeta] = useState({
    main_categories: [],
    sub_categories_by_main: {},
    products_by_sub: {},
    transporters: [],
    payment_statuses: ["Unpaid", "Partial", "Paid"],
    tax_types: ["None", "GST", "IGST", "CGST_SGST"],
  });

  useEffect(() => {
    api.get("/meta").then((r) => setMeta((m) => ({ ...m, ...r.data })));
  }, []);

  // Bug fix (2026-07-22) · Canonical vendor selectors for Packer & Transporter.
  // Loaded from Party Ledger v2 (canonical) with fallback to legacy /vendors
  // for anything not yet migrated. Free text is still allowed — the backend
  // calls get_or_create_vendor_party on save so a NEW name quick-creates a
  // canonical party. This gives us "canonical selector + quick-create".
  const [vendorParties, setVendorParties] = useState([]);
  useEffect(() => {
    Promise.all([
      api.get("/party-ledger-v2/parties", { params: { type: "vendor" } })
        .catch(() => ({ data: { parties: [] } })),
      api.get("/vendors").catch(() => ({ data: [] })),
    ]).then(([partyRes, vendorRes]) => {
      // Party Ledger v2 returns { count, parties: [...] }; be defensive.
      const parties = Array.isArray(partyRes.data?.parties) ? partyRes.data.parties
                    : (Array.isArray(partyRes.data) ? partyRes.data : []);
      const legacy = Array.isArray(vendorRes.data) ? vendorRes.data : [];
      // dedupe by name, prefer canonical parties (they carry a stable id)
      const seen = new Set();
      const merged = [];
      parties.forEach((p) => {
        const key = (p.name || "").trim().toLowerCase();
        if (key && !seen.has(key)) { seen.add(key); merged.push({ id: p.id, name: p.name }); }
      });
      legacy.forEach((v) => {
        const key = (v.name || "").trim().toLowerCase();
        if (key && !seen.has(key)) { seen.add(key); merged.push({ id: v.id, name: v.name }); }
      });
      setVendorParties(merged);
    });
  }, []);

  useEffect(() => {
    if (order) {
      setForm({
        ...emptyOrder(),
        ...order,
        order_date: order.order_date ? order.order_date.substring(0, 10) : "",
        shipped_date: order.shipped_date ? order.shipped_date.substring(0, 10) : "",
        items: (order.items && order.items.length) ? order.items : [emptyItem()],
        shipments: order.shipments || [],
        other_revenue: order.other_revenue || [],
        other_expense: order.other_expense || [],
        order_payments: order.order_payments || [],
        tax_amount_manual: !!order.tax_amount_manual,
        packing_cost_manual: !!order.packing_cost_manual,
      });
      setSavedOrder(null);
    } else {
      setForm(emptyOrder());
      setSavedOrder(null);
    }
  }, [order, open]);

  // Nested shipment dialog + inline shipments section state
  const [shipmentDialog, setShipmentDialog] = useState({ open: false, shipment: null });
  const [shipmentsExpanded, setShipmentsExpanded] = useState(true);

  const refreshOrderShipments = useCallback(async () => {
    const oid = effectiveOrder?.id;
    if (!oid) return;
    try {
      const r = await api.get(`/orders/${oid}`);
      const fresh = r.data;
      setForm((f) => ({
        ...f,
        shipments: fresh.shipments || [],
        // sync derived fields so summary stays accurate without losing user edits above
        status: fresh.status || f.status,
        shipped_qty_total: fresh.shipped_qty_total,
        ordered_qty_total: fresh.ordered_qty_total,
        last_shipped_date: fresh.last_shipped_date,
        // keep items in sync (qty_shipped stamped on items)
        items: (fresh.items && fresh.items.length) ? fresh.items : f.items,
      }));
    } catch (e) { /* silent */ }
  }, [effectiveOrder?.id]);

  const openNewShipment = async () => {
    const oid = await ensureOrderSaved();
    if (!oid) return;
    setShipmentDialog({ open: true, shipment: null });
  };
  const openEditShipment = (sh) => setShipmentDialog({ open: true, shipment: sh });
  const deleteShipment = async (sh) => {
    const oid = effectiveOrder?.id;
    if (!oid) return;
    if (!confirm("Delete this shipment? Revenue and profit will be recalculated.")) return;
    try {
      await api.delete(`/orders/${oid}/shipments/${sh.id}`);
      toast.success("Shipment deleted");
      await refreshOrderShipments();
    } catch (err) {
      toast.error("Failed to delete shipment");
    }
  };

  // Payments received for this order (from CustomerPayment allocations)
  const [orderPayments, setOrderPayments] = useState({ payments: [], total_received: 0, outstanding: 0, count: 0 });
  const [paymentsExpanded, setPaymentsExpanded] = useState(true);
  const [paymentDialog, setPaymentDialog] = useState({ open: false, payment: null });

  const refreshOrderPayments = useCallback(async () => {
    const oid = effectiveOrder?.id;
    if (!oid) return;
    try {
      const r = await api.get(`/orders/${oid}/payments`);
      setOrderPayments(r.data);
    } catch (e) { /* silent */ }
  }, [effectiveOrder?.id]);

  // Order timeline — history of events (created, shipments, payments)
  const [timeline, setTimeline] = useState([]);
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const refreshTimeline = useCallback(async () => {
    const oid = effectiveOrder?.id;
    if (!oid) return;
    try {
      const r = await api.get(`/orders/${oid}/timeline`);
      setTimeline(r.data.events || []);
    } catch (e) { /* silent */ }
  }, [effectiveOrder?.id]);

  useEffect(() => {
    if (open && effectiveOrder?.id) { refreshOrderPayments(); refreshTimeline(); }
    if (!open) {
      setOrderPayments({ payments: [], total_received: 0, outstanding: 0, count: 0, customer_advance_available: 0 });
      setTimeline([]);
    }
  }, [open, effectiveOrder?.id, refreshOrderPayments, refreshTimeline]);

  const allocateAdvance = async () => {
    const oid = effectiveOrder?.id;
    if (!oid) return;
    const available = Number(orderPayments.customer_advance_available || 0);
    const outstanding = Number(orderPayments.outstanding || 0);
    if (available <= 0.5 || outstanding <= 0.5) return;
    try {
      await api.post(`/orders/${oid}/allocate-advance`);
      toast.success("Advance allocated to this order");
      await Promise.all([refreshOrderPayments(), refreshOrderShipments(), refreshTimeline()]);
      onSaved?.({ keepOpen: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not allocate advance");
    }
  };

  const openNewPayment = async () => {
    const oid = await ensureOrderSaved();
    if (!oid) return;
    // Prefill with this order's outstanding amount pre-allocated
    const outstanding = Math.max(0, Number(orderPayments.outstanding || 0));
    setPaymentDialog({
      open: true,
      payment: {
        id: null,
        customer_name: form.client_name || effectiveOrder?.client_name || "",
        date: new Date().toISOString().substring(0, 10),
        amount: outstanding,
        mode: "UPI",
        account_id: "",
        account_name: "",
        reference: "",
        remarks: "",
        allocations: outstanding > 0 ? [{ order_id: oid, amount: outstanding }] : [],
      },
    });
  };
  const openEditPayment = async (p) => {
    try {
      // Fetch the full payment (with all allocations)
      const r = await api.get(`/customer-payments/${p.payment_id}`);
      setPaymentDialog({ open: true, payment: r.data });
    } catch {
      toast.error("Could not load payment for edit");
    }
  };
  const deleteOrderPayment = async (p) => {
    if (!confirm("Delete this payment? Any allocations will be reversed on all affected orders.")) return;
    try {
      await api.delete(`/customer-payments/${p.payment_id}`);
      toast.success("Payment deleted");
      await Promise.all([refreshOrderPayments(), refreshOrderShipments()]);
    } catch {
      toast.error("Failed to delete payment");
    }
  };

  // Auto-calc packing cost = boxes × cost/box (only when user hasn't manually edited).
  // Also mirror packing "boxes used" into freight "boxes shipped" (until user overrides).
  useEffect(() => {
    setForm((f) => {
      const auto = (Number(f.boxes_used) || 0) * (Number(f.cost_per_box) || 0);
      const next = { ...f };
      if (!f.packing_cost_manual) next.packing_cost = auto;
      // Mirror packing boxes to freight boxes_shipped
      next.boxes_shipped = Number(f.boxes_used) || 0;
      return next;
    });
    // eslint-disable-next-line
  }, [form.boxes_used, form.cost_per_box]);

  const updateField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const updateItem = (idx, patch) => {
    setForm((f) => {
      const items = f.items.map((it, i) => {
        if (i !== idx) return it;
        const next = { ...it, ...patch };
        if ("qty" in patch || "rate" in patch) {
          next.product_sales = (Number(next.qty) || 0) * (Number(next.rate) || 0);
        }
        return next;
      });
      return { ...f, items };
    });
  };

  const addItem = () => setForm((f) => ({ ...f, items: [...f.items, emptyItem()] }));
  const removeItem = (idx) => setForm((f) => ({
    ...f,
    items: f.items.length === 1 ? f.items : f.items.filter((_, i) => i !== idx),
  }));

  // Other Revenue / Other Expense CRUD
  const addAdj = (key) => setForm((f) => ({ ...f, [key]: [...(f[key] || []), emptyAdj()] }));
  const updateAdj = (key, idx, patch) => setForm((f) => ({
    ...f,
    [key]: f[key].map((r, i) => (i === idx ? { ...r, ...patch } : r)),
  }));
  const removeAdj = (key, idx) => setForm((f) => ({
    ...f, [key]: f[key].filter((_, i) => i !== idx),
  }));

  // Order-payment CRUD
  const addPayment = (invoiceTotal) => setForm((f) => ({
    ...f, order_payments: [...(f.order_payments || []), emptyPayment(f.order_payments?.length === 0 ? invoiceTotal : 0)]
  }));
  const updatePayment = (idx, patch) => setForm((f) => ({
    ...f, order_payments: f.order_payments.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
  }));
  const removePayment = (idx) => setForm((f) => ({
    ...f, order_payments: f.order_payments.filter((_, i) => i !== idx),
  }));

  // Summary math (mirrors backend)
  const summary = useMemo(() => {
    const items = form.items || [];
    const product_sales_total = items.reduce((s, i) => s + (Number(i.product_sales) || 0), 0);

    // Prefer purchase_sources (post-refactor) for per-item cost breakdown.
    // Falls back to legacy factory_*/outside_* fields for orders that haven't
    // been re-saved yet.
    let factory_cost = 0, outside_cost = 0;
    for (const it of items) {
      const sources = it.purchase_sources || [];
      if (sources.length > 0) {
        for (const s of sources) {
          const rowSum = (Number(s.complete) || 0) + (Number(s.glass) || 0) + (Number(s.fitting) || 0);
          if (s.supplier_id === "factory") factory_cost += rowSum;
          else outside_cost += rowSum;
        }
      } else {
        factory_cost += (Number(it.factory_complete) || 0) + (Number(it.factory_glass) || 0) + (Number(it.factory_fitting) || 0);
        outside_cost += (Number(it.outside_complete) || 0) + (Number(it.outside_glass) || 0) + (Number(it.outside_fitting) || 0);
      }
    }

    const other_rev_total = (form.other_revenue || []).reduce((s, r) => s + (Number(r.amount) || 0), 0);
    const other_exp_total = (form.other_expense || []).reduce((s, r) => s + (Number(r.amount) || 0), 0);
    // Freight is captured per-shipment now — always compute from the shipments array
    // so the live summary matches what the backend will store.
    const ship_freight_charged = (form.shipments || []).reduce((s, sh) => s + (Number(sh.freight_charged) || 0), 0);
    const ship_freight_paid = (form.shipments || []).reduce((s, sh) => s + (Number(sh.freight_paid) || 0), 0);
    const revenue = product_sales_total
      + ship_freight_charged
      + Number(form.packing_recovery || 0)
      + other_rev_total;
    const cost = factory_cost + outside_cost + Number(form.packing_cost || 0) + ship_freight_paid + other_exp_total;
    // Tax base includes Other Revenue (already in revenue) and subtracts Other Expense
    // so the taxable amount reflects the true net revenue after these adjustments.
    const tax_base = Math.max(0, revenue - other_exp_total);
    const auto_tax = form.tax_applicable ? (tax_base * (Number(form.tax_percent) || 0) / 100) : 0;
    const tax_amount = form.tax_applicable
      ? (form.tax_amount_manual ? Number(form.tax_amount || 0) : auto_tax)
      : 0;
    const invoice = revenue + tax_amount;
    const profit = revenue - cost;
    const margin = revenue > 0 ? (profit / revenue) * 100 : 0;
    const received = (form.order_payments || []).reduce((s, p) => s + (Number(p.amount) || 0), 0);
    const outstanding = invoice - received;
    return { product_sales_total, factory_cost, outside_cost, other_rev_total, other_exp_total,
             revenue, cost, tax_amount, auto_tax, invoice, profit, margin, received, outstanding };
  }, [form]);

  // Auto-fill tax_amount when NOT in manual mode and formula inputs change
  useEffect(() => {
    if (!form.tax_applicable) return;
    if (form.tax_amount_manual) return;
    setForm((f) => (f.tax_amount === summary.auto_tax ? f : { ...f, tax_amount: summary.auto_tax }));
    // eslint-disable-next-line
  }, [summary.auto_tax, form.tax_applicable, form.tax_amount_manual]);

  // When user picks "Paid" and has no payments, auto-add one prefilled with invoice_total.
  // Uses functional setState + inside-check to avoid stale-state races with rapid Add clicks.
  useEffect(() => {
    if (form.payment_status !== "Paid") return;
    if (summary.invoice <= 0) return;
    setForm((f) => {
      if ((f.order_payments || []).length > 0) return f;
      return { ...f, order_payments: [emptyPayment(summary.invoice)] };
    });
    // eslint-disable-next-line
  }, [form.payment_status]);

  // Live-derived payment status based on actual received amount (customer-payment
  // allocations) vs invoice total. Kicks in as soon as at least one payment exists.
  useEffect(() => {
    const rec = Number(orderPayments.total_received || 0);
    const count = Number(orderPayments.count || 0);
    if (count === 0 && rec <= 0) return;
    const inv = Number(orderPayments.invoice_total || summary.invoice || 0);
    let s = "Unpaid";
    if (rec <= 0) s = "Unpaid";
    else if (rec + 0.5 >= inv && inv > 0) s = "Paid";
    else s = "Partial";
    if (s !== form.payment_status) setForm((f) => ({ ...f, payment_status: s }));
    // eslint-disable-next-line
  }, [orderPayments.total_received, orderPayments.invoice_total, orderPayments.count]);

  const resetTaxToAuto = () => {
    setForm((f) => ({ ...f, tax_amount_manual: false, tax_amount: summary.auto_tax }));
  };
  const onManualTaxEdit = (v) => {
    setForm((f) => ({ ...f, tax_amount_manual: true, tax_amount: v }));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.client_name?.trim()) return toast.error("Please enter the client name.");
    if (form.items.length === 0) return toast.error("Add at least one product.");

    // Bug fix (2026-07-22) · Vendor linkage validation.
    // Packing cost > 0 requires a Packer vendor so the canonical
    // packing Purchase can be auto-generated with vendor_party_id.
    if (Number(form.packing_cost) > 0 && !(form.packer_name || "").trim()) {
      toast.error("Please select a Packer vendor — packing cost cannot be linked without one.");
      return;
    }
    // Any shipment with freight_paid > 0 requires a transporter so the
    // canonical freight Purchase can be auto-generated.
    const badShip = (form.shipments || []).find((s) =>
      Number(s.freight_paid || 0) > 0 && !(s.transporter || "").trim()
    );
    if (badShip) {
      toast.error(`Shipment ${(badShip.id || "").slice(0, 8)} has freight paid without a transporter — please select one.`);
      return;
    }

    setSaving(true);
    try {
      const payload = {
        ...form,
        order_date: form.order_date ? new Date(form.order_date).toISOString() : null,
        shipped_date: form.shipped_date ? new Date(form.shipped_date).toISOString() : null,
      };
      const existingId = effectiveOrder?.id;
      if (existingId) {
        await api.put(`/orders/${existingId}`, payload);
        toast.success("Order updated");
      } else {
        await api.post("/orders", payload);
        toast.success("Order added");
      }
      onSaved?.();
    } catch (err) {
      console.error(err);
      toast.error("Failed to save order.");
    } finally {
      setSaving(false);
    }
  };

  // Auto-save the order (create if new) so that shipment / payment sub-dialogs can attach to a real id.
  // Returns the effective order id, or null if save was aborted.
  const ensureOrderSaved = async () => {
    if (effectiveOrder?.id) return effectiveOrder.id;
    if (!form.client_name?.trim()) {
      toast.error("Please enter the client name before adding a shipment or payment.");
      return null;
    }
    if (!form.items.length || !form.items.some((i) => i.product_name?.trim())) {
      toast.error("Add at least one product before adding a shipment or payment.");
      return null;
    }
    try {
      const payload = {
        ...form,
        order_date: form.order_date ? new Date(form.order_date).toISOString() : null,
        shipped_date: form.shipped_date ? new Date(form.shipped_date).toISOString() : null,
      };
      const r = await api.post("/orders", payload);
      const created = r.data;
      setSavedOrder(created);
      // sync form with server-generated ids for items etc
      setForm((f) => ({
        ...f,
        items: created.items && created.items.length ? created.items : f.items,
        shipments: created.shipments || [],
        status: created.status,
      }));
      toast.success("Order draft saved");
      return created.id;
    } catch (err) {
      console.error(err);
      toast.error("Could not save the order — check required fields.");
      return null;
    }
  };

  const subsForMain = (mc) => meta.sub_categories_by_main?.[mc] || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[92vh] overflow-y-auto" data-testid="order-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-3xl">
            {effectiveOrder ? "Edit order" : "New order"}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            Add products, packing, freight and tax. Summary updates live below.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-8 mt-2">
          {/* CLIENT / DATES / STATUS */}
          <section>
            <div className="label-caps mb-3">Client & Dates</div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="md:col-span-2">
                <Label className="text-[10px] label-caps">Client</Label>
                <Input value={form.client_name} onChange={(e) => updateField("client_name", e.target.value)}
                       data-testid="ord-client" placeholder="e.g. Minakshi Jain"
                       list="clients-list"
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
                <datalist id="clients-list">
                  {meta.clients?.map((c) => <option key={c} value={c} />)}
                </datalist>
              </div>
              <div>
                <Label className="text-[10px] label-caps">Order date</Label>
                <Input type="date" value={form.order_date} data-testid="ord-order-date"
                       onChange={(e) => updateField("order_date", e.target.value)}
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Shipped date</Label>
                <Input type="date" value={form.shipped_date} data-testid="ord-shipped-date"
                       onChange={(e) => updateField("shipped_date", e.target.value)}
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Payment status</Label>
                <Select value={form.payment_status} onValueChange={(v) => updateField("payment_status", v)}>
                  <SelectTrigger data-testid="ord-payment-status" className="mt-1.5 bg-white border-[var(--border-warm)]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(meta.payment_statuses || []).map((s) => (<SelectItem key={s} value={s}>{s}</SelectItem>))}
                  </SelectContent>
                </Select>
              </div>
              <div className="md:col-span-3">
                <Label className="text-[10px] label-caps">Notes</Label>
                <Textarea value={form.notes} onChange={(e) => updateField("notes", e.target.value)}
                          rows={2}
                          className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
            </div>
          </section>

          {/* PRODUCTS */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="label-caps">Products</div>
                <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                  Add every product in this shipment. Costs stay per-product.
                </div>
              </div>
              <Button type="button" onClick={addItem} data-testid="add-product-btn"
                      size="sm"
                      className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5 rounded-md h-8">
                <Plus size={14} /> Add product
              </Button>
            </div>

            <div className="space-y-4">
              {form.items.map((it, idx) => (
                <div key={it.id || idx} className="rounded-md p-4 border"
                     data-testid={`product-${idx}`}
                     style={{ background: "var(--surface-alt)", borderColor: "var(--border-warm)" }}>
                  <div className="flex items-start justify-between mb-3">
                    <div className="serif text-lg">Product #{idx + 1}</div>
                    {form.items.length > 1 && (
                      <button type="button" onClick={() => removeItem(idx)}
                              data-testid={`remove-product-${idx}`}
                              className="p-1.5 rounded hover:bg-white transition-colors">
                        <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-3">
                    <div>
                      <Label className="text-[10px] label-caps">Main category</Label>
                      <Select value={it.main_category}
                              onValueChange={(v) => updateItem(idx, { main_category: v, sub_category: "" })}>
                        <SelectTrigger data-testid={`item-${idx}-main`} className="mt-1.5 bg-white border-[var(--border-warm)]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(meta.main_categories || []).map((c) => (
                            <SelectItem key={c} value={c}>{c}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label className="text-[10px] label-caps">Sub category</Label>
                      <Input value={it.sub_category} onChange={(e) => updateItem(idx, { sub_category: e.target.value })}
                             list={`subs-${idx}`}
                             placeholder="e.g. Trophy TL"
                             data-testid={`item-${idx}-sub`}
                             className="mt-1.5 bg-white border-[var(--border-warm)]" />
                      <datalist id={`subs-${idx}`}>
                        {subsForMain(it.main_category).map((s) => <option key={s} value={s} />)}
                      </datalist>
                    </div>
                    <div className="md:col-span-2">
                      <Label className="text-[10px] label-caps">Product name</Label>
                      <Input value={it.product_name}
                             onChange={(e) => updateItem(idx, { product_name: e.target.value })}
                             data-testid={`item-${idx}-name`}
                             placeholder="e.g. Trophy TL — Amber Glass"
                             className="mt-1.5 bg-white border-[var(--border-warm)]" />
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-3 mb-3">
                    <Num label="Qty" value={it.qty} onChange={(v) => updateItem(idx, { qty: v })}
                         testId={`item-${idx}-qty`} />
                    <Num label="Selling rate" value={it.rate} onChange={(v) => updateItem(idx, { rate: v })}
                         testId={`item-${idx}-rate`} prefix="₹" />
                    <Num label="Product sales" value={it.product_sales}
                         onChange={(v) => updateItem(idx, { product_sales: v })}
                         testId={`item-${idx}-sales`} prefix="₹"
                         hint="Auto = Qty × Rate. Editable." />
                  </div>

                  <PurchaseSourcesEditor
                    item={it}
                    itemIndex={idx}
                    onChange={(next) => updateItem(idx, next)}
                  />
                </div>
              ))}
            </div>
          </section>

          {/* PACKING */}
          <section>
            <div className="card-warm p-5">
              <div className="flex items-center gap-2 mb-3">
                <Package size={14} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                <div className="label-caps">Packing</div>
                <span className="text-xs" style={{ color: "var(--muted)" }}>
                  Freight, transporter & LR are now captured per shipment below.
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <Num label="Boxes used" value={form.boxes_used} testId="pack-boxes"
                     onChange={(v) => updateField("boxes_used", v)}
                     hint="Prefills each new shipment" />
                <Num label="Cost / box" value={form.cost_per_box} prefix="₹"
                     onChange={(v) => updateField("cost_per_box", v)} />
                <Num label="Packing cost" value={form.packing_cost} prefix="₹" testId="pack-cost"
                     onChange={(v) => setForm((f) => ({ ...f, packing_cost: v, packing_cost_manual: true }))}
                     hint={form.packing_cost_manual
                       ? "Manually set — click Reset to auto"
                       : "Auto = boxes × cost/box"} />
                <Num label="Packing charged (from customer)"
                     value={form.packing_recovery || 0} prefix="₹"
                     testId="pack-charged"
                     onChange={(v) => updateField("packing_recovery", v)}
                     hint="Adds to revenue" />
              </div>
              {/* Canonical Packer selector (Bug fix 2026-07-22).
                  Kept separate from transporter (per-shipment freight vendor).
                  Blank = internal expense (no auto-Purchase). */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mt-3">
                <div className="md:col-span-2">
                  <Label className="text-[10px] label-caps">Packer vendor</Label>
                  <Input list="packer-vendor-list" value={form.packer_name || ""}
                         data-testid="pack-packer"
                         onChange={(e) => updateField("packer_name", e.target.value)}
                         className="mt-1.5 bg-white border-[var(--border-warm)]"
                         placeholder={Number(form.packing_cost) > 0
                           ? "Required when packing cost > 0"
                           : "Optional — select or type to quick-create"} />
                  <datalist id="packer-vendor-list">
                    {vendorParties.map((v) => (
                      <option key={`pkr-${v.id}`} value={v.name} />
                    ))}
                  </datalist>
                  <div className="text-[10px] mt-1"
                       style={{ color: Number(form.packing_cost) > 0 && !(form.packer_name || "").trim()
                         ? "var(--terracotta)" : "var(--muted)" }}
                       data-testid="pack-packer-hint">
                    {Number(form.packing_cost) > 0 && !(form.packer_name || "").trim()
                      ? "Required — the auto-generated packing Purchase will be linked to this vendor's Party Ledger."
                      : (form.packer_name
                          ? "A canonical Purchase for packing will be created under this vendor."
                          : "Leave blank to treat packing as an internal expense (no vendor bill).")}
                  </div>
                </div>
              </div>
              {form.packing_cost_manual && (
                <div className="mt-2 flex justify-end">
                  <button type="button"
                          onClick={() => setForm((f) => ({
                            ...f,
                            packing_cost_manual: false,
                            packing_cost: (Number(f.boxes_used) || 0) * (Number(f.cost_per_box) || 0),
                          }))}
                          data-testid="pack-cost-reset"
                          className="text-[10px] flex items-center gap-1 hover:underline"
                          style={{ color: "var(--terracotta)" }}>
                    <RotateCcw size={10} strokeWidth={2} /> Reset to auto
                  </button>
                </div>
              )}
            </div>
          </section>

          {/* OTHER REVENUE / OTHER EXPENSE */}
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <AdjustmentsCard
              title="Other revenue"
              subtitle="Loose item sale, installation charges, custom work — anything that adds to revenue."
              testId="other-revenue"
              tone="var(--sage)"
              rows={form.other_revenue || []}
              suggestions={REVENUE_SUGGESTIONS}
              onAdd={() => addAdj("other_revenue")}
              onUpdate={(idx, patch) => updateAdj("other_revenue", idx, patch)}
              onRemove={(idx) => removeAdj("other_revenue", idx)}
              total={summary.other_rev_total}
            />
            <AdjustmentsCard
              title="Other expense"
              subtitle="Discounts given, labour, local transport, loading — anything that adds to cost."
              testId="other-expense"
              tone="var(--terracotta)"
              rows={form.other_expense || []}
              suggestions={EXPENSE_SUGGESTIONS}
              onAdd={() => addAdj("other_expense")}
              onUpdate={(idx, patch) => updateAdj("other_expense", idx, patch)}
              onRemove={(idx) => removeAdj("other_expense", idx)}
              total={summary.other_exp_total}
            />
          </section>

          {/* TAX */}
          <section className="card-warm p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Receipt size={14} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                <div className="label-caps">Tax</div>
                <span className="text-xs" style={{ color: "var(--muted)" }}>
                  Only affects invoice total — never sales or profit.
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Label className="text-xs" style={{ color: "var(--muted)" }}>Tax applicable</Label>
                <Switch checked={form.tax_applicable} data-testid="tax-toggle"
                        onCheckedChange={(v) => updateField("tax_applicable", v)} />
              </div>
            </div>
            {form.tax_applicable && (
              <div className="space-y-3" data-testid="tax-fields">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <Label className="text-[10px] label-caps">Tax type</Label>
                    <Select value={form.tax_type} onValueChange={(v) => updateField("tax_type", v)}>
                      <SelectTrigger className="mt-1.5 bg-white border-[var(--border-warm)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(meta.tax_types || []).map((t) => (
                          <SelectItem key={t} value={t}>{t.replace("_", " + ")}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Num label="Tax %" value={form.tax_percent} suffix="%"
                       onChange={(v) => updateField("tax_percent", v)} />
                  <div>
                    <div className="flex items-center justify-between">
                      <Label className="text-[10px] label-caps">Tax amount</Label>
                      {form.tax_amount_manual && (
                        <button type="button" onClick={resetTaxToAuto}
                                data-testid="tax-reset-btn"
                                className="text-[10px] flex items-center gap-1 hover:underline"
                                style={{ color: "var(--terracotta)" }}>
                          <RotateCcw size={10} strokeWidth={2} /> Reset to auto
                        </button>
                      )}
                    </div>
                    <Input
                      type="number" step="0.01"
                      value={form.tax_amount || 0}
                      onChange={(e) => onManualTaxEdit(parseFloat(e.target.value) || 0)}
                      data-testid="tax-amount-input"
                      className="mt-1.5 bg-white border-[var(--border-warm)]"
                    />
                    <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
                      {form.tax_amount_manual
                        ? "Manually set — click Reset to auto-calculate"
                        : `Auto: ${(Number(form.tax_percent) || 0)}% of (revenue − other expense)`}
                    </div>
                  </div>
                </div>
                {form.tax_amount_manual && (
                  <div className="text-xs px-3 py-2 rounded"
                       style={{ background: "rgba(212,163,115,0.15)", color: "#8a5a2c" }}
                       data-testid="tax-manual-notice">
                    Manual tax amount stored. Dashboard, exports and invoice will use ₹{form.tax_amount}.
                  </div>
                )}
              </div>
            )}
          </section>

          {/* SHIPMENTS — integrated into the order lifecycle */}
          <section className="card-warm p-5" data-testid="shipments-section">
            <div className="flex items-center justify-between mb-3">
              <button type="button" onClick={() => setShipmentsExpanded((v) => !v)}
                      className="flex items-center gap-2 hover:opacity-80"
                      data-testid="shipments-toggle">
                {shipmentsExpanded
                  ? <ChevronDown size={16} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                  : <ChevronRight size={16} strokeWidth={1.75} style={{ color: "var(--muted)" }} />}
                <Truck size={14} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                <div>
                  <div className="label-caps text-left">Shipments</div>
                  <div className="text-xs mt-1 text-left" style={{ color: "var(--muted)" }}>
                    Revenue &amp; profit are recognized when items are dispatched.
                    {(form.shipments || []).length > 0 && (
                      <span> {(form.shipments || []).length} shipment
                        {(form.shipments || []).length === 1 ? "" : "s"} recorded.</span>
                    )}
                  </div>
                </div>
              </button>
              {effectiveOrder?.id ? (
                <Button type="button" size="sm" onClick={openNewShipment}
                        data-testid="add-shipment-btn"
                        className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5 h-8">
                  <Plus size={13} /> Add shipment
                </Button>
              ) : (
                <Button type="button" size="sm" onClick={openNewShipment}
                        data-testid="add-shipment-btn"
                        className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5 h-8">
                  <Plus size={13} /> Save &amp; add shipment
                </Button>
              )}
            </div>

            {!effectiveOrder?.id && shipmentsExpanded && (
              <div className="text-xs p-3 rounded flex items-start gap-2"
                   style={{ background: "rgba(74,109,124,0.08)", color: "#4A6D7C" }}>
                <Info size={13} className="mt-0.5 shrink-0" />
                <div>
                  Enter client &amp; products above, then click <b>Save &amp; add shipment</b> to record the first dispatch. Revenue is recognized only from shipped quantities.
                </div>
              </div>
            )}

            {effectiveOrder?.id && shipmentsExpanded && (
              <>
                {/* Shipment progress panel — always shown for saved orders */}
                {(() => {
                  const ordered = Number(form.ordered_qty_total || 0) || (form.items || []).reduce((s, i) => s + Number(i.qty || 0), 0);
                  const shipped = Number(form.shipped_qty_total || 0) || (form.shipments || []).reduce((s, sh) => s + (sh.items || []).reduce((ss, si) => ss + Number(si.qty || 0), 0), 0);
                  const remaining = Math.max(0, ordered - shipped);
                  const ratio = ordered > 0 ? shipped / ordered : 0;
                  const invoice = Number(orderPayments.invoice_total || summary.invoice || 0);
                  const revenueRecognized = ordered > 0 ? invoice : 0;
                  const totalPotential = ordered > 0 ? (invoice / (ratio || 1)) : 0;
                  const pendingRevenue = Math.max(0, totalPotential - revenueRecognized);
                  return (
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3 p-3 rounded-md"
                         style={{ background: "var(--surface-alt)", border: "1px solid var(--border-warm)" }}
                         data-testid="shipment-progress-panel">
                      <div>
                        <div className="label-caps text-[10px]">Ordered</div>
                        <div className="serif text-base num mt-0.5" data-testid="prog-ordered">{ordered.toFixed(0)} pcs</div>
                      </div>
                      <div>
                        <div className="label-caps text-[10px]">Shipped</div>
                        <div className="serif text-base num mt-0.5" style={{ color: "var(--sage)" }}
                             data-testid="prog-shipped">{shipped.toFixed(0)} pcs</div>
                      </div>
                      <div>
                        <div className="label-caps text-[10px]">Remaining</div>
                        <div className="serif text-base num mt-0.5"
                             style={{ color: remaining > 0 ? "var(--terracotta)" : "var(--muted)" }}
                             data-testid="prog-remaining">{remaining.toFixed(0)} pcs</div>
                      </div>
                      <div>
                        <div className="label-caps text-[10px]">Revenue recognized</div>
                        <div className="serif text-base num mt-0.5" style={{ color: "var(--sage)" }}
                             data-testid="prog-rev-recognized">{fmtINR(revenueRecognized)}</div>
                      </div>
                      <div>
                        <div className="label-caps text-[10px]">Pending revenue</div>
                        <div className="serif text-base num mt-0.5"
                             style={{ color: pendingRevenue > 0.5 ? "var(--terracotta)" : "var(--muted)" }}
                             data-testid="prog-rev-pending">{fmtINR(pendingRevenue)}</div>
                      </div>
                    </div>
                  );
                })()}

                {(form.shipments || []).length === 0 ? (
                  <div className="text-xs py-6 text-center rounded"
                       style={{ background: "var(--surface-alt)", color: "var(--muted)" }}>
                    No shipments yet. Nothing counted as revenue.
                    <div className="mt-2">
                      <Button type="button" size="sm" onClick={openNewShipment}
                              data-testid="empty-add-shipment"
                              className="bg-white border h-8 text-xs gap-1.5"
                              style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                        <Plus size={12} /> Record first shipment
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {(form.shipments || []).map((sh, sidx) => {
                      const shippedQty = (sh.items || []).reduce((s, si) => s + Number(si.qty || 0), 0);
                      return (
                        <div key={sh.id || sidx}
                             className="rounded-md border bg-white px-4 py-3 flex items-center gap-4"
                             style={{ borderColor: "var(--border-warm)" }}
                             data-testid={`shipment-row-${sidx}`}>
                          <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
                               style={{ background: "rgba(197,91,67,0.12)", color: "var(--terracotta)" }}>
                            <Truck size={15} strokeWidth={1.75} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-3 flex-wrap">
                              <span className="text-sm font-medium">{fmtDate(sh.date)}</span>
                              <span className="text-xs num" style={{ color: "var(--terracotta)" }}>
                                {shippedQty} qty
                              </span>
                              {sh.boxes_shipped > 0 && (
                                <span className="text-xs" style={{ color: "var(--muted)" }}>
                                  · {sh.boxes_shipped} boxes
                                </span>
                              )}
                              {sh.transporter && (
                                <span className="text-xs" style={{ color: "var(--muted)" }}>
                                  · via {sh.transporter}
                                </span>
                              )}
                              {sh.lr_number && (
                                <span className="text-xs" style={{ color: "var(--muted)" }}>
                                  · LR {sh.lr_number}
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] mt-1" style={{ color: "var(--muted)" }}>
                              {sh.freight_charged > 0 && (
                                <span>Freight charged {fmtINR(sh.freight_charged)}</span>
                              )}
                              {sh.freight_charged > 0 && sh.freight_paid > 0 && <span> · </span>}
                              {sh.freight_paid > 0 && (
                                <span>Freight paid {fmtINR(sh.freight_paid)}</span>
                              )}
                              {sh.remarks && <span> · {sh.remarks}</span>}
                            </div>
                          </div>
                          <div className="flex items-center gap-1 shrink-0">
                            <button type="button" onClick={() => openEditShipment(sh)}
                                    data-testid={`edit-shipment-${sidx}`}
                                    className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                              <Pencil size={13} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                            </button>
                            <button type="button" onClick={() => deleteShipment(sh)}
                                    data-testid={`delete-shipment-${sidx}`}
                                    className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                              <Trash2 size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                            </button>
                          </div>
                        </div>
                      );
                    })}

                    <div className="pt-2 grid grid-cols-3 gap-4 text-xs border-t mt-2"
                         style={{ borderColor: "var(--border-warm)" }}>
                      <div className="pt-2">
                        <div className="label-caps">Shipped qty</div>
                        <div className="serif text-base num mt-0.5"
                             data-testid="shipped-qty-total">
                          {form.shipped_qty_total || 0} / {form.ordered_qty_total || 0}
                        </div>
                      </div>
                      <div className="pt-2">
                        <div className="label-caps">Freight charged</div>
                        <div className="serif text-base num mt-0.5" style={{ color: "var(--sage)" }}>
                          {fmtINR((form.shipments || []).reduce((s, sh) => s + Number(sh.freight_charged || 0), 0))}
                        </div>
                      </div>
                      <div className="pt-2">
                        <div className="label-caps">Freight paid</div>
                        <div className="serif text-base num mt-0.5" style={{ color: "var(--terracotta)" }}>
                          {fmtINR((form.shipments || []).reduce((s, sh) => s + Number(sh.freight_paid || 0), 0))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>

          {/* PAYMENTS RECEIVED — allocated from Customer Payments */}
          <section className="card-warm p-5" data-testid="order-payments-section">
            <div className="flex items-center justify-between mb-3">
              <button type="button" onClick={() => setPaymentsExpanded((v) => !v)}
                      className="flex items-center gap-2 hover:opacity-80"
                      data-testid="order-payments-toggle">
                {paymentsExpanded
                  ? <ChevronDown size={16} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                  : <ChevronRight size={16} strokeWidth={1.75} style={{ color: "var(--muted)" }} />}
                <Banknote size={14} strokeWidth={1.75} style={{ color: "var(--sage)" }} />
                <div>
                  <div className="label-caps text-left">Payments received</div>
                  <div className="text-xs mt-1 text-left" style={{ color: "var(--muted)" }}>
                    Money receipts allocated to this order. Also updates the Party Ledger and Cash Book.
                  </div>
                </div>
              </button>
              {effectiveOrder?.id ? (
                <Button type="button" size="sm" onClick={openNewPayment}
                        data-testid="add-order-payment-btn"
                        className="bg-[var(--sage)] hover:opacity-90 text-white gap-1.5 h-8">
                  <Plus size={13} /> Record payment
                </Button>
              ) : (
                <Button type="button" size="sm" onClick={openNewPayment}
                        data-testid="add-order-payment-btn"
                        className="bg-[var(--sage)] hover:opacity-90 text-white gap-1.5 h-8">
                  <Plus size={13} /> Save &amp; record payment
                </Button>
              )}
            </div>

            {!effectiveOrder?.id && paymentsExpanded && (
              <div className="text-xs p-3 rounded flex items-start gap-2"
                   style={{ background: "rgba(74,109,124,0.08)", color: "#4A6D7C" }}>
                <Info size={13} className="mt-0.5 shrink-0" />
                <div>Enter client &amp; products above, then click <b>Save &amp; record payment</b> to log a receipt against this order.</div>
              </div>
            )}

            {effectiveOrder?.id && paymentsExpanded && (
              <>
                {/* Customer Advance Available — one-click allocate */}
                {Number(orderPayments.customer_advance_available || 0) > 0.5 && Number(orderPayments.outstanding || 0) > 0.5 && (
                  <div className="mb-3 rounded-md border px-4 py-3 flex items-center gap-3"
                       style={{ borderColor: "var(--border-warm)", background: "rgba(212,163,115,0.10)" }}
                       data-testid="customer-advance-card">
                    <Coins size={16} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium">
                        Customer advance available: <span className="num serif text-base ml-1"
                          style={{ color: "var(--terracotta)" }}>{fmtINR(orderPayments.customer_advance_available)}</span>
                      </div>
                      <div className="text-[11px] mt-0.5" style={{ color: "var(--muted)" }}>
                        Applying will update the existing payment — no duplicate record is created.
                      </div>
                    </div>
                    <Button type="button" size="sm" onClick={allocateAdvance}
                            data-testid="allocate-advance-btn"
                            className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5 h-8">
                      Allocate to this Order
                    </Button>
                  </div>
                )}
                {(orderPayments.payments || []).length === 0 ? (
                  <div className="text-xs py-6 text-center rounded"
                       style={{ background: "var(--surface-alt)", color: "var(--muted)" }}>
                    No payments received yet for this order.
                    <div className="mt-2">
                      <Button type="button" size="sm" onClick={openNewPayment}
                              data-testid="empty-add-payment"
                              className="bg-white border h-8 text-xs gap-1.5"
                              style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                        <Plus size={12} /> Record first payment
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {(orderPayments.payments || []).map((p, pidx) => (
                      <div key={p.payment_id}
                           className="rounded-md border bg-white px-4 py-3 flex items-center gap-4"
                           style={{ borderColor: "var(--border-warm)" }}
                           data-testid={`order-payment-row-${pidx}`}>
                        <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
                             style={{ background: "rgba(58,90,64,0.12)", color: "var(--sage)" }}>
                          <Banknote size={15} strokeWidth={1.75} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 flex-wrap">
                            <span className="text-sm font-medium">{fmtDate(p.date)}</span>
                            <span className="text-sm num" style={{ color: "var(--sage)" }}>
                              {fmtINR(p.allocated_to_this_order)}
                            </span>
                            {Math.abs(p.total_amount - p.allocated_to_this_order) > 0.5 && (
                              <span className="text-[10px]" style={{ color: "var(--muted)" }}>
                                (of {fmtINR(p.total_amount)} total)
                              </span>
                            )}
                            <span className="inline-block px-2 py-0.5 rounded-full text-[10px]"
                                  style={{ background: "var(--surface-alt)" }}>
                              {p.mode || "—"}
                            </span>
                            {p.payment_status && (
                              <span className="inline-block px-2 py-0.5 rounded-full text-[10px]"
                                    style={{ background: p.payment_status === "Full" ? "rgba(58,90,64,0.15)"
                                              : p.payment_status === "Advance" ? "rgba(212,163,115,0.20)"
                                              : "rgba(197,91,67,0.15)",
                                             color: p.payment_status === "Full" ? "var(--sage)"
                                              : p.payment_status === "Advance" ? "var(--terracotta)"
                                              : "var(--terracotta)" }}
                                    data-testid={`order-payment-status-${pidx}`}>
                                {p.payment_status}
                              </span>
                            )}
                          </div>
                          <div className="text-[11px] mt-1" style={{ color: "var(--muted)" }}>
                            {p.account_name && (
                              <span className="inline-flex items-center gap-1">
                                <Landmark size={10} /> {p.account_name}
                              </span>
                            )}
                            {p.received_by_party_name && <span> · via {p.received_by_party_name}</span>}
                            {p.reference && <span> · Ref {p.reference}</span>}
                            {p.remarks && <span> · {p.remarks}</span>}
                          </div>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <button type="button" onClick={() => openEditPayment(p)}
                                  data-testid={`edit-order-payment-${pidx}`}
                                  className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                            <Pencil size={13} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                          </button>
                          <button type="button" onClick={() => deleteOrderPayment(p)}
                                  data-testid={`delete-order-payment-${pidx}`}
                                  className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                            <Trash2 size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Payments summary — always shown when we have orderPayments loaded */}
                <div className="pt-3 grid grid-cols-2 md:grid-cols-4 gap-4 text-xs border-t mt-3"
                     style={{ borderColor: "var(--border-warm)" }}>
                  <div className="pt-2">
                    <div className="label-caps">Invoice total</div>
                    <div className="serif text-base num mt-0.5"
                         data-testid="op-invoice-total">{fmtINR(orderPayments.invoice_total)}</div>
                  </div>
                  <div className="pt-2">
                    <div className="label-caps">Total received</div>
                    <div className="serif text-base num mt-0.5" style={{ color: "var(--sage)" }}
                         data-testid="op-received">{fmtINR(orderPayments.total_received)}</div>
                  </div>
                  <div className="pt-2">
                    <div className="label-caps">Outstanding balance</div>
                    <div className="serif text-base num mt-0.5"
                         style={{ color: orderPayments.outstanding > 0.5 ? "var(--danger)" : "var(--sage)" }}
                         data-testid="op-outstanding">
                      {fmtINR(orderPayments.outstanding)}
                    </div>
                  </div>
                  <div className="pt-2">
                    <div className="label-caps">Customer advance</div>
                    <div className="serif text-base num mt-0.5"
                         style={{ color: (orderPayments.customer_advance_available || 0) > 0 ? "var(--terracotta)" : "var(--muted)" }}
                         data-testid="op-advance">
                      {fmtINR(orderPayments.customer_advance_available || 0)}
                    </div>
                  </div>
                </div>
              </>
            )}
          </section>

          {/* PAYMENT DETAILS — moved to standalone Customer Payments module */}
          {false && (form.payment_status === "Partial" || form.payment_status === "Paid") && (
            <section className="card-warm p-5" data-testid="payment-details">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Banknote size={14} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                  <div className="label-caps">Payment details</div>
                </div>
                <Button type="button" size="sm"
                        onClick={() => addPayment(summary.invoice)}
                        data-testid="add-payment-btn"
                        className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5 h-8">
                  <Plus size={13} /> Add another payment
                </Button>
              </div>

              {(form.order_payments || []).length === 0 ? (
                <div className="text-xs py-4 text-center" style={{ color: "var(--muted)" }}>
                  No payments recorded. Click Add to log one.
                </div>
              ) : (
                <div className="space-y-3">
                  {form.order_payments.map((p, idx) => (
                    <div key={p.id || idx}
                         className="rounded-md p-3 border"
                         style={{ background: "var(--surface-alt)", borderColor: "var(--border-warm)" }}
                         data-testid={`payment-row-${idx}`}>
                      <div className="flex items-start justify-between mb-2">
                        <div className="text-xs font-medium">Payment #{idx + 1}</div>
                        <button type="button" onClick={() => removePayment(idx)}
                                data-testid={`remove-payment-${idx}`}
                                className="p-1 rounded hover:bg-white">
                          <Trash2 size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                        </button>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                        <div>
                          <Label className="text-[10px] label-caps">Amount</Label>
                          <div className="relative mt-1.5">
                            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs"
                                  style={{ color: "var(--muted)" }}>₹</span>
                            <Input type="number" step="0.01"
                                   value={p.amount === 0 ? "" : p.amount}
                                   placeholder="0"
                                   onChange={(e) => updatePayment(idx, { amount: parseFloat(e.target.value) || 0 })}
                                   data-testid={`pmt-amount-${idx}`}
                                   className="pl-6 bg-white border-[var(--border-warm)] num" />
                          </div>
                        </div>
                        <div>
                          <Label className="text-[10px] label-caps">Mode</Label>
                          <Select value={p.mode} onValueChange={(v) => updatePayment(idx, { mode: v })}>
                            <SelectTrigger data-testid={`pmt-mode-${idx}`} className="mt-1.5 bg-white border-[var(--border-warm)]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {(meta.payment_modes || []).map((m) => (
                                <SelectItem key={m} value={m}>{m}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div>
                          <Label className="text-[10px] label-caps">Received in</Label>
                          <Select
                            value={p.account_id || ""}
                            onValueChange={(v) => {
                              const acc = (meta.accounts || []).find((a) => a.id === v);
                              updatePayment(idx, { account_id: v, account_name: acc?.name || "" });
                            }}>
                            <SelectTrigger data-testid={`pmt-account-${idx}`} className="mt-1.5 bg-white border-[var(--border-warm)]">
                              <SelectValue placeholder="Select account" />
                            </SelectTrigger>
                            <SelectContent>
                              {(meta.accounts || []).map((a) => (
                                <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div>
                          <Label className="text-[10px] label-caps">Date</Label>
                          <Input type="date"
                                 value={p.date ? p.date.substring(0, 10) : ""}
                                 onChange={(e) => updatePayment(idx, { date: e.target.value })}
                                 data-testid={`pmt-date-${idx}`}
                                 className="mt-1.5 bg-white border-[var(--border-warm)]" />
                        </div>
                        <div className="md:col-span-2">
                          <Label className="text-[10px] label-caps">Reference / UTR (optional)</Label>
                          <Input value={p.reference || ""}
                                 onChange={(e) => updatePayment(idx, { reference: e.target.value })}
                                 data-testid={`pmt-ref-${idx}`}
                                 className="mt-1.5 bg-white border-[var(--border-warm)]" />
                        </div>
                        <div className="md:col-span-2">
                          <Label className="text-[10px] label-caps">Remarks (optional)</Label>
                          <Input value={p.remarks || ""}
                                 onChange={(e) => updatePayment(idx, { remarks: e.target.value })}
                                 data-testid={`pmt-remarks-${idx}`}
                                 className="mt-1.5 bg-white border-[var(--border-warm)]" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-4 pt-3 border-t grid grid-cols-3 gap-4"
                   style={{ borderColor: "var(--border-warm)" }}>
                <div>
                  <div className="text-[10px] label-caps">Invoice total</div>
                  <div className="serif text-lg num mt-1">{fmtINR(summary.invoice)}</div>
                </div>
                <div>
                  <div className="text-[10px] label-caps">Total received</div>
                  <div className="serif text-lg num mt-1" style={{ color: "var(--sage)" }}
                       data-testid="pmt-received">{fmtINR(summary.received)}</div>
                </div>
                <div>
                  <div className="text-[10px] label-caps">Outstanding</div>
                  <div className="serif text-lg num mt-1"
                       style={{ color: summary.outstanding > 0.5 ? "var(--terracotta)" : "var(--sage)" }}
                       data-testid="pmt-outstanding">
                    {fmtINR(summary.outstanding)}
                  </div>
                </div>
              </div>
              <div className="mt-3 text-[10px]" style={{ color: "var(--muted)" }}>
                Account is only a reference tag for where the receipt was received. This app does not compute
                or reconcile bank balances.
              </div>
            </section>
          )}

          {/* TIMELINE — history of the order */}
          {effectiveOrder?.id && (
            <section className="card-warm p-5" data-testid="order-timeline-section">
              <div className="flex items-center justify-between mb-3">
                <button type="button" onClick={() => setTimelineExpanded((v) => !v)}
                        className="flex items-center gap-2 hover:opacity-80"
                        data-testid="order-timeline-toggle">
                  {timelineExpanded
                    ? <ChevronDown size={16} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                    : <ChevronRight size={16} strokeWidth={1.75} style={{ color: "var(--muted)" }} />}
                  <Clock size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                  <div>
                    <div className="label-caps text-left">Timeline</div>
                    <div className="text-xs mt-1 text-left" style={{ color: "var(--muted)" }}>
                      Everything that has happened to this order — created, shipped, paid.
                      {timeline.length > 0 && <span> {timeline.length} events.</span>}
                    </div>
                  </div>
                </button>
              </div>
              {timelineExpanded && (
                timeline.length === 0 ? (
                  <div className="text-xs py-6 text-center rounded"
                       style={{ background: "var(--surface-alt)", color: "var(--muted)" }}>
                    No events yet.
                  </div>
                ) : (
                  <div className="space-y-2" data-testid="order-timeline">
                    {timeline.map((ev, i) => (
                      <div key={i}
                           className="rounded-md border bg-white px-4 py-3 flex items-center gap-4"
                           style={{ borderColor: "var(--border-warm)" }}
                           data-testid={`timeline-event-${i}`}>
                        <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0"
                             style={{
                               background: ev.type === "shipment" ? "rgba(197,91,67,0.12)"
                                         : ev.type === "payment" ? "rgba(58,90,64,0.12)"
                                         : "rgba(122,117,113,0.15)",
                               color: ev.type === "shipment" ? "var(--terracotta)"
                                    : ev.type === "payment" ? "var(--sage)"
                                    : "var(--muted)",
                             }}>
                          {ev.type === "shipment" ? <Truck size={14} strokeWidth={1.75} />
                           : ev.type === "payment" ? <Banknote size={14} strokeWidth={1.75} />
                           : <Package size={14} strokeWidth={1.75} />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 flex-wrap">
                            <span className="text-xs font-medium" style={{ color: "var(--muted)" }}>{fmtDate(ev.date)}</span>
                            <span className="text-sm">{ev.title}</span>
                          </div>
                          {ev.detail && (
                            <div className="text-[11px] mt-0.5" style={{ color: "var(--muted)" }}>{ev.detail}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )
              )}
            </section>
          )}

          {/* SUMMARY */}
          <section className="rounded-md p-5"
                   style={{ background: "var(--surface-alt)", border: "1px solid var(--border-warm)" }}>
            <div className="flex items-center justify-between mb-4">
              <div className="label-caps">Order summary</div>
              {effectiveOrder?.id && (
                <div className="flex flex-wrap gap-1.5" data-testid="order-party-links">
                  <a href={`/party-ledger?type=customer&name=${encodeURIComponent(form.client_name || "")}`}
                     target="_blank" rel="noreferrer"
                     data-testid="link-customer-ledger"
                     className="text-[11px] px-2.5 py-1 rounded-full border inline-flex items-center gap-1 hover:bg-white transition-colors"
                     style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                    <Users size={11} /> Customer Ledger
                  </a>
                  <a href={`/party-ledger?type=vendor`}
                     target="_blank" rel="noreferrer"
                     data-testid="link-vendor-ledger"
                     className="text-[11px] px-2.5 py-1 rounded-full border inline-flex items-center gap-1 hover:bg-white transition-colors"
                     style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                    <Building2 size={11} /> Vendor Ledger
                  </a>
                  <a href={`/party-ledger?type=fathers_firm`}
                     target="_blank" rel="noreferrer"
                     data-testid="link-fathers-firm"
                     className="text-[11px] px-2.5 py-1 rounded-full border inline-flex items-center gap-1 hover:bg-white transition-colors"
                     style={{ borderColor: "var(--border-warm)", color: "var(--ink)" }}>
                    <Landmark size={11} /> Father's Firm
                  </a>
                </div>
              )}
            </div>
            {(() => {
              const fullyShipped = ["Fully Shipped", "Delivered"].includes(form.status);
              const profitLabel = fullyShipped ? "Net profit" : "Estimated profit";
              return (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div>
                      <div className="text-[10px] label-caps">Invoice total</div>
                      <div className="serif text-xl num mt-1" data-testid="sum-invoice">{fmtINR(summary.invoice)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Total received</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--sage)" }}
                           data-testid="sum-received">{fmtINR(orderPayments.total_received || 0)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Outstanding</div>
                      <div className="serif text-xl num mt-1"
                           style={{ color: (orderPayments.outstanding || 0) > 0.5 ? "var(--danger)" : "var(--sage)" }}
                           data-testid="sum-outstanding">
                        {fmtINR(orderPayments.outstanding || 0)}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Operating revenue</div>
                      <div className="serif text-xl num mt-1" data-testid="sum-revenue">{fmtINR(summary.revenue)}</div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t"
                       style={{ borderColor: "var(--border-warm)" }}>
                    <div>
                      <div className="text-[10px] label-caps">Purchase cost</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--muted)" }}
                           data-testid="sum-purchase">{fmtINR(summary.factory_cost + summary.outside_cost)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Packing</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--muted)" }}
                           data-testid="sum-packing">{fmtINR(Number(form.packing_cost || 0))}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Freight</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--muted)" }}
                           data-testid="sum-freight">{fmtINR((form.shipments || []).reduce((s, sh) => s + Number(sh.freight_paid || 0), 0))}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Other costs</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--muted)" }}
                           data-testid="sum-other-cost">{fmtINR(summary.other_exp_total)}</div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t"
                       style={{ borderColor: "var(--border-warm)" }}>
                    <div>
                      <div className="text-[10px] label-caps">Total cost</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--muted)" }}>{fmtINR(summary.cost)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Tax amount</div>
                      <div className="serif text-xl num mt-1" style={{ color: "var(--muted)" }}>{fmtINR(summary.tax_amount)}</div>
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">{profitLabel}</div>
                      <div className="serif text-xl num mt-1" data-testid="sum-profit"
                           style={{ color: summary.profit >= 0 ? "var(--sage)" : "var(--danger)" }}>
                        {fmtINR(summary.profit)}
                      </div>
                      {!fullyShipped && (
                        <div className="text-[10px] mt-0.5" style={{ color: "var(--muted)" }}>
                          Final when order completes
                        </div>
                      )}
                    </div>
                    <div>
                      <div className="text-[10px] label-caps">Current margin</div>
                      <div className="serif text-xl num mt-1"
                           style={{ color: summary.margin >= 0 ? "var(--sage)" : "var(--danger)" }}
                           data-testid="sum-margin">
                        {summary.margin.toFixed(1)}%
                      </div>
                    </div>
                  </div>
                </>
              );
            })()}
          </section>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="ord-save-btn"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Saving…" : (effectiveOrder ? "Update order" : "Add order")}
            </Button>
          </DialogFooter>
        </form>

        {effectiveOrder?.id && (
          <ShipmentDialog
            open={shipmentDialog.open}
            onOpenChange={(v) => setShipmentDialog((s) => ({ ...s, open: v, shipment: v ? s.shipment : null }))}
            order={{ ...effectiveOrder, items: form.items, shipments: form.shipments }}
            shipment={shipmentDialog.shipment}
            onSaved={async () => {
              setShipmentDialog({ open: false, shipment: null });
              await refreshOrderShipments();
              onSaved?.({ keepOpen: true });
            }}
          />
        )}

        {effectiveOrder?.id && (
          <CustomerPaymentDialog
            open={paymentDialog.open}
            onOpenChange={(v) => setPaymentDialog((s) => ({ ...s, open: v, payment: v ? s.payment : null }))}
            payment={paymentDialog.payment}
            defaultCustomer={form.client_name || effectiveOrder?.client_name}
            onSaved={async () => {
              setPaymentDialog({ open: false, payment: null });
              await refreshOrderPayments();
              await refreshOrderShipments();
              onSaved?.({ keepOpen: true });
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
