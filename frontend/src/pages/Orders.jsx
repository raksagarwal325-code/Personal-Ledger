import { useEffect, useState, useMemo, Fragment } from "react";
import { useSearchParams } from "react-router-dom";
import { api, fmtINR, fmtDate } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Plus, Search, Trash2, Pencil, ChevronDown, ChevronRight, Package, Truck } from "lucide-react";
import OrderDialog from "../components/OrderDialog";
import { toast } from "sonner";

const STATUS_STYLE = {
  "Draft":             { bg: "rgba(122,117,113,0.15)", fg: "var(--muted)" },
  "Confirmed":         { bg: "rgba(74,109,124,0.15)",  fg: "#4A6D7C" },
  "Packed":            { bg: "rgba(212,163,115,0.2)",  fg: "#8a5a2c" },
  "Partially Shipped": { bg: "rgba(197,91,67,0.15)",   fg: "var(--terracotta)" },
  "Fully Shipped":     { bg: "rgba(58,90,64,0.12)",    fg: "var(--sage)" },
  "Delivered":         { bg: "rgba(58,90,64,0.18)",    fg: "var(--sage)" },
  "Cancelled":         { bg: "rgba(188,71,73,0.12)",   fg: "var(--danger)" },
};

const PAY_STYLE = {
  Paid:    { bg: "rgba(58,90,64,0.12)",   fg: "var(--sage)" },
  Partial: { bg: "rgba(212,163,115,0.2)", fg: "#8a5a2c" },
  Unpaid:  { bg: "rgba(188,71,73,0.12)",  fg: "var(--danger)" },
};

