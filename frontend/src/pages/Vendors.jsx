import { useEffect, useState } from "react";
import { api } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { Plus, Pencil, Trash2, Truck } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "../components/ui/dialog";
import { toast } from "sonner";

const emptyForm = () => ({
  name: "", contact: "", phone: "", email: "", gstin: "", address: "", notes: "",
});

export default function Vendors() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm());

  const load = () => {
    setLoading(true);
    api.get("/vendors").then((r) => setRows(r.data)).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setEditing(null); setForm(emptyForm()); setDialogOpen(true); };
  const openEdit = (v) => { setEditing(v); setForm({ ...emptyForm(), ...v }); setDialogOpen(true); };

  const save = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return toast.error("Vendor name is required.");
    try {
      if (editing?.id) {
        await api.put(`/vendors/${editing.id}`, { ...editing, ...form });
        toast.success("Vendor updated");
      } else {
        await api.post("/vendors", form);
        toast.success("Vendor added");
      }
      setDialogOpen(false);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Failed to save vendor");
    }
  };

  const remove = async (v) => {
    if (!confirm(`Delete vendor "${v.name}"? Their bills will remain but references will show only the name.`)) return;
    try {
      await api.delete(`/vendors/${v.id}`);
      toast.success("Vendor deleted");
      load();
    } catch { toast.error("Failed to delete"); }
  };

  return (
    <div data-testid="vendors-page">
      <PageHeader
        eyebrow="Suppliers &amp; makers"
        title="Vendors"
        subtitle="Contact book for the workshops and shops that supply your parts, glass, fittings and services."
        actions={
          <Button onClick={openNew} data-testid="add-vendor-btn"
                  className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md">
            <Plus size={16} /> New vendor
          </Button>
        }
      />

      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="ledger-table w-full min-w-[720px]" data-testid="vendors-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Contact</th>
                <th>Phone</th>
                <th>GSTIN</th>
                <th>Notes</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-sm" style={{ color: "var(--muted)" }}>
                    <Truck size={22} className="inline-block mb-2" strokeWidth={1.5} />
                    <div>No vendors yet. Click "New vendor" to add your first supplier.</div>
                  </td>
                </tr>
              )}
              {rows.map((v) => (
                <tr key={v.id} data-testid={`vendor-row-${v.id}`}>
                  <td className="font-medium">{v.name}</td>
                  <td style={{ color: "var(--muted)" }}>{v.contact || "—"}</td>
                  <td>{v.phone || "—"}</td>
                  <td className="num" style={{ color: "var(--muted)" }}>{v.gstin || "—"}</td>
                  <td className="max-w-[260px] truncate text-xs" style={{ color: "var(--muted)" }}>{v.notes || ""}</td>
                  <td className="text-right whitespace-nowrap">
                    <button onClick={() => openEdit(v)} data-testid={`edit-vendor-${v.id}`}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                      <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                    </button>
                    <button onClick={() => remove(v)} data-testid={`delete-vendor-${v.id}`}
                            className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1">
                      <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg" data-testid="vendor-dialog">
          <DialogHeader>
            <DialogTitle className="serif text-2xl">{editing ? "Edit vendor" : "New vendor"}</DialogTitle>
            <DialogDescription className="text-xs">
              Contact and tax details for a supplier of parts, glass, fittings or services.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={save} className="space-y-4 mt-2">
            <div>
              <Label className="text-[11px] label-caps">Name*</Label>
              <Input data-testid="v-name" value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     className="mt-1 bg-white border-[var(--border-warm)]" required />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-[11px] label-caps">Contact person</Label>
                <Input data-testid="v-contact" value={form.contact}
                       onChange={(e) => setForm({ ...form, contact: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[11px] label-caps">Phone</Label>
                <Input data-testid="v-phone" value={form.phone}
                       onChange={(e) => setForm({ ...form, phone: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[11px] label-caps">Email</Label>
                <Input data-testid="v-email" value={form.email}
                       onChange={(e) => setForm({ ...form, email: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
              <div>
                <Label className="text-[11px] label-caps">GSTIN</Label>
                <Input data-testid="v-gstin" value={form.gstin}
                       onChange={(e) => setForm({ ...form, gstin: e.target.value })}
                       className="mt-1 bg-white border-[var(--border-warm)]" />
              </div>
            </div>
            <div>
              <Label className="text-[11px] label-caps">Address</Label>
              <Input data-testid="v-address" value={form.address}
                     onChange={(e) => setForm({ ...form, address: e.target.value })}
                     className="mt-1 bg-white border-[var(--border-warm)]" />
            </div>
            <div>
              <Label className="text-[11px] label-caps">Notes</Label>
              <Textarea data-testid="v-notes" value={form.notes} rows={2}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })}
                        className="mt-1 bg-white border-[var(--border-warm)]" />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}
                      className="border-[var(--border-warm)]">Cancel</Button>
              <Button type="submit" data-testid="v-save-btn"
                      className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white">
                {editing ? "Update" : "Add"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
