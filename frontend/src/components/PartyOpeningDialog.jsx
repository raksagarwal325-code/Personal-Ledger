import { useEffect, useState } from "react";
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
import { api } from "../lib/api";
import { toast } from "sonner";

const TYPE_OPTIONS = [
  { value: "vendor",   label: "Vendor" },
  { value: "customer", label: "Customer" },
  { value: "other",    label: "Other" },
];

// Dialog for creating a new party or editing an existing party's opening balance.
export default function PartyOpeningDialog({ open, onOpenChange, party, onSaved }) {
  const isNew = !party || !party.id;
  const [form, setForm] = useState({
    name: "",
    type: "vendor",
    opening_direction: "you_pay",   // you_pay = I owe them (positive); you_receive = they owe me
    opening_amount: "",
    opening_date: new Date().toISOString().substring(0, 10),
    opening_notes: "",
    phone: "",
    email: "",
    gstin: "",
    address: "",
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (isNew) {
      setForm({
        name: "", type: "vendor",
        opening_direction: "you_pay", opening_amount: "",
        opening_date: new Date().toISOString().substring(0, 10),
        opening_notes: "", phone: "", email: "", gstin: "", address: "",
      });
    } else {
      const ob = Number(party.opening_balance || 0);
      setForm({
        name: party.name || "",
        type: party.type || "other",
        opening_direction: ob >= 0 ? "you_pay" : "you_receive",
        opening_amount: ob ? String(Math.abs(ob)) : "",
        opening_date: party.opening_date ? party.opening_date.substring(0, 10) : new Date().toISOString().substring(0, 10),
        opening_notes: party.opening_notes || "",
        phone: party.contact?.phone || "",
        email: party.contact?.email || "",
        gstin: party.contact?.gstin || "",
        address: party.contact?.address || "",
      });
    }
  }, [open, party, isNew]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() && isNew) return toast.error("Party name is required.");
    const amt = parseFloat(form.opening_amount || 0);
    const opening_balance = amt
      ? (form.opening_direction === "you_pay" ? amt : -amt)
      : 0;
    setSaving(true);
    try {
      const payload = {
        ...(isNew ? {} : party),
        name: form.name.trim(),
        type: form.type,
        opening_balance,
        opening_date: form.opening_date ? new Date(form.opening_date).toISOString() : null,
        opening_notes: form.opening_notes || "",
        contact: {
          phone: form.phone || "",
          email: form.email || "",
          gstin: form.gstin || "",
          address: form.address || "",
        },
      };
      if (isNew) {
        await api.post("/party-ledger-v2/parties", payload);
        toast.success(`Party "${form.name}" created`);
      } else {
        await api.put(`/party-ledger-v2/parties/${party.id}`, { ...payload, id: party.id });
        toast.success("Party updated");
      }
      onSaved?.();
    } catch (err) {
      const msg = err?.response?.data?.detail || "Failed to save party";
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="party-opening-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-2xl">
            {isNew ? "New party" : `Edit ${party?.name}`}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            {isNew
              ? "Create a new counterparty. You can set an opening balance if there was already a running dues position."
              : "Update contact details or the opening balance (dues carried forward from before the ledger started)."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4 mt-2">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] label-caps">Name</Label>
              <Input value={form.name}
                     onChange={(e) => set("name", e.target.value)}
                     disabled={!isNew && party?.is_system}
                     data-testid="po-name"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[10px] label-caps">Type</Label>
              <Select value={form.type} onValueChange={(v) => set("type", v)}
                      disabled={!isNew}>
                <SelectTrigger data-testid="po-type" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TYPE_OPTIONS.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="card-warm p-3">
            <div className="label-caps text-[10px] mb-2">Opening balance</div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Label className="text-[10px] label-caps">Amount</Label>
                <div className="relative mt-1.5">
                  <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs"
                        style={{ color: "var(--muted)" }}>₹</span>
                  <Input type="number" step="0.01" value={form.opening_amount}
                         onChange={(e) => set("opening_amount", e.target.value)}
                         data-testid="po-amount"
                         placeholder="0"
                         className="pl-6 bg-white border-[var(--border-warm)] num text-right" />
                </div>
              </div>
              <div>
                <Label className="text-[10px] label-caps">Date</Label>
                <Input type="date" value={form.opening_date}
                       onChange={(e) => set("opening_date", e.target.value)}
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between">
              <div className="text-xs" style={{ color: "var(--muted)" }}>
                {form.opening_direction === "you_pay"
                  ? "You Pay — you already owed this party"
                  : "You Receive — this party already owed you"}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs"
                      style={{ color: form.opening_direction === "you_pay" ? "var(--danger)" : "var(--muted)" }}>
                  You Pay
                </span>
                <Switch
                  checked={form.opening_direction === "you_receive"}
                  onCheckedChange={(v) => set("opening_direction", v ? "you_receive" : "you_pay")}
                  data-testid="po-direction"
                />
                <span className="text-xs"
                      style={{ color: form.opening_direction === "you_receive" ? "var(--sage)" : "var(--muted)" }}>
                  You Receive
                </span>
              </div>
            </div>
            <div className="mt-3">
              <Label className="text-[10px] label-caps">Notes</Label>
              <Textarea rows={2} value={form.opening_notes}
                        onChange={(e) => set("opening_notes", e.target.value)}
                        placeholder="Where does this dues position come from?"
                        className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] label-caps">Phone</Label>
              <Input value={form.phone} onChange={(e) => set("phone", e.target.value)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[10px] label-caps">GSTIN</Label>
              <Input value={form.gstin} onChange={(e) => set("gstin", e.target.value)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </div>
          <div>
            <Label className="text-[10px] label-caps">Address</Label>
            <Textarea rows={2} value={form.address} onChange={(e) => set("address", e.target.value)}
                      className="mt-1.5 bg-white border-[var(--border-warm)]" />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="po-save"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Saving…" : (isNew ? "Create party" : "Save changes")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
