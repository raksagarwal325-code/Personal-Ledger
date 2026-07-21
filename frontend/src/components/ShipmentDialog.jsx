import { useState, useEffect, useMemo } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { api, fmtINR } from "../lib/api";
import { toast } from "sonner";
import { Truck, Package } from "lucide-react";

export default function ShipmentDialog({ open, onOpenChange, order, shipment, onSaved }) {
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!order) return;
    const already = order.shipments || [];
    const shippedById = {};
    already.forEach((s) => (s.items || []).forEach((si) => {
      // ignore this shipment if editing
      if (shipment && s.id === shipment.id) return;
      shippedById[si.order_item_id] = (shippedById[si.order_item_id] || 0) + Number(si.qty || 0);
    }));
    const rows = (order.items || []).map((it) => {
      const alreadyShipped = shippedById[it.id] || 0;
      const remaining = Math.max(0, Number(it.qty || 0) - alreadyShipped);
      const existing = (shipment?.items || []).find((si) => si.order_item_id === it.id);
      return {
        order_item_id: it.id,
        product_name: it.product_name,
        main_category: it.main_category,
        ordered: it.qty || 0,
        remaining,
        qty: existing ? Number(existing.qty || 0) : (shipment ? 0 : remaining),
      };
    });
    setForm({
      date: shipment?.date ? shipment.date.substring(0, 10) : new Date().toISOString().substring(0, 10),
      items: rows,
      boxes_shipped: shipment?.boxes_shipped ?? (shipment ? 0 : Number(order?.boxes_used || 0)),
      freight_charged: shipment?.freight_charged || 0,
      freight_paid: shipment?.freight_paid || 0,
      transporter: shipment?.transporter || "",
      lr_number: shipment?.lr_number || "",
      remarks: shipment?.remarks || "",
    });
  }, [order, shipment, open]);

  const totalShipped = useMemo(
    () => (form?.items || []).reduce((s, r) => s + Number(r.qty || 0), 0),
    [form]
  );

  const setQty = (idx, v) => setForm((f) => ({
    ...f,
    items: f.items.map((r, i) => i === idx ? { ...r, qty: v } : r),
  }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form) return;
    const items = form.items.filter((r) => Number(r.qty) > 0)
      .map((r) => ({ order_item_id: r.order_item_id, qty: Number(r.qty) }));
    if (items.length === 0) return toast.error("Add at least one product with a quantity to ship.");

    const payload = {
      date: form.date ? new Date(form.date).toISOString() : null,
      items,
      boxes_shipped: Number(form.boxes_shipped) || 0,
      freight_charged: Number(form.freight_charged) || 0,
      freight_paid: Number(form.freight_paid) || 0,
      transporter: form.transporter,
      lr_number: form.lr_number,
      remarks: form.remarks,
    };
    setSaving(true);
    try {
      if (shipment?.id) {
        await api.put(`/orders/${order.id}/shipments/${shipment.id}`, payload);
        toast.success("Shipment updated");
      } else {
        await api.post(`/orders/${order.id}/shipments`, payload);
        toast.success("Shipment recorded");
      }
      onSaved?.();
    } catch (err) {
      toast.error("Failed to save shipment");
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  if (!form) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[92vh] overflow-y-auto" data-testid="shipment-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-3xl">
            {shipment ? "Edit shipment" : "New shipment"}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            Revenue and profit are recognised for these quantities on the shipping date.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-6 mt-2">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <Label className="text-[10px] label-caps">Shipping date</Label>
              <Input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
                     data-testid="ship-date"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[10px] label-caps">Transporter</Label>
              <Input value={form.transporter} onChange={(e) => setForm({ ...form, transporter: e.target.value })}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[10px] label-caps">LR / tracking</Label>
              <Input value={form.lr_number} onChange={(e) => setForm({ ...form, lr_number: e.target.value })}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </div>

          <div>
            <div className="label-caps mb-3 flex items-center gap-2">
              <Package size={13} /> Products to ship
            </div>
            <div className="rounded-md border overflow-hidden"
                 style={{ borderColor: "var(--border-warm)" }}>
              <table className="w-full text-sm">
                <thead style={{ background: "var(--surface-alt)" }}>
                  <tr>
                    <th className="text-left p-3 label-caps">Product</th>
                    <th className="text-right p-3 label-caps">Ordered</th>
                    <th className="text-right p-3 label-caps">Remaining</th>
                    <th className="text-right p-3 label-caps">Ship now</th>
                  </tr>
                </thead>
                <tbody>
                  {form.items.map((r, idx) => (
                    <tr key={r.order_item_id} className="border-t"
                        style={{ borderColor: "var(--border-warm)" }}>
                      <td className="p-3">
                        <div className="text-xs" style={{ color: "var(--muted)" }}>{r.main_category}</div>
                        <div>{r.product_name}</div>
                      </td>
                      <td className="p-3 text-right num">{r.ordered}</td>
                      <td className="p-3 text-right num" style={{ color: r.remaining > 0 ? "var(--terracotta)" : "var(--muted)" }}>
                        {r.remaining}
                      </td>
                      <td className="p-3 text-right">
                        <Input type="number" step="0.01" value={r.qty}
                               onChange={(e) => setQty(idx, parseFloat(e.target.value) || 0)}
                               data-testid={`ship-qty-${idx}`}
                               className="w-24 ml-auto text-right num bg-white border-[var(--border-warm)] h-8" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="text-xs mt-2 text-right" style={{ color: "var(--muted)" }}>
              Total this shipment: <span className="num font-medium">{totalShipped}</span>
            </div>
          </div>

          <div>
            <div className="label-caps mb-3 flex items-center gap-2">
              <Truck size={13} /> Freight & boxes
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <Label className="text-[10px] label-caps">Boxes shipped</Label>
                <Input type="number" value={form.boxes_shipped} onChange={(e) => setForm({ ...form, boxes_shipped: parseFloat(e.target.value) || 0 })}
                       data-testid="ship-boxes"
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Freight charged</Label>
                <Input type="number" value={form.freight_charged} onChange={(e) => setForm({ ...form, freight_charged: parseFloat(e.target.value) || 0 })}
                       data-testid="ship-freight-charged"
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[10px] label-caps">Freight paid</Label>
                <Input type="number" value={form.freight_paid} onChange={(e) => setForm({ ...form, freight_paid: parseFloat(e.target.value) || 0 })}
                       data-testid="ship-freight-paid"
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
            </div>
          </div>

          <div>
            <Label className="text-[10px] label-caps">Remarks</Label>
            <Input value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })}
                   className="mt-1.5 bg-white border-[var(--border-warm)]" />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="ship-save-btn"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Saving…" : shipment ? "Update shipment" : "Record shipment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