export default function Orders() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [status, setStatus] = useState(searchParams.get("payment_status") || "all");
  const [mainCat, setMainCat] = useState(searchParams.get("main_category") || "all");
  const [search, setSearch] = useState(searchParams.get("client_name") || "");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [meta, setMeta] = useState({ main_categories: [] });

  useEffect(() => {
    api.get("/meta").then((r) => setMeta(r.data));
  }, []);

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setEditing(null);
      setDialogOpen(true);
      searchParams.delete("new");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const load = () => {
    setLoading(true);
    const params = {};
    if (status !== "all") params.payment_status = status;
    if (mainCat !== "all") params.main_category = mainCat;
    if (search) params.client_name = search;
    if (startDate) params.start_date = new Date(startDate).toISOString();
    if (endDate) params.end_date = new Date(endDate).toISOString();
    api.get("/orders", { params })
      .then((r) => setOrders(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [status, mainCat, startDate, endDate]);
  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line
  }, [search]);

  const totals = useMemo(() => orders.reduce(
    (a, o) => ({
      revenue: a.revenue + (o.operating_revenue || 0),
      cost: a.cost + (o.total_cost || 0),
      profit: a.profit + (o.net_profit || 0),
      invoice: a.invoice + (o.invoice_total || 0),
      received: a.received + (o.total_received || 0),
      outstanding: a.outstanding + (o.outstanding_balance || 0),
      est_revenue: a.est_revenue + (o.estimated_operating_revenue || o.operating_revenue || 0),
      est_profit: a.est_profit + (o.estimated_net_profit || o.net_profit || 0),
      unrealized_profit: a.unrealized_profit + (o.unrealized_net_profit || 0),
    }),
    { revenue: 0, cost: 0, profit: 0, invoice: 0, received: 0, outstanding: 0,
      est_revenue: 0, est_profit: 0, unrealized_profit: 0 }
  ), [orders]);

  const toggle = (id) => setExpanded((prev) => {
    const n = new Set(prev);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const handleDelete = async (id, e) => {
    e?.stopPropagation();
    if (!confirm("Delete this order?")) return;
    await api.delete(`/orders/${id}`);
    toast.success("Order deleted");
    load();
  };

  const handleEdit = (o, e) => {
    e?.stopPropagation();
    setEditing(o);
    setDialogOpen(true);
  };

  return (
    <div>
      <PageHeader
        eyebrow="Order book"
        title="Orders"
        subtitle="One row per shipment. Click any order to see its products and cost breakdown."
        actions={
          <Button onClick={() => { setEditing(null); setDialogOpen(true); }}
                  data-testid="add-order-btn"
                  className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2 rounded-md">
            <Plus size={16} /> New order
          </Button>
        }
      />

      {/* Filters */}
      <div className="card-warm p-4 md:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <div className="relative lg:col-span-2">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" />
          <Input value={search} data-testid="filter-search"
                 onChange={(e) => setSearch(e.target.value)} placeholder="Search client…"
                 className="pl-9 bg-white border-[var(--border-warm)]" />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger data-testid="filter-status" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Payment status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="Unpaid">Unpaid</SelectItem>
            <SelectItem value="Partial">Partial</SelectItem>
            <SelectItem value="Paid">Paid</SelectItem>
          </SelectContent>
        </Select>
        <Select value={mainCat} onValueChange={setMainCat}>
          <SelectTrigger data-testid="filter-main-cat" className="bg-white border-[var(--border-warm)]">
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All categories</SelectItem>
            {(meta.main_categories || []).map((c) => (
              <SelectItem key={c} value={c}>{c}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
               className="bg-white border-[var(--border-warm)]" />
        <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
               className="bg-white border-[var(--border-warm)]" />
      </div>

      {/* Totals */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Orders</div>
          <div className="serif text-2xl num mt-1" data-testid="orders-total-count">{orders.length}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Operating Revenue</div>
          <div className="serif text-2xl num mt-1" data-testid="orders-total-rev">{fmtINR(totals.revenue)}</div>
          <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
            realized · est {fmtINR(totals.est_revenue)}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Invoice value</div>
          <div className="serif text-2xl num mt-1">{fmtINR(totals.invoice)}</div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Realized Profit</div>
          <div className="serif text-2xl num mt-1"
               style={{ color: totals.profit >= 0 ? "var(--sage)" : "var(--danger)" }}
               data-testid="orders-total-profit">
            {fmtINR(totals.profit)}
          </div>
          <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}
               data-testid="orders-total-est-profit">
            est {fmtINR(totals.est_profit)}
            {totals.unrealized_profit > 0.5 && (
              <span style={{ color: "var(--terracotta)" }}>
                {" · "}unrealized {fmtINR(totals.unrealized_profit)}
              </span>
            )}
          </div>
        </div>
        <div className="card-warm px-5 py-4">
          <div className="label-caps">Outstanding</div>
          <div className="serif text-2xl num mt-1"
               style={{ color: totals.outstanding > 0.5 ? "var(--terracotta)" : "var(--sage)" }}
               data-testid="orders-total-outstanding">
            {fmtINR(totals.outstanding)}
          </div>
          <div className="text-[10px] mt-1" style={{ color: "var(--muted)" }}>
            Received {fmtINR(totals.received)}
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card-warm overflow-hidden">
        <div className="overflow-x-auto max-h-[70vh]">
          <table className="ledger-table w-full min-w-[1180px]" data-testid="orders-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}></th>
                <th>Date</th>
                <th>Client</th>
                <th>Items</th>
                <th className="num">Realized Rev</th>
                <th className="num">Est. Rev</th>
                <th className="num">Total Cost</th>
                <th className="num">Realized Profit</th>
                <th className="num">Est. Profit</th>
                <th className="num">Outstanding</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan="12" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>Loading…</td></tr>
              )}
              {!loading && orders.length === 0 && (
                <tr><td colSpan="12" className="text-center py-10 text-sm" style={{ color: "var(--muted)" }}>
                  No orders yet. Click "New order" to create one.
                </td></tr>
              )}
              {orders.map((o) => {
                const isOpen = expanded.has(o.id);
                const s = STATUS_STYLE[o.status] || STATUS_STYLE["Confirmed"];
                const ps = PAY_STYLE[o.payment_status] || PAY_STYLE.Unpaid;
                return (
                  <Fragment key={o.id}>
                    <tr onClick={() => toggle(o.id)} className="cursor-pointer"
                        data-testid={`order-row-${o.id}`}>
                      <td>
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded"
                              style={{ background: isOpen ? "var(--surface-alt)" : "transparent",
                                       color: "var(--muted)" }}>
                          {isOpen
                            ? <ChevronDown size={14} strokeWidth={1.75} />
                            : <ChevronRight size={14} strokeWidth={1.75} />}
                        </span>
                      </td>
                      <td className="whitespace-nowrap">{fmtDate(o.last_shipped_date || o.shipped_date || o.order_date)}</td>
                      <td className="max-w-[220px] truncate font-medium">{o.client_name || "—"}</td>
                      <td>
                        <span className="inline-flex items-center gap-1.5 text-xs"
                              style={{ color: "var(--terracotta)" }}>
                          <Package size={12} strokeWidth={1.75} />
                          <span className="font-medium">{(o.items || []).length}</span>
                          <span style={{ color: "var(--muted)" }}>
                            {(o.items || []).length === 1 ? "Product" : "Products"}
                          </span>
                        </span>
                        {o.ordered_qty_total > 0 && (
                          <div className="text-[10px] mt-0.5" style={{ color: "var(--muted)" }}>
                            {o.shipped_qty_total || 0}/{o.ordered_qty_total} qty · {(o.shipment_progress_percent || 0).toFixed(0)}%
                          </div>
                        )}
                      </td>
                      <td className="num font-medium">{fmtINR(o.operating_revenue)}</td>
                      <td className="num" style={{ color: "var(--muted)" }}
                          data-testid={`order-est-rev-${o.id}`}>
                        {fmtINR(o.estimated_operating_revenue || o.operating_revenue || 0)}
                      </td>
                      <td className="num" style={{ color: "var(--muted)" }}>{fmtINR(o.total_cost)}</td>
                      <td className="num font-medium"
                          style={{ color: o.net_profit >= 0 ? "var(--sage)" : "var(--danger)" }}>
                        {fmtINR(o.net_profit)}
                      </td>
                      <td className="num"
                          style={{ color: "var(--muted)" }}
                          data-testid={`order-est-profit-${o.id}`}>
                        {fmtINR(o.estimated_net_profit || o.net_profit || 0)}
                        {(o.unrealized_net_profit || 0) > 0.5 && (
                          <div className="text-[10px] mt-0.5"
                               style={{ color: "var(--terracotta)" }}>
                            +{fmtINR(o.unrealized_net_profit)} unrealized
                          </div>
                        )}
                      </td>
                      <td className="num"
                          style={{ color: (o.outstanding_balance || 0) > 0.5 ? "var(--terracotta)" : "var(--muted)" }}>
                        {fmtINR(o.outstanding_balance || 0)}
                      </td>
                      <td>
                        <div className="flex flex-col gap-1">
                          <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium"
                                style={{ background: s.bg, color: s.fg }}>
                            {o.status || "—"}
                          </span>
                          <span className="inline-block px-2 py-0.5 rounded-full text-[10px]"
                                style={{ background: ps.bg, color: ps.fg }}>
                            {o.payment_status || "—"}
                          </span>
                        </div>
                      </td>
                      <td className="text-right whitespace-nowrap">
                        <button onClick={(e) => { e.stopPropagation(); setEditing(o); setDialogOpen(true); }}
                                data-testid={`add-shipment-${o.id}`}
                                title="Manage shipments"
                                className="p-1.5 rounded hover:bg-[var(--surface-alt)]">
                          <Truck size={14} strokeWidth={1.75} style={{ color: "var(--terracotta)" }} />
                        </button>
                        <button onClick={(e) => handleEdit(o, e)} data-testid={`edit-order-${o.id}`}
                                className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1">
                          <Pencil size={14} strokeWidth={1.75} style={{ color: "var(--muted)" }} />
                        </button>
                        <button onClick={(e) => handleDelete(o.id, e)} data-testid={`delete-order-${o.id}`}
                                className="p-1.5 rounded hover:bg-[var(--surface-alt)] ml-1">
                          <Trash2 size={14} strokeWidth={1.75} style={{ color: "var(--danger)" }} />
                        </button>
                      </td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={12} className="p-0" style={{ background: "var(--surface-alt)" }}>
                          <div className="px-6 py-5">
                            {/* Phase 4 — Revenue recognition */}
                            <div className="rounded-md bg-white p-4 border mb-5"
                                 style={{ borderColor: "var(--border-warm)" }}
                                 data-testid={`order-rev-recognition-${o.id}`}>
                              <div className="flex items-center justify-between mb-3">
                                <div className="label-caps">Revenue recognition</div>
                                <div className="text-xs" style={{ color: "var(--muted)" }}>
                                  {o.shipped_qty_total || 0} of {o.ordered_qty_total || 0} qty shipped
                                  {" · "}{(o.shipment_progress_percent || 0).toFixed(0)}%
                                </div>
                              </div>
                              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                                <div>
                                  <div className="text-xs" style={{ color: "var(--muted)" }}>Realized revenue</div>
                                  <div className="serif text-lg num mt-0.5">{fmtINR(o.operating_revenue || 0)}</div>
                                </div>
                                <div>
                                  <div className="text-xs" style={{ color: "var(--muted)" }}>Estimated revenue</div>
                                  <div className="serif text-lg num mt-0.5">
                                    {fmtINR(o.estimated_operating_revenue || o.operating_revenue || 0)}
                                  </div>
                                </div>
                                <div>
                                  <div className="text-xs" style={{ color: "var(--muted)" }}>Realized profit</div>
                                  <div className="serif text-lg num mt-0.5"
                                       style={{ color: (o.net_profit || 0) >= 0 ? "var(--sage)" : "var(--danger)" }}>
                                    {fmtINR(o.net_profit || 0)}
                                  </div>
                                  <div className="text-[10px] mt-0.5" style={{ color: "var(--muted)" }}>
                                    {(o.margin_percent || 0).toFixed(1)}% margin
                                  </div>
                                </div>
                                <div>
                                  <div className="text-xs" style={{ color: "var(--muted)" }}>Estimated profit</div>
                                  <div className="serif text-lg num mt-0.5"
                                       style={{ color: (o.estimated_net_profit || 0) >= 0 ? "var(--sage)" : "var(--danger)" }}>
                                    {fmtINR(o.estimated_net_profit || o.net_profit || 0)}
                                  </div>
                                  <div className="text-[10px] mt-0.5" style={{ color: "var(--muted)" }}>
                                    {(o.estimated_margin_percent || 0).toFixed(1)}% margin
                                  </div>
                                </div>
                              </div>
                              {(o.unrealized_net_profit || 0) > 0.5 && (
                                <div className="mt-3 pt-3 border-t text-xs"
                                     style={{ borderColor: "var(--border-warm)", color: "var(--terracotta)" }}>
                                  Unrealized profit still to book once remaining shipments complete:{" "}
                                  <span className="font-medium">{fmtINR(o.unrealized_net_profit)}</span>
                                  {(o.unrealized_revenue || 0) > 0 && (
                                    <span style={{ color: "var(--muted)" }}>
                                      {" · "}on {fmtINR(o.unrealized_revenue)} of pending revenue
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-5 text-sm">
                              <div>
                                <div className="label-caps">Product sales</div>
                                <div className="serif text-lg num mt-1">{fmtINR(o.product_sales_total)}</div>
                                {(o.other_revenue_total || 0) > 0 && (
                                  <div className="text-xs mt-1" style={{ color: "var(--sage)" }}>
                                    + {fmtINR(o.other_revenue_total)} other revenue
                                  </div>
                                )}
                              </div>
                              <div>
                                <div className="label-caps">Packing</div>
                                <div className="serif text-lg num mt-1">
                                  {fmtINR(o.packing_cost)}{" "}
                                  {o.boxes_used > 0 && (
                                    <span className="text-xs font-normal" style={{ color: "var(--muted)" }}>
                                      · {o.boxes_used} boxes
                                    </span>
                                  )}
                                </div>
                                {(o.packing_recovery || 0) > 0 && (
                                  <div className="text-xs" style={{ color: "var(--sage)" }}>
                                    + {fmtINR(o.packing_recovery)} charged
                                  </div>
                                )}
                              </div>
                              <div>
                                <div className="label-caps">Freight</div>
                                <div className="serif text-lg num mt-1" style={{ color: "var(--muted)" }}>
                                  {fmtINR(o.freight_paid)} paid
                                </div>
                                {o.freight_charged > 0 && (
                                  <div className="text-xs" style={{ color: "var(--sage)" }}>
                                    + {fmtINR(o.freight_charged)} charged
                                  </div>
                                )}
                                {o.transporter && (
                                  <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
                                    via {o.transporter}
                                  </div>
                                )}
                              </div>
                              <div>
                                <div className="label-caps">Tax</div>
                                <div className="serif text-lg num mt-1">
                                  {o.tax_applicable ? fmtINR(o.tax_amount) : "—"}
                                </div>
                                {o.tax_applicable && (
                                  <div className="text-xs" style={{ color: "var(--muted)" }}>
                                    {o.tax_type} @ {o.tax_percent}%
                                    {o.tax_amount_manual && (
                                      <span className="ml-1" style={{ color: "#8a5a2c" }}>· manual</span>
                                    )}
                                  </div>
                                )}
                                {(o.other_expense_total || 0) > 0 && (
                                  <div className="text-xs mt-1" style={{ color: "var(--terracotta)" }}>
                                    + {fmtINR(o.other_expense_total)} other expense
                                  </div>
                                )}
                              </div>
                            </div>

                            {((o.other_revenue || []).length > 0 || (o.other_expense || []).length > 0) && (
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
                                {(o.other_revenue || []).length > 0 && (
                                  <div className="rounded-md bg-white p-4 border"
                                       style={{ borderColor: "var(--border-warm)" }}>
                                    <div className="label-caps mb-2" style={{ color: "var(--sage)" }}>Other revenue</div>
                                    {o.other_revenue.map((r) => (
                                      <div key={r.id} className="flex justify-between text-sm py-1">
                                        <span>{r.description || "—"}</span>
                                        <span className="num">{fmtINR(r.amount)}</span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                                {(o.other_expense || []).length > 0 && (
                                  <div className="rounded-md bg-white p-4 border"
                                       style={{ borderColor: "var(--border-warm)" }}>
                                    <div className="label-caps mb-2" style={{ color: "var(--terracotta)" }}>Other expense</div>
                                    {o.other_expense.map((r) => (
                                      <div key={r.id} className="flex justify-between text-sm py-1">
                                        <span>{r.description || "—"}</span>
                                        <span className="num">{fmtINR(r.amount)}</span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}

                            {((o.order_payments || []).length > 0) && (
                              <div className="rounded-md bg-white p-4 border mb-5"
                                   style={{ borderColor: "var(--border-warm)" }}>
                                <div className="flex items-center justify-between mb-2">
                                  <div className="label-caps">Payments received</div>
                                  <div className="text-xs" style={{ color: "var(--muted)" }}>
                                    {fmtINR(o.total_received || 0)} of {fmtINR(o.invoice_total || 0)}
                                    {" · "}
                                    <span style={{ color: (o.outstanding_balance || 0) > 0.5 ? "var(--terracotta)" : "var(--sage)" }}>
                                      outstanding {fmtINR(o.outstanding_balance || 0)}
                                    </span>
                                  </div>
                                </div>
                                <div className="space-y-1">
                                  {o.order_payments.map((p) => (
                                    <div key={p.id} className="flex justify-between text-sm py-1 border-b last:border-b-0"
                                         style={{ borderColor: "var(--border-warm)" }}>
                                      <div className="flex-1">
                                        <span>{fmtDate(p.date)}</span>
                                        <span className="mx-2" style={{ color: "var(--muted)" }}>·</span>
                                        <span>{p.mode}</span>
                                        {p.account_name && (
                                          <>
                                            <span className="mx-2" style={{ color: "var(--muted)" }}>→</span>
                                            <span style={{ color: "var(--muted)" }}>{p.account_name}</span>
                                          </>
                                        )}
                                        {p.reference && (
                                          <span className="ml-2 text-xs" style={{ color: "var(--muted)" }}>
                                            #{p.reference}
                                          </span>
                                        )}
                                      </div>
                                      <div className="num font-medium" style={{ color: "var(--sage)" }}>
                                        {fmtINR(p.amount)}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            <div className="rounded-md overflow-hidden bg-white border"
                                 style={{ borderColor: "var(--border-warm)" }}>
                              <table className="ledger-table w-full">
                                <thead>
                                  <tr>
                                    <th>Main / Sub</th>
                                    <th>Product</th>
                                    <th className="num">Qty</th>
                                    <th className="num">Rate</th>
                                    <th className="num">Sales</th>
                                    <th className="num">Factory</th>
                                    <th className="num">Outside</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {(o.items || []).map((it) => {
                                    const fac = (it.factory_complete || 0) + (it.factory_glass || 0) + (it.factory_fitting || 0);
                                    const out = (it.outside_complete || 0) + (it.outside_glass || 0) + (it.outside_fitting || 0);
                                    return (
                                      <tr key={it.id}>
                                        <td>
                                          <div className="text-sm">{it.main_category}</div>
                                          {it.sub_category && (
                                            <div className="text-xs" style={{ color: "var(--muted)" }}>
                                              {it.sub_category}
                                            </div>
                                          )}
                                        </td>
                                        <td className="max-w-[240px] truncate">{it.product_name}</td>
                                        <td className="num">{it.qty}</td>
                                        <td className="num">{fmtINR(it.rate)}</td>
                                        <td className="num font-medium">{fmtINR(it.product_sales)}</td>
                                        <td className="num" style={{ color: "var(--muted)" }}>{fmtINR(fac)}</td>
                                        <td className="num" style={{ color: "var(--muted)" }}>{fmtINR(out)}</td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>

                            {o.notes && (
                              <div className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
                                <span className="label-caps mr-2">Notes</span> {o.notes}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
            {orders.length > 0 && !loading && (
              <tfoot>
                <tr style={{ background: "var(--surface-alt)", fontWeight: 600, borderTop: "2px solid var(--border-warm)" }}
                    data-testid="orders-footer-totals">
                  <td colSpan={4} className="py-3 px-3 label-caps" style={{ fontSize: 11 }}>
                    Totals · {orders.length} orders
                  </td>
                  <td className="num py-3">{fmtINR(totals.revenue)}</td>
                  <td className="num py-3" style={{ color: "var(--muted)" }}>{fmtINR(totals.cost)}</td>
                  <td className="num py-3"
                      style={{ color: totals.profit >= 0 ? "var(--sage)" : "var(--danger)" }}>
                    {fmtINR(totals.profit)}
                  </td>
                  <td className="num py-3"
                      style={{ color: totals.outstanding > 0.5 ? "var(--terracotta)" : "var(--sage)" }}
                      data-testid="orders-footer-outstanding">
                    {fmtINR(totals.outstanding)}
                  </td>
                  <td colSpan={2}></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      <OrderDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        order={editing}
        onSaved={(opts) => {
          load();
          if (!opts?.keepOpen) {
            setDialogOpen(false);
          } else if (editing?.id) {
            // Refetch the edited order so nested shipment refresh reflects on next open too
            api.get(`/orders/${editing.id}`).then((r) => setEditing(r.data)).catch(() => {});
          }
        }}
      />
    </div>
  );
}
