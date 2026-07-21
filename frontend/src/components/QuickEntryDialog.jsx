import { useState, useEffect, useMemo } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "./ui/select";
import { Switch } from "./ui/switch";
import { api, fmtINR } from "../lib/api";
import { toast } from "sonner";
import { PlusCircle } from "lucide-react";

// Categories the user picks from — mapped to backend keys with descriptions.
const CATEGORIES = [
  { key: "purchase",         label: "Purchase",                 hint: "You bought from this party. Adds to what you owe them." },
  { key: "packing",          label: "Packing charges",          hint: "Adds to what you owe them." },
  { key: "vendor_payment",   label: "Payment to party",         hint: "Money you (or someone on your behalf) paid to this party." },
  { key: "customer_payment", label: "Receipt from party",       hint: "Money received from this party." },
  { key: "sale_invoice",     label: "Sale / invoice raised",    hint: "Adds to what this party owes you." },
  { key: "expense",          label: "Expense on their behalf",  hint: "You paid an expense for this party — they owe you." },
  { key: "income",           label: "Income from party",        hint: "Miscellaneous income received." },
  { key: "advance",          label: "Advance to vendor",        hint: "Paid before invoice — becomes an advance if it exceeds dues." },
  { key: "credit_note",      label: "Credit note",              hint: "Reduces payable to the party." },
  { key: "discount",         label: "Discount",                 hint: "Reduces payable to the party." },
  { key: "purchase_return",  label: "Purchase return",          hint: "Goods sent back — reduces payable." },
  { key: "transfer",         label: "Transfer",                 hint: "Movement between you and this party. No P&L impact." },
  { key: "adjustment",       label: "Manual adjustment",        hint: "Correction / journal — you pick the direction." },
];

const DIRECTIONAL_CATEGORIES = new Set(["transfer", "adjustment"]);
const OUTWARD_CATEGORIES = new Set(["vendor_payment", "purchase", "packing", "expense", "advance"]);
const INWARD_CATEGORIES  = new Set(["customer_payment", "income"]);

