import { useEffect, useState } from "react";
import { api } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Plus, Pencil, Archive, ArchiveRestore, Banknote, Wallet, Smartphone, CreditCard } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "../components/ui/dialog";
import { toast } from "sonner";

const TYPE_META = {
  Bank:      { icon: Banknote,   label: "Bank" },
  Cash:      { icon: Wallet,     label: "Cash" },
  PettyCash: { icon: Wallet,     label: "Petty Cash" },
  UPI:       { icon: Smartphone, label: "UPI" },
  Wallet:    { icon: Smartphone, label: "Wallet" },
  Gateway:   { icon: CreditCard, label: "Gateway" },
  Other:     { icon: Wallet,     label: "Other" },
};

export default function Accounts() {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showArchived, setShowArchived] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", type: "Bank", notes: "" });

  const load = () => {
    setLoading(true);
    api.get("/accounts", { params: { include_archived: showArchived } })
      .then((r) => setAccounts(r.data))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [showArchived]);

  const openNew = () => {
    setEditing(null);
    setForm({ name: "", type: "Bank", notes: "" });
    setDialogOpen(true);
  };
  const openEdit = (a) => {
    setEditing(a);
    setForm({ name: a.name, type: a.type, notes: a.notes || "" });
    setDialogOpen(true);
  };

  const save = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return toast.error("Please enter a name.");
    try {
      if (editing) {
        await api.put(`/accounts/${editing.id}`, { ...editing, ...form });
        toast.success("Account updated");
      } else {
        await api.post("/accounts", form);
        toast.success("Account added");
      }
      setDialogOpen(false);
      load();
    } catch { toast.error("Failed to save."); }
  };

  const toggleArchive = async (a) => {
    await api.post(`/accounts/${a.id}/archive`, null, { params: { archived: !a.archived } });
    toast.success(a.archived ? "Restored" : "Archived");
    load();
  };

  const active = accounts.filter((a) => !a.archived);
  const archived = accounts.filter((a) => a.archived);

  return (
    <div>
      <PageHeader
        eyebrow="Settings"
        title="Accounts"
        subtitle="Where money flows in and out. These accounts appear in every payment dropdown across the app."
        actions={
          <Button onClick={openNew} data-testid="add-account-btn"
                  className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md">
            <Plus size={16} /> Add account
          </Button>
        }
      />

      <div className="mb-4 flex items-center gap-4 text-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showArchived}
                 onChange={(e) => setShowArchived(e.target.checked)}
                 data-testid="toggle-archived" />
          <span style={{ color: "var(--muted)" }}>Show archived</span>
        </label>
        <span className="text-xs" style={{ color: "var(--muted)" }}>
          {active.length} active{showArchived && archived.length > 0 ? ` · ${archived.length} archived` : ""}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="accounts-grid">
        {loading && <div className="text-sm" style={{ color: "var(--muted)" }}>Loading…</div>}
        {!loading && accounts.length === 0 && (
          <div className="col-span-full card-warm p-10 text-center text-sm"
               style={{ color: "var(--muted)" }}>
            No accounts yet. Click Add account to create your first one.
          </div>
        )}
        {accounts.map((a) => {
          const meta = TYPE_META[a.type] || TYPE_META.Other;
          const Icon = meta.icon;
          return (
            <div key={a.id}
                 className={`card-warm p-5 relative ${a.archived ? "opacity-60" : ""}`}
                 data-testid={`account-${a.id}`}>
              <div className="flex items-start gap-3 mb-3">
                <div className="p-2.5 rounded-md" style={{ background: "var(--surface-alt)" }}>
                  <Icon size={18} strokeWidth={1.5} style={{ color: "var(--terracotta)" }} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="serif text-xl truncate">{a.name}</div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
                    {meta.label}{a.archived ? " · archived" : ""}
                  </div>
                </div>
              </div>
              {a.notes && (
                <div className="text-xs mb-3" style={{ color: "var(--muted)" }}>{a.notes}</div>
              )}
              <div className="flex gap-2">
                <button onClick={() => openEdit(a)} data-testid={`edit-account-${a.id}`}
                        className="text-xs flex items-center gap-1 px-2 py-1 rounded hover:bg-[var(--surface-alt)]"
                        style={{ color: "var(--muted)" }}>
                  <Pencil size={12} /> Edit
                </button>
                <button onClick={() => toggleArchive(a)} data-testid={`archive-account-${a.id}`}
                        className="text-xs flex items-center gap-1 px-2 py-1 rounded hover:bg-[var(--surface-alt)]"
                        style={{ color: a.archived ? "var(--sage)" : "var(--muted)" }}>
                  {a.archived ? <><ArchiveRestore size={12} /> Restore</> : <><Archive size={12} /> Archive</>}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 card-warm p-5 max-w-3xl text-xs" style={{ color: "var(--muted)" }}>
        <div className="label-caps mb-2">Note</div>
        This is a reference master, not a bank ledger. Selecting an account on a payment only tags where the
        business receipt was received. The app does not track or reconcile actual bank balances — personal
        transactions outside the app are not visible here.
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md" data-testid="account-dialog">
          <DialogHeader>
            <DialogTitle className="serif text-2xl">
              {editing ? "Edit account" : "New account"}
            </DialogTitle>
            <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
              Add a bank, wallet, UPI or cash bucket where business payments arrive or are paid from.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-4 mt-2">
            <div>
              <Label className="text-[10px] label-caps">Name</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="e.g. ICICI Current"
                     data-testid="acc-name"
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[10px] label-caps">Type</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="acc-type" className="mt-1.5 bg-white border-[var(--border-warm)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(TYPE_META).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-[10px] label-caps">Notes (optional)</Label>
              <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
                     className="mt-1.5 bg-white border-[var(--border-warm)]" />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}
                      className="border-[var(--border-warm)]">Cancel</Button>
              <Button type="submit" data-testid="acc-save-btn"
                      className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
                {editing ? "Update" : "Add account"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
