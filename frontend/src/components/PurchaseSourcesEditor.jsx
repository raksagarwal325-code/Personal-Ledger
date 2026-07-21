import { useEffect, useMemo, useRef, useState } from "react";
import { api, fmtINR } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { Trash2, Plus, ChevronDown, Search, Shield, Check } from "lucide-react";
import { toast } from "sonner";

const FACTORY_ID = "factory";
const emptyRow = () => ({
  id: crypto.randomUUID?.() || Math.random().toString(36).slice(2),
  supplier_id: "",
  supplier_name: "",
  complete: 0,
  glass: 0,
  fitting: 0,
});

// -------- Supplier combobox (searchable + quick-create) --------
function SupplierCombobox({ value, valueName, sources, onPick, onCreated, testId }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", gstin: "", address: "", notes: "" });
  const inputRef = useRef(null);

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 40); }, [open]);
  useEffect(() => { if (!open) { setQ(""); setShowCreate(false); setForm({ name: "", phone: "", gstin: "", address: "", notes: "" }); } }, [open]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return sources;
    return sources.filter((s) => s.name.toLowerCase().includes(term));
  }, [q, sources]);

  const currentLabel = valueName || sources.find((s) => s.id === value)?.name || "Choose supplier…";
  const currentIsFactory = value === FACTORY_ID;

  const create = async (e) => {
    e?.preventDefault?.();
    const name = form.name.trim();
    if (!name) return toast.error("Enter a vendor name");
    try {
      const r = await api.post("/vendors", { name, phone: form.phone, gstin: form.gstin, address: form.address, notes: form.notes });
      toast.success(`Vendor "${name}" added`);
      onCreated?.();
      onPick({ id: r.data.id, name: r.data.name });
      setOpen(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Could not create vendor");
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button"
                data-testid={testId}
                className={`w-full h-9 flex items-center gap-2 px-3 rounded-md border bg-white text-left text-sm hover:bg-[var(--surface-alt)] transition-colors`}
                style={{ borderColor: "var(--border-warm)" }}>
          {currentIsFactory && <Shield size={12} strokeWidth={2} style={{ color: "var(--terracotta)" }} />}
          <span className={`flex-1 truncate ${value ? "" : "text-[var(--muted)]"}`}>{currentLabel}</span>
          <ChevronDown size={13} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="p-0 w-72" style={{ borderColor: "var(--border-warm)" }}>
        {!showCreate ? (
          <>
            <div className="p-2 border-b relative" style={{ borderColor: "var(--border-warm)" }}>
              <Search size={12} className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
              <Input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
                     placeholder="Search supplier…"
                     data-testid={`${testId}-search`}
                     className="pl-7 h-8 text-sm bg-white border-[var(--border-warm)]" />
            </div>
            <div className="max-h-64 overflow-y-auto py-1">
              {filtered.map((s) => (
                <button key={s.id} type="button"
                        onClick={() => { onPick({ id: s.id, name: s.name }); setOpen(false); }}
                        data-testid={`${testId}-opt-${s.id}`}
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-[var(--surface-alt)] text-left">
                  {s.type === "factory" && <Shield size={12} strokeWidth={2} style={{ color: "var(--terracotta)" }} />}
                  <span className="flex-1 truncate">{s.name}</span>
                  {s.type === "factory" && <span className="text-[10px]" style={{ color: "var(--muted)" }}>protected</span>}
                  {value === s.id && <Check size={12} strokeWidth={2} style={{ color: "var(--sage)" }} />}
                </button>
              ))}
              {filtered.length === 0 && (
                <div className="py-4 text-center text-xs" style={{ color: "var(--muted)" }}>No matching supplier.</div>
              )}
            </div>
            <div className="border-t p-2" style={{ borderColor: "var(--border-warm)" }}>
              <button type="button"
                      onClick={() => { setShowCreate(true); setForm((f) => ({ ...f, name: q })); }}
                      data-testid={`${testId}-add-new`}
                      className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-[var(--surface-alt)] text-sm">
                <Plus size={13} strokeWidth={2} style={{ color: "var(--terracotta)" }} />
                <span>Add new vendor{q ? `: "${q}"` : ""}</span>
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={create} className="p-3 space-y-2" data-testid={`${testId}-create-form`}>
            <div className="text-[10px] label-caps">New vendor</div>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                   placeholder="Vendor name *" autoFocus
                   data-testid={`${testId}-new-name`}
                   className="h-8 text-sm bg-white border-[var(--border-warm)]" />
            <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })}
                   placeholder="Phone"
                   data-testid={`${testId}-new-phone`}
                   className="h-8 text-sm bg-white border-[var(--border-warm)]" />
            <Input value={form.gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value })}
                   placeholder="GSTIN (optional)"
                   className="h-8 text-sm bg-white border-[var(--border-warm)]" />
            <Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })}
                   placeholder="Address (optional)"
                   className="h-8 text-sm bg-white border-[var(--border-warm)]" />
            <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
                   placeholder="Notes (optional)"
                   className="h-8 text-sm bg-white border-[var(--border-warm)]" />
            <div className="flex gap-2 pt-1">
              <Button type="button" variant="outline" onClick={() => setShowCreate(false)}
                      className="border-[var(--border-warm)] h-8 text-xs flex-1">Cancel</Button>
              <Button type="submit"
                      data-testid={`${testId}-create-btn`}
                      className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white h-8 text-xs flex-1">
                Add & pick
              </Button>
            </div>
          </form>
        )}
      </PopoverContent>
    </Popover>
  );
}

