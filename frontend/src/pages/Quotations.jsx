import { useEffect, useState, useMemo, Fragment } from "react";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Plus, Search, Trash2, Pencil, Copy, Eye, FileText } from "lucide-react";
import QuotationDialog from "../components/QuotationDialog";
import QuotationPreview from "../components/QuotationPreview";
import { toast } from "sonner";

const STATUS_STYLE = {
  Draft:      { bg: "rgba(122,117,113,0.15)", fg: "var(--muted)" },
  Sent:       { bg: "rgba(74,109,124,0.15)",  fg: "#4A6D7C" },
  Accepted:   { bg: "rgba(58,90,64,0.12)",    fg: "var(--sage)" },
  Rejected:   { bg: "rgba(188,71,73,0.12)",   fg: "var(--danger)" },
  Converted:  { bg: "rgba(212,163,115,0.2)",  fg: "#8a5a2c" },
};

export default function Quotations() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [previewing, setPreviewing] = useState(null);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");

  const load = () => {
    setLoading(true);
    const params = {};
    if (status !== "all") params.status = status;
    if (search) params.search = search;
    api.get("/quotations", { params })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [status]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);

  const totals = useMemo(() => rows.reduce(
    (a, q) => ({
      count: a.count + 1,
      subtotal: a.subtotal + (q.subtotal || 0),
      tax: a.tax + (q.tax_amount || 0),
      total: a.total + (q.total || 0),
      accepted: a.accepted + (q.status === "Accepted" || q.status === "Converted" ? (q.total || 0) : 0),
    }),
    { count: 0, subtotal: 0, tax: 0, total: 0, accepted: 0 }
  ), [rows]);

  const openNew = () => { setEditing(null); setDialogOpen(true); };
  const openEdit = (q) => { setEditing(q); setDialogOpen(true); };
  const openPreview = (q) => { setPreviewing(q); setPreviewOpen(true); };

  const handleDelete = async (q, e) => {
    e?.stopPropagation();
    if (!confirm(`Delete quotation ${q.quote_number}?`)) return;
    try {
      await api.delete(`/quotations/${q.id}`);
      toast.success("Quotation deleted");
      load();
    } catch {
      toast.error("Could not delete quotation");
    }
  };

  const handleDuplicate = async (q, e) => {
    e?.stopPropagation();
    try {
      const r = await api.post(`/quotations/${q.id}/duplicate`);
      toast.success(`Duplicated as ${r.data.quote_number}`);
      load();
    } catch {
      toast.error("Could not duplicate");
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="Sales"
        title="Quotations"
        subtitle="Draft, share and track quotations. When accepted, one click converts them into an order in the ledger."
        actions={
          <Button
            onClick={openNew}
            data-testid="add-quotation-btn"
            className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md"
          >
            <Plus size={16} /> New quotation
          </Button>
        }
      />

      {/* Filters */}
      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <div className="relative lg:col-span-3">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input
            value={search}
            data-testid="quot-search"
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by client or quote number…"
            className="pl-9 bg-white border-[var(--border-warm)]"
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger data-testid="quot-status" className="bg-white border-[var(--border-warm)] lg:col-span-2">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="Draft">Draft</SelectItem>
            <SelectItem value="Sent">Sent</SelectItem>
            <SelectItem value="Accepted">Accepted</SelectItem>
            <SelectItem value="Rejected">Rejected</SelectItem>
            <SelectItem value="Converted">Converted</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Quotations</div>
          <div className="serif text-2xl num mt-1" data-testid="quot-count">{totals.count}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Value quoted</div>
          <div className="serif text-2xl num mt-1">{fmtINR(totals.total)}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Tax quoted</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--muted)" }}>{fmtINR(totals.tax)}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Accepted / converted</div>
          <div className="serif text-2xl num mt-1" style={{ color: "var(--sage)" }}>{fmtINR(totals.accepted)}</div>
        </div>
      </div>

      {/* Table */}
      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto max-h-[70vh]">
          <table className="ledger-table w-full min-w-[900px]" data-testid="quotations-table">
            <thead>
              <tr>
                <th>Quote #</th>
                <th>Date</th>
                <th>Client</th>
                <th>Items</th>
                <th className="num">Subtotal</th>
                <th className="num">Tax</th>
                <th className="num">Total</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="9" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan="9" className="text-center py-12 text-sm" style={{ color: "var(--muted)" }}>
                    <FileText size={22} className="mx-auto mb-2 opacity-60" strokeWidth={1.5} />
                    <div>No quotations yet.</div>
                    <div className="mt-1">Click <b>New quotation</b> to draft your first quote.</div>
                  </td>
                </tr>
              )}
              {rows.map((q) => {
                const st = STATUS_STYLE[q.status] || STATUS_STYLE.Draft;
                return (
                  <Fragment key={q.id}>
                    <tr
                      onClick={() => openPreview(q)}
                      className="cursor-pointer"
                      data-testid={`quot-row-${q.id}`}
                    >
                      <td className="font-medium whitespace-nowrap">{q.quote_number}</td>
                      <td className="whitespace-nowrap">{fmtDate(q.quote_date)}</td>
                      <td className="max-w-[220px] truncate">{q.client_name || "—"}</td>
                      <td>
                        <span className="text-xs" style={{ color: "var(--muted)" }}>
                          {(q.items || []).length} {(q.items || []).length === 1 ? "line" : "lines"}
                        </span>
                      </td>
                      <td className="num" style={{ color: "var(--muted)" }}>{fmtINR(q.subtotal)}</td>
                      <td className="num" style={{ color: "var(--muted)" }}>{fmtINR(q.tax_amount)}</td>
                      <td className="num font-medium">{fmtINR(q.total)}</td>
                      <td>
                        <span
                          className="inline-block px-2 py-0.5 rounded-full text-xs font-medium"
                          style={{ background: st.bg, color: st.fg }}
                        >
                          {q.status}
                        </span>
                      </td>
                      <td className="text-right whitespace-nowrap">
                        <button
                          onClick={(e) => { e.stopPropagation(); openPreview(q); }}
                          data-testid={`preview-quot-${q.id}`}
                          title="Preview & print"
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)]"
                        >
                          <Eye size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); openEdit(q); }}
                          data-testid={`edit-quot-${q.id}`}
                          title="Edit"
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1"
                        >
                          <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                        </button>
                        <button
                          onClick={(e) => handleDuplicate(q, e)}
                          data-testid={`dup-quot-${q.id}`}
                          title="Duplicate"
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1"
                        >
                          <Copy size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                        </button>
                        <button
                          onClick={(e) => handleDelete(q, e)}
                          data-testid={`del-quot-${q.id}`}
                          title="Delete"
                          className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1"
                        >
                          <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                        </button>
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <QuotationDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        quotation={editing}
        onSaved={() => { load(); setDialogOpen(false); }}
      />

      <QuotationPreview
        open={previewOpen}
        onOpenChange={setPreviewOpen}
        quotation={previewing}
        onEdit={() => { setEditing(previewing); setPreviewOpen(false); setDialogOpen(true); }}
      />
    </div>
  );
}
