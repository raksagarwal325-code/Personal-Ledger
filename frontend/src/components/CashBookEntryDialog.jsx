import { useState, useEffect, useMemo } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { api, MODES } from "../lib/api";
import { toast } from "sonner";

const KIND_META = {
  general_income:  { label: "General Income",  hint: "One-off receipts that don't belong to a specific order (e.g. scrap sale, rebate)." },
  general_expense: { label: "General Expense", hint: "Non-order, non-purchase costs (e.g. rent, office tea, stationery)." },
  transfer:        { label: "Transfer",        hint: "Move money between your own accounts. Profit-neutral." },
};

const empty = {
  date: "",
  kind: "general_expense",
  amount: 0,
  mode: "Cash",
  account_id: "",
  account_name: "",
  from_account_id: "",
  from_account_name: "",
  to_account_id: "",
  to_account_name: "",
  party_name: "",
  reference: "",
  notes: "",
};

export default function CashBookEntryDialog({ open, onOpenChange, initialKind = "general_expense", entry, onSaved }) {
  const [form, setForm] = useState(empty);
  const [accounts, setAccounts] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      api.get("/meta").then((r) => setAccounts(r.data.accounts || []));
    }
  }, [open]);

  useEffect(() => {
    if (entry) {
      setForm({ ...empty, ...entry, date: (entry.date || "").substring(0, 10) });
    } else {
      setForm({ ...empty, kind: initialKind, date: new Date().toISOString().substring(0, 10) });
    }
  }, [entry, initialKind, open]);

  const set = (name, val) => setForm((f) => ({ ...f, [name]: val }));

  const accountByName = useMemo(
    () => Object.fromEntries(accounts.map((a) => [a.id, a])),
    [accounts]
  );

  const submit = async (e) => {
    e.preventDefault();
    if (!Number(form.amount) || Number(form.amount) <= 0) {
      toast.error("Enter an amount greater than zero.");
      return;
    }
    if (form.kind === "transfer") {
      if (!form.from_account_id || !form.to_account_id) {
        toast.error("Transfer needs both source and destination accounts.");
        return;
      }
      if (form.from_account_id === form.to_account_id) {
        toast.error("Source and destination accounts must differ.");
        return;
      }
    }
    setSaving(true);
    try {
      const acctName = (id) => accountByName[id]?.name || "";
      const payload = {
        ...form,
        amount: Number(form.amount) || 0,
        date: form.date ? new Date(form.date).toISOString() : null,
        account_name: acctName(form.account_id),
        from_account_name: acctName(form.from_account_id),
        to_account_name: acctName(form.to_account_id),
      };
      if (entry?.id) {
        await api.put(`/cash-book-entries/${entry.id}`, payload);
        toast.success(`${KIND_META[form.kind].label} updated`);
      } else {
        await api.post("/cash-book-entries", payload);
        toast.success(`${KIND_META[form.kind].label} added`);
      }
      onSaved?.();
      onOpenChange(false);
    } catch (err) {
      console.error(err);
      const msg = err?.response?.data?.detail || "Failed to save.";
      toast.error(typeof msg === "string" ? msg : "Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  const meta = KIND_META[form.kind] || KIND_META.general_expense;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="cashbook-entry-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-3xl">
            {entry ? `Edit ${meta.label.toLowerCase()}` : `New ${meta.label.toLowerCase()}`}
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            {meta.hint}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4 mt-2">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="label-caps text-xs">Kind</Label>
              <Select value={form.kind} onValueChange={(v) => set("kind", v)} disabled={!!entry}>
                <SelectTrigger data-testid="cbe-kind" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="general_income">General Income</SelectItem>
                  <SelectItem value="general_expense">General Expense</SelectItem>
                  <SelectItem value="transfer">Transfer</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="label-caps text-xs">Date</Label>
              <Input type="date" value={form.date} onChange={(e) => set("date", e.target.value)}
                     data-testid="cbe-date" className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="label-caps text-xs">Amount</Label>
              <Input type="number" value={form.amount} data-testid="cbe-amount"
                     onChange={(e) => set("amount", parseFloat(e.target.value) || 0)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs">Mode</Label>
              <Select value={form.mode} onValueChange={(v) => set("mode", v)}>
                <SelectTrigger data-testid="cbe-mode" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MODES.map((m) => (<SelectItem key={m} value={m}>{m}</SelectItem>))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {form.kind === "transfer" ? (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label className="label-caps text-xs">From account</Label>
                <Select value={form.from_account_id} onValueChange={(v) => set("from_account_id", v)}>
                  <SelectTrigger data-testid="cbe-from" className="mt-1.5 bg-white border-[var(--border-warm)]">
                    <SelectValue placeholder="Pick source" />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (<SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="label-caps text-xs">To account</Label>
                <Select value={form.to_account_id} onValueChange={(v) => set("to_account_id", v)}>
                  <SelectTrigger data-testid="cbe-to" className="mt-1.5 bg-white border-[var(--border-warm)]">
                    <SelectValue placeholder="Pick destination" />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (<SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label className="label-caps text-xs">Account</Label>
                <Select value={form.account_id} onValueChange={(v) => set("account_id", v)}>
                  <SelectTrigger data-testid="cbe-account" className="mt-1.5 bg-white border-[var(--border-warm)]">
                    <SelectValue placeholder="—" />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (<SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="label-caps text-xs">Party (optional)</Label>
                <Input value={form.party_name} onChange={(e) => set("party_name", e.target.value)}
                       data-testid="cbe-party"
                       placeholder="e.g. Airtel, Office"
                       className="mt-1.5 bg-white border-[var(--border-warm)]" />
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label className="label-caps text-xs">Reference (optional)</Label>
              <Input value={form.reference} onChange={(e) => set("reference", e.target.value)}
                     data-testid="cbe-ref"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="label-caps text-xs">Note (optional)</Label>
              <Input value={form.notes} onChange={(e) => set("notes", e.target.value)}
                     data-testid="cbe-notes"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="cbe-save-btn"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Saving…" : entry ? "Update" : "Add entry"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