// -------- Amount input --------
function AmtInput({ value, onChange, placeholder = "0", testId }) {
  return (
    <div className="relative">
      <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs" style={{ color: "var(--muted)" }}>₹</span>
      <Input type="number" step="0.01"
             value={value === 0 ? "" : (value ?? "")}
             placeholder={placeholder}
             onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
             data-testid={testId}
             className="pl-5 pr-1 h-9 text-right num text-sm bg-white border-[var(--border-warm)]" />
    </div>
  );
}

// -------- Main editor --------
export default function PurchaseSourcesEditor({ item, itemIndex, onChange }) {
  const [sources, setSources] = useState([]);
  const [refreshTick, setRefreshTick] = useState(0);
  const rows = item.purchase_sources || [];

  useEffect(() => {
    api.get("/purchase-sources")
      .then((r) => setSources(r.data.sources || []))
      .catch(() => setSources([{ id: FACTORY_ID, name: "Factory", type: "factory", protected: true }]));
  }, [refreshTick]);

  const updateRow = (rowId, patch) => {
    const next = rows.map((r) => (r.id === rowId ? { ...r, ...patch } : r));
    onChange({ ...item, purchase_sources: next });
  };
  const removeRow = (rowId) => {
    onChange({ ...item, purchase_sources: rows.filter((r) => r.id !== rowId) });
  };
  const addRow = () => {
    onChange({ ...item, purchase_sources: [...rows, emptyRow()] });
  };

  // Row-level validation
  const isRowInvalid = (r) => {
    const total = (r.complete || 0) + (r.glass || 0) + (r.fitting || 0);
    if (total > 0.5 && !r.supplier_id) return true;
    return false;
  };

  const totals = useMemo(() => {
    let c = 0, g = 0, f = 0;
    for (const r of rows) { c += Number(r.complete || 0); g += Number(r.glass || 0); f += Number(r.fitting || 0); }
    return { complete: c, glass: g, fitting: f, total: c + g + f };
  }, [rows]);

  return (
    <div className="space-y-2" data-testid={`purchases-editor-${itemIndex}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] label-caps">Purchases</div>
          <div className="text-[11px] mt-0.5" style={{ color: "var(--muted)" }}>
            One row per supplier. Factory = Father's Firm (settled separately).
          </div>
        </div>
      </div>

      <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border-warm)" }}>
        <div className="grid grid-cols-12 gap-2 px-3 py-2 text-[10px] label-caps"
             style={{ background: "var(--surface-alt)" }}>
          <div className="col-span-5">Purchased from</div>
          <div className="col-span-2 text-right">Complete</div>
          <div className="col-span-2 text-right">Glass</div>
          <div className="col-span-2 text-right">Fitting</div>
          <div className="col-span-1 text-right"></div>
        </div>
        {rows.length === 0 && (
          <div className="p-4 text-xs text-center" style={{ color: "var(--muted)" }}>
            No purchase sources yet.
          </div>
        )}
        {rows.map((row, ri) => (
          <div key={row.id}
               className={`grid grid-cols-12 gap-2 px-3 py-2 items-center border-t ${isRowInvalid(row) ? "bg-[rgba(197,91,67,0.06)]" : ""}`}
               style={{ borderColor: "var(--border-warm)" }}
               data-testid={`purchase-row-${itemIndex}-${ri}`}>
            <div className="col-span-5">
              <SupplierCombobox
                value={row.supplier_id}
                valueName={row.supplier_name}
                sources={sources}
                onPick={({ id, name }) => updateRow(row.id, { supplier_id: id, supplier_name: name })}
                onCreated={() => setRefreshTick((t) => t + 1)}
                testId={`ps-supplier-${itemIndex}-${ri}`}
              />
              {isRowInvalid(row) && (
                <div className="text-[10px] mt-0.5" style={{ color: "var(--terracotta)" }}>
                  Please pick a supplier for this row.
                </div>
              )}
            </div>
            <div className="col-span-2">
              <AmtInput value={row.complete} onChange={(v) => updateRow(row.id, { complete: v })}
                        testId={`ps-complete-${itemIndex}-${ri}`} />
            </div>
            <div className="col-span-2">
              <AmtInput value={row.glass} onChange={(v) => updateRow(row.id, { glass: v })}
                        testId={`ps-glass-${itemIndex}-${ri}`} />
            </div>
            <div className="col-span-2">
              <AmtInput value={row.fitting} onChange={(v) => updateRow(row.id, { fitting: v })}
                        testId={`ps-fitting-${itemIndex}-${ri}`} />
            </div>
            <div className="col-span-1 text-right">
              <button type="button" onClick={() => removeRow(row.id)}
                      data-testid={`ps-remove-${itemIndex}-${ri}`}
                      className="p-1.5 rounded hover:bg-[var(--surface-alt)]"
                      title="Remove this row">
                <Trash2 size={13} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
              </button>
            </div>
          </div>
        ))}
        {/* Footer totals */}
        {rows.length > 0 && (
          <div className="grid grid-cols-12 gap-2 px-3 py-2 border-t text-xs items-center"
               style={{ borderColor: "var(--border-warm)", background: "var(--surface-alt)" }}
               data-testid={`ps-totals-${itemIndex}`}>
            <div className="col-span-5 label-caps text-[10px]">Row totals</div>
            <div className="col-span-2 text-right num">{fmtINR(totals.complete)}</div>
            <div className="col-span-2 text-right num">{fmtINR(totals.glass)}</div>
            <div className="col-span-2 text-right num">{fmtINR(totals.fitting)}</div>
            <div className="col-span-1 text-right num" style={{ color: "var(--sage)" }}>
              {fmtINR(totals.total)}
            </div>
          </div>
        )}
      </div>

      <Button type="button" onClick={addRow}
              data-testid={`ps-add-row-${itemIndex}`}
              variant="outline"
              className="h-8 text-xs gap-1.5 border-[var(--border-warm)]">
        <Plus size={12} /> Add purchase source
      </Button>
    </div>
  );
}