export default function QuickEntryDialog({ open, onOpenChange, prefilledParty, onSaved }) {
  const [parties, setParties] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [form, setForm] = useState({
    party_id: "",
    category: "vendor_payment",
    amount: "",
    date: new Date().toISOString().substring(0, 10),
    notes: "",
    direction: "you_pay",
    paid_by_party_id: "",
    received_by_party_id: "",
    split_paid_by_amount: "",
    account_id: "",
    account_name: "",
    reference: "",
    related_order_id: "",
    related_purchase_id: "",
  });
  const [saving, setSaving] = useState(false);

  // Load parties + accounts
  useEffect(() => {
    if (!open) return;
    Promise.all([
      api.get("/party-ledger-v2/parties", { params: { include_settled: true } }),
      api.get("/accounts").catch(() => ({ data: [] })),
    ]).then(([r1, r2]) => {
      setParties(r1.data.parties || []);
      setAccounts(r2.data || []);
    });
  }, [open]);

  // Reset / prefill on open
  useEffect(() => {
    if (!open) return;
    const isCustomer = prefilledParty?.type === "customer";
    setForm((f) => ({
      ...f,
      party_id: prefilledParty?.id || "",
      category: isCustomer ? "customer_payment" : (prefilledParty?.type === "vendor" ? "vendor_payment" : "vendor_payment"),
      amount: "",
      notes: "",
      direction: "you_pay",
      paid_by_party_id: "",
      received_by_party_id: "",
      split_paid_by_amount: "",
      reference: "",
      related_order_id: "",
      related_purchase_id: "",
    }));
  }, [open, prefilledParty]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const selectedParty = useMemo(
    () => parties.find((p) => p.id === form.party_id) || null,
    [parties, form.party_id]
  );
  const paidByParty = useMemo(
    () => parties.find((p) => p.id === form.paid_by_party_id) || null,
    [parties, form.paid_by_party_id]
  );
  const receivedByParty = useMemo(
    () => parties.find((p) => p.id === form.received_by_party_id) || null,
    [parties, form.received_by_party_id]
  );

  const availableForPaidBy = parties.filter((p) => p.type === "fathers_firm" || p.type === "other");
  const availableForReceivedBy = availableForPaidBy;

  const catMeta = CATEGORIES.find((c) => c.key === form.category);
  const showPaidBy = OUTWARD_CATEGORIES.has(form.category);
  const showReceivedBy = INWARD_CATEGORIES.has(form.category);
  const showDirection = DIRECTIONAL_CATEGORIES.has(form.category);

  // Live impact preview
  const impact = useMemo(() => {
    const amt = parseFloat(form.amount || 0);
    if (!amt || !selectedParty) return null;
    const SIGN = {
      purchase: +1, packing: +1, purchase_return: -1,
      sale_invoice: -1, customer_payment: +1, vendor_payment: -1,
      expense: -1, income: +1, advance: -1, credit_note: -1, discount: -1,
    };
    let sign = SIGN[form.category];
    if (sign === undefined) sign = form.direction === "you_pay" ? +1 : -1;
    const delta = sign * amt;
    return delta;
  }, [form, selectedParty]);

  const submit = async (e) => {
    e.preventDefault();
    if (!form.party_id) return toast.error("Pick the party.");
    const amt = parseFloat(form.amount);
    if (!amt || amt <= 0) return toast.error("Enter a positive amount.");
    if (showPaidBy && form.paid_by_party_id && form.paid_by_party_id === form.party_id) {
      return toast.error("Paid-by party cannot be the same as the target party.");
    }
    setSaving(true);
    try {
      const payload = {
        party_id: form.party_id,
        category: form.category,
        amount: amt,
        date: form.date ? new Date(form.date).toISOString() : null,
        notes: form.notes || "",
        paid_by_party_id: showPaidBy && form.paid_by_party_id ? form.paid_by_party_id : null,
        received_by_party_id: showReceivedBy && form.received_by_party_id ? form.received_by_party_id : null,
        direction: showDirection ? form.direction : null,
        account_id: form.account_id || null,
        account_name: form.account_name || "",
        reference: form.reference || "",
        related_order_id: form.related_order_id || null,
        related_purchase_id: form.related_purchase_id || null,
        split_paid_by_amount: form.split_paid_by_amount ? parseFloat(form.split_paid_by_amount) : null,
      };
      const res = await api.post("/party-ledger-v2/transactions", payload);
      const n = (res.data.entries || []).length;
      toast.success(n > 1 ? `Posted ${n} linked entries` : "Transaction posted");
      onSaved?.();
    } catch (err) {
      const msg = err?.response?.data?.detail || "Failed to save transaction";
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="quick-entry-dialog">
        <DialogHeader>
          <DialogTitle className="serif text-2xl flex items-center gap-2">
            <PlusCircle size={18} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
            Quick entry
          </DialogTitle>
          <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
            Post any inter-party transaction. Linked postings (e.g. Father's Firm pays on
            your behalf) create both effects automatically.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="space-y-4 mt-2">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-[10px] label-caps">Party</Label>
              <Select value={form.party_id} onValueChange={(v) => set("party_id", v)}>
                <SelectTrigger data-testid="qe-party" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue placeholder="Pick a party" />
                </SelectTrigger>
                <SelectContent className="max-h-[300px]">
                  {parties.filter((p) => p.type !== "self").map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name} <span className="text-[10px] ml-1" style={{ color: "var(--muted)" }}>({p.type})</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedParty && (
                <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
                  Current: {selectedParty.status} {selectedParty.status !== "Settled" && fmtINR(Math.abs(selectedParty.net_balance || 0))}
                </div>
              )}
            </div>
            <div>
              <Label className="text-[10px] label-caps">Category</Label>
              <Select value={form.category} onValueChange={(v) => set("category", v)}>
                <SelectTrigger data-testid="qe-category" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {catMeta && (
                <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>{catMeta.hint}</div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-[10px] label-caps">Amount</Label>
              <div className="relative mt-1.5">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs" style={{ color: "var(--muted)" }}>₹</span>
                <Input
                  type="number" step="0.01" value={form.amount}
                  onChange={(e) => set("amount", e.target.value)}
                  data-testid="qe-amount" placeholder="0"
                  className="pl-6 bg-white border-[var(--border-warm)] num text-right"
                />
              </div>
            </div>
            <div>
              <Label className="text-[10px] label-caps">Date</Label>
              <Input type="date" value={form.date}
                     onChange={(e) => set("date", e.target.value)}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[10px] label-caps">Reference (optional)</Label>
              <Input value={form.reference}
                     onChange={(e) => set("reference", e.target.value)}
                     data-testid="qe-reference"
                     placeholder="Cheque/UTR/Bill#"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
              <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>Duplicate references are blocked.</div>
            </div>
          </div>

          {/* Directional (transfer / adjustment) */}
          {showDirection && (
            <div className="card-warm p-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="label-caps text-[10px]">Direction</div>
                  <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                    {form.direction === "you_pay"
                      ? "You now owe this party more (money went out)"
                      : "This party now owes you more (money came in)"}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs" style={{ color: form.direction === "you_pay" ? "var(--danger)" : "var(--muted)" }}>You Pay</span>
                  <Switch
                    checked={form.direction === "you_receive"}
                    onCheckedChange={(v) => set("direction", v ? "you_receive" : "you_pay")}
                    data-testid="qe-direction"
                  />
                  <span className="text-xs" style={{ color: form.direction === "you_receive" ? "var(--sage)" : "var(--muted)" }}>You Receive</span>
                </div>
              </div>
            </div>
          )}

          {/* Paid by / Received by */}
          {(showPaidBy || showReceivedBy) && (
            <div className="card-warm p-3 space-y-3">
              {showPaidBy && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-[10px] label-caps">Paid by (leave blank for Rakshit)</Label>
                    <Select value={form.paid_by_party_id || "self"} onValueChange={(v) => set("paid_by_party_id", v === "self" ? "" : v)}>
                      <SelectTrigger data-testid="qe-paid-by" className="mt-1.5 bg-white border-[var(--border-warm)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="self">Rakshit (me)</SelectItem>
                        {availableForPaidBy.map((p) => (
                          <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {paidByParty && (
                      <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
                        A linked entry will be posted on <b>{paidByParty.name}</b>: You Pay +{fmtINR(parseFloat(form.split_paid_by_amount || form.amount || 0))}
                      </div>
                    )}
                  </div>
                  <div>
                    <Label className="text-[10px] label-caps">Split (paid_by portion)</Label>
                    <div className="relative mt-1.5">
                      <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-xs" style={{ color: "var(--muted)" }}>₹</span>
                      <Input
                        type="number" step="0.01" value={form.split_paid_by_amount}
                        onChange={(e) => set("split_paid_by_amount", e.target.value)}
                        disabled={!form.paid_by_party_id}
                        data-testid="qe-split"
                        placeholder="Full amount"
                        className="pl-6 bg-white border-[var(--border-warm)] num text-right"
                      />
                    </div>
                    <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>Leave blank if paid_by covers the full amount.</div>
                  </div>
                </div>
              )}
              {showReceivedBy && (
                <div>
                  <Label className="text-[10px] label-caps">Received by (leave blank for Rakshit)</Label>
                  <Select value={form.received_by_party_id || "self"} onValueChange={(v) => set("received_by_party_id", v === "self" ? "" : v)}>
                    <SelectTrigger data-testid="qe-received-by" className="mt-1.5 bg-white border-[var(--border-warm)]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="self">Rakshit (me)</SelectItem>
                      {availableForReceivedBy.map((p) => (
                        <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {receivedByParty && (
                    <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
                      A linked entry will be posted on <b>{receivedByParty.name}</b>: You Receive +{fmtINR(parseFloat(form.amount || 0))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Account (bank) */}
          {accounts.length > 0 && (showPaidBy || showReceivedBy) && (
            <div>
              <Label className="text-[10px] label-caps">Bank / cash account (optional)</Label>
              <Select value={form.account_id || "none"} onValueChange={(v) => {
                if (v === "none") { set("account_id", ""); set("account_name", ""); return; }
                const a = accounts.find((x) => x.id === v);
                set("account_id", v);
                set("account_name", a?.name || "");
              }}>
                <SelectTrigger data-testid="qe-account" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {accounts.map((a) => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}

          <div>
            <Label className="text-[10px] label-caps">Notes</Label>
            <Textarea rows={2} value={form.notes}
                      onChange={(e) => set("notes", e.target.value)}
                      data-testid="qe-notes"
                      placeholder="Optional context…"
                      className="mt-1.5 bg-white border-[var(--border-warm)]" />
          </div>

          {/* Impact preview */}
          {impact !== null && (
            <div className="rounded-md p-3 text-sm"
                 style={{ background: "var(--surface-alt)", border: "1px solid var(--border-warm)" }}
                 data-testid="qe-impact-preview">
              <span className="label-caps text-[10px] mr-2">Effect on {selectedParty?.name}</span>
              {impact > 0 ? (
                <span style={{ color: "var(--danger)" }}>You Pay +{fmtINR(impact)}</span>
              ) : impact < 0 ? (
                <span style={{ color: "var(--sage)" }}>You Receive +{fmtINR(-impact)}</span>
              ) : (
                <span style={{ color: "var(--muted)" }}>No net change</span>
              )}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}
                    className="border-[var(--border-warm)]">Cancel</Button>
            <Button type="submit" disabled={saving} data-testid="qe-save"
                    className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
              {saving ? "Posting…" : "Post transaction"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
