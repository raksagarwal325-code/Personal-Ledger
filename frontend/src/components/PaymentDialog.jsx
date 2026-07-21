import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { api, MODES } from "../lib/api";
import { toast } from "sonner";

const empty = {
  date: "",
  party: "",
  mode: "RHUF",
  received_by_me: 0,
  received_by_fac: 0,
  payment_by_me: 0,
  payment_by_fac: 0,
  note: "",
};

export default function PaymentDialog({ open, onOpenChange, payment, onSaved }) {
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (payment) {
      setForm({ ...empty, ...payment, date: payment.date ? payment.date.substring(0, 10) : "" });
    } else {
      setForm({ ...empty, date: new Date().toISOString().substring(0, 10) });
    }
  }, [payment, open]);

  const set = (name, val) => setForm((f) => ({ ...f, [name]: val }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.party) {
      toast.error("Please add a party name.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        date: form.date ? new Date(form.date).toISOString() : null,
        received_by_me: Number(form.received_by_me) || 0,
        received_by_fac: Number(form.received_by_fac) || 0,
        payment_by_me: Number(form.payment_by_me) || 0,
        payment_by_fac: Number(form.payment_by_fac) || 0,
      };
      if (payment?.id) {
        await api.put(`/payments/${payment.id}`, payload);
        toast.success("Payment updated");
      } else {
        await api.post("/payments", payload);
        toast.success("Payment added");
      }
      onSaved?.();
    } catch (err) {
      console.error(err);
      toast.error("Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="payment-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-3xl">
            {payment ? "Edit payment" : "New payment"}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            Log money received or paid, with party and mode.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4 mt-2">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="label-caps text-xs">Date</Label>
              <Input type="date" value={form.date} onChange={(e) => set("date", e.target.value)}
                     data-testid="pay-date" className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs">Mode</Label>
              <Select value={form.mode} onValueChange={(v) => set("mode", v)}>
                <SelectTrigger data-testid="pay-mode" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODES.map((m) => (<SelectItem key={m} value={m}>{m}</SelectItem>))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <Label className="label-caps text-xs">Party</Label>
            <Input value={form.party} onChange={(e) => set("party", e.target.value)}
                   placeholder="e.g. Minakshi, Anita, Factory"
                   data-testid="pay-party"
                   className="mt-1.5 bg-white border-[var(--border-warm)]" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="label-caps text-xs" style={{ color: "var(--sage)" }}>Received by me</Label>
              <Input type="number" value={form.received_by_me} data-testid="pay-recv-me"
                     onChange={(e) => set("received_by_me", parseFloat(e.target.value) || 0)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs" style={{ color: "var(--sage)" }}>Received by factory</Label>
              <Input type="number" value={form.received_by_fac} data-testid="pay-recv-fac"
                     onChange={(e) => set("received_by_fac", parseFloat(e.target.value) || 0)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs" style={{ color: "var(--terracotta)" }}>Payment by me</Label>
              <Input type="number" value={form.payment_by_me} data-testid="pay-pay-me"
                     onChange={(e) => set("payment_by_me", parseFloat(e.target.value) || 0)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs" style={{ color: "var(--terracotta)" }}>Payment by factory</Label>
              <Input type="number" value={form.payment_by_fac} data-testid="pay-pay-fac"
                     onChange={(e) => set("payment_by_fac", parseFloat(e.target.value) || 0)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </div>

          <div>
            <Label className="label-caps text-xs">Note (optional)</Label>
            <Input value={form.note} onChange={(e) => set("note", e.target.value)}
                   className="mt-1.5 bg-white border-[var(--border-warm)]" />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="pay-save-btn"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Saving…" : payment ? "Update" : "Add payment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
