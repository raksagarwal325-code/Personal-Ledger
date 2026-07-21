import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtINR } from "../lib/api";
import PageHeader from "../components/PageHeader";
import KpiDrawer from "../components/KpiDrawer";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from "recharts";
import {
  TrendingUp, TrendingDown, Wallet, Package, ArrowDownRight, ArrowUpRight,
  Receipt, Truck, Boxes, ClipboardList, ChevronRight, Coins, ShoppingBag,
} from "lucide-react";

const CHART_COLORS = ["#C55B43", "#3A5A40", "#D4A373", "#4A6D7C", "#8B6F5C", "#BC4749", "#2C2A29", "#6B4B3E"];

function PartyCard({ label, value, tone = "muted", sub, to }) {
  const color = tone === "danger" ? "var(--danger)"
              : tone === "sage" ? "var(--sage)"
              : "var(--ink)";
  return (
    <Link
      to={to || "/party-ledger"}
      className="card-warm px-4 py-3 hover:shadow-md transition-shadow block"
      data-testid={`dash-party-card-${(label || "").toLowerCase().replace(/[^a-z]+/g, "-")}`}
    >
      <div className="label-caps text-[10px] leading-tight" style={{ color: "var(--muted)" }}>{label}</div>
      <div className="serif text-xl md:text-2xl num mt-1.5" style={{ color }}>{fmtINR(value || 0)}</div>
      {sub && <div className="text-[10px] mt-0.5" style={{ color: "var(--muted)" }}>{sub}</div>}
    </Link>
  );
}

function Kpi({ label, value, sub, tone = "default", icon: Icon, testId, small, onClick, kpiId }) {
  const toneColor = tone === "success" ? "var(--sage)"
                  : tone === "danger" ? "var(--danger)"
                  : tone === "primary" ? "var(--terracotta)" : "var(--ink)";
  const interactive = !!onClick;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!interactive}
      data-testid={testId}
      data-kpi-id={kpiId}
      className={`card-warm p-5 md:p-6 fade-up text-left w-full group ${interactive ? "cursor-pointer" : "cursor-default"}`}
      style={{ background: "var(--surface)" }}
    >
      <div className="flex items-start justify-between mb-4">
        <div className="label-caps">{label}</div>
        <div className="flex items-center gap-2">
          {Icon && <Icon size={15} strokeWidth={1.5} style={{ color: "var(--muted)" }} />}
          {interactive && (
            <ChevronRight size={13} strokeWidth={1.75}
                          className="opacity-0 group-hover:opacity-100 transition-opacity"
                          style={{ color: "var(--terracotta)" }} />
          )}
        </div>
      </div>
      <div className={`serif ${small ? "text-2xl" : "text-3xl md:text-4xl"} leading-none num`}
           style={{ color: toneColor }}>
        {value}
      </div>
      {sub && <div className="text-[11px] mt-2" style={{ color: "var(--muted)" }}>{sub}</div>}
    </button>
  );
}

function Card({ title, subtitle, children, className = "", testId }) {
  return (
    <div className={`card-warm p-6 md:p-7 fade-up ${className}`} data-testid={testId}>
      <div className="flex items-baseline justify-between mb-5">
        <div>
          <h3 className="serif text-2xl leading-none">{title}</h3>
          {subtitle && <p className="text-xs mt-1.5" style={{ color: "var(--muted)" }}>{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

const monthLabel = (m) => {
  if (!m) return "";
  const [y, mm] = m.split("-");
  const d = new Date(Number(y), Number(mm) - 1, 1);
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
};

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [partyLedger, setPartyLedger] = useState(null);
  const [ffSettlement, setFfSettlement] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedMain, setSelectedMain] = useState(null);
  const [drawerKpi, setDrawerKpi] = useState(null);
  const openKpi = (id) => setDrawerKpi(id);

  useEffect(() => {
    Promise.all([
      api.get("/dashboard"),
      api.get("/party-ledger-v2/summary").catch(() => ({ data: null })),
      api.get("/party-ledger-v2/fathers-firm-settlement").catch(() => ({ data: null })),
    ]).then(([r, r2, r3]) => {
      setData(r.data);
      setPartyLedger(r2.data);
      setFfSettlement(r3.data);
      setLoading(false);
      if (r.data?.main_categories?.length) {
        setSelectedMain(r.data.main_categories[0].main_category);
      }
    }).catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-12 w-64 bg-[var(--surface-alt)] rounded" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          {[...Array(8)].map((_, i) => <div key={i} className="h-32 bg-[var(--surface-alt)] rounded" />)}
        </div>
      </div>
    );
  }
  if (!data) return <div>Failed to load dashboard.</div>;

  const { kpis, monthly, main_categories, sub_categories, top_customers, top_products, modes } = data;
  const monthlyChart = monthly.map((m) => ({ ...m, label: monthLabel(m.month) }));
  const subForSelected = selectedMain ? (sub_categories[selectedMain] || []) : [];

  return (
    <div>
      <PageHeader
        eyebrow="Ledger overview"
        title="Workshop at a glance"
        subtitle="Order-level revenue, cost, profit and GST — with drill-downs into product and customer performance."
      />

      {/* Primary KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-4">
        <Kpi label="Shipped Revenue" value={fmtINR(kpis.operating_revenue)}
             sub={`${kpis.order_count} orders · from shipped qty only`}
             icon={TrendingUp} testId="kpi-revenue" kpiId="revenue"
             onClick={() => openKpi("revenue")} />
        <Kpi label="Invoice Value" value={fmtINR(kpis.invoice_value)}
             sub={`GST collected ${fmtINR(kpis.gst_collected)}`}
             icon={Receipt} testId="kpi-invoice" kpiId="invoice"
             onClick={() => openKpi("invoice")} />
        <Kpi label="Net Profit" value={fmtINR(kpis.net_profit)}
             sub={`${kpis.margin_percent.toFixed(1)}% margin`}
             tone="success" icon={TrendingUp} testId="kpi-profit" kpiId="profit"
             onClick={() => openKpi("profit")} />
        <Kpi label="Total Cost" value={fmtINR(kpis.total_cost)}
             sub="factory + outside + packing + freight"
             tone="danger" icon={TrendingDown} testId="kpi-cost" kpiId="cost"
             onClick={() => openKpi("cost")} />
      </div>

      {/* Party settlement row — Party Ledger v2 */}
      {partyLedger && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-4" data-testid="dash-party-summary">
          {/* Father's Firm — single signed settlement card */}
          {(() => {
            const status = ffSettlement?.status || "settled";
            const amount = Number(ffSettlement?.amount || 0);
            const tone = status === "you_pay" ? "danger" : status === "you_receive" ? "sage" : "muted";
            const label = "Father's Firm Settlement";
            const sub = status === "you_pay" ? "You Pay"
                      : status === "you_receive" ? "You Receive"
                      : "Settled";
            return (
              <PartyCard label={label}
                         value={amount}
                         tone={tone}
                         sub={sub}
                         to={`/party-ledger?type=fathers_firm&status=${status}`} />
            );
          })()}
          <PartyCard label="Vendor payables"
                     value={partyLedger.vendor_you_pay}
                     tone="danger" to="/party-ledger?type=vendor&status=you_pay" />
          <PartyCard label="Vendor advances"
                     value={partyLedger.vendor_advances_you_receive}
                     tone="sage" to="/party-ledger?type=vendor&status=you_receive" />
          <PartyCard label="Customer receivables"
                     value={partyLedger.customer_you_receive}
                     tone="sage" to="/party-ledger?type=customer&status=you_receive" />
          {/* Net settlement — uses single signed Father's Firm balance to avoid double-counting */}
          {(() => {
            const ffSigned = Number(ffSettlement?.balance_signed || 0);
            // Base = existing net_position but SUBTRACT the fathers_firm split cards
            // and add back only the single signed FF value so it isn't double counted.
            const fromNet = Number(partyLedger.net_position || 0);
            // partyLedger.net_position already sums every party's signed balance including FF.
            // The two removed cards were split views of the same balance, so the underlying
            // net_position figure remains correct. Just make sure we show a single figure.
            const netAbs = Math.abs(fromNet);
            const netTone = fromNet > 0.5 ? "danger" : fromNet < -0.5 ? "sage" : "muted";
            const netSub = fromNet > 0.5 ? "You Pay overall" : fromNet < -0.5 ? "You Receive overall" : "Settled";
            return (
              <PartyCard label="Net settlement"
                         value={netAbs}
                         tone={netTone}
                         sub={netSub}
                         to="/party-ledger" />
            );
          })()}
        </div>
      )}

      {/* Secondary KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-4">
        <Kpi label="Outstanding Receivable" value={fmtINR(kpis.outstanding_receivable)}
             sub="Unpaid or partial orders" small icon={ArrowDownRight}
             tone={kpis.outstanding_receivable > 0 ? "primary" : "default"}
             testId="kpi-receivable" kpiId="receivable"
             onClick={() => openKpi("receivable")} />
        <Kpi label="Customer Advances" value={fmtINR(kpis.customer_advances || 0)}
             sub="Unallocated customer payments" small icon={Coins}
             tone={(kpis.customer_advances || 0) > 0 ? "success" : "default"}
             testId="kpi-advances" kpiId="advances"
             onClick={() => openKpi("advances")} />
        <Kpi label="Boxes Used / Shipped" value={`${kpis.boxes_used || 0} / ${kpis.boxes_shipped || 0}`}
             sub={`Packing ${fmtINR(kpis.packing_cost)}`} small icon={Boxes}
             testId="kpi-boxes" kpiId="boxes"
             onClick={() => openKpi("boxes")} />
        <Kpi label="Freight Paid / Charged"
             value={`${fmtINR(kpis.freight_paid)}`}
             sub={`Charged ${fmtINR(kpis.freight_charged)}`}
             small icon={Truck} testId="kpi-freight" kpiId="freight"
             onClick={() => openKpi("freight")} />
      </div>

      {/* Purchases KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-8">
        <Kpi label="Purchase Value" value={fmtINR(kpis.purchase_value || 0)}
             sub={`${kpis.purchase_count || 0} vendor bills`} small icon={ShoppingBag}
             testId="kpi-purchase-value" />
        <Kpi label="Purchase Paid" value={fmtINR(kpis.purchase_paid || 0)}
             sub="Total paid to vendors" small icon={ArrowUpRight}
             tone="default" testId="kpi-purchase-paid" />
        <Kpi label="Outstanding Payable" value={fmtINR(kpis.purchase_outstanding || 0)}
             sub="Vendor bills unpaid" small icon={ArrowUpRight}
             tone={(kpis.purchase_outstanding || 0) > 0 ? "danger" : "default"}
             testId="kpi-payable" kpiId="payable"
             onClick={() => openKpi("payable")} />
        <Kpi label="Cash Paid Out" value={fmtINR(kpis.outstanding_payable)}
             sub="Money paid out (Cash Book)" small icon={Wallet}
             testId="kpi-cash-out" />
      </div>

      {/* Monthly + Main Category */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <Card title="Monthly performance" subtitle="Revenue vs profit trend"
              className="lg:col-span-2" testId="chart-monthly">
          {monthlyChart.length === 0 ? (
            <div className="h-72 flex items-center justify-center text-sm" style={{ color: "var(--muted)" }}>
              No dated orders yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={monthlyChart} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--border-warm)" vertical={false} />
                <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false}
                       tickFormatter={(v) => v >= 100000 ? `${(v/100000).toFixed(1)}L` : v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
                <Tooltip
                  contentStyle={{ background: "#fff", border: "1px solid var(--border-warm)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => fmtINR(v)}
                />
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                <Line type="monotone" dataKey="revenue" stroke="#C55B43" strokeWidth={2.5} dot={{ r: 3 }} name="Revenue" />
                <Line type="monotone" dataKey="profit" stroke="#3A5A40" strokeWidth={2.5} dot={{ r: 3 }} name="Profit" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Main categories" subtitle="Sales share by category" testId="chart-main-cat">
          {main_categories.length === 0 ? (
            <div className="h-72 flex items-center justify-center text-sm" style={{ color: "var(--muted)" }}>No data.</div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={main_categories.filter((c) => c.sales > 0)}
                  dataKey="sales" nameKey="main_category"
                  innerRadius={55} outerRadius={95} paddingAngle={2}
                  stroke="var(--surface)" strokeWidth={2}
                  onClick={(entry) => entry?.main_category && setSelectedMain(entry.main_category)}
                >
                  {main_categories.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]}
                          cursor="pointer" />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "#fff", border: "1px solid var(--border-warm)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => fmtINR(v)}
                />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      {/* Sub-cat drill-down + top customers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <Card
          title="Sub-category drill"
          subtitle={selectedMain ? `Inside ${selectedMain} — click a slice on the pie to switch` : "Pick a category"}
          testId="chart-subcat"
        >
          {subForSelected.length === 0 ? (
            <div className="h-52 flex items-center justify-center text-sm" style={{ color: "var(--muted)" }}>
              No sub-categories recorded yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={subForSelected} layout="vertical" margin={{ left: 30 }}>
                <CartesianGrid stroke="var(--border-warm)" horizontal={false} />
                <XAxis type="number" stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false}
                       tickFormatter={(v) => v >= 100000 ? `${(v/100000).toFixed(1)}L` : v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
                <YAxis type="category" dataKey="sub_category" stroke="var(--muted)"
                       fontSize={11} tickLine={false} axisLine={false} width={110} />
                <Tooltip
                  contentStyle={{ background: "#fff", border: "1px solid var(--border-warm)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => fmtINR(v)}
                />
                <Bar dataKey="sales" fill="#C55B43" name="Sales" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Top customers" subtitle="Ranked by profit contribution" testId="top-customers">
          <div className="space-y-3.5 mt-2">
            {top_customers.length === 0 && (
              <div className="text-sm" style={{ color: "var(--muted)" }}>No customers yet.</div>
            )}
            {top_customers.slice(0, 7).map((c) => (
              <div key={c.client} className="flex items-center justify-between text-sm">
                <div className="flex-1 truncate pr-4">
                  <div className="font-medium" style={{ color: "var(--ink)" }}>{c.client}</div>
                  <div className="text-xs" style={{ color: "var(--muted)" }}>
                    {c.orders} orders · revenue {fmtINR(c.revenue)}
                  </div>
                </div>
                <div className="serif text-lg num"
                     style={{ color: c.profit >= 0 ? "var(--sage)" : "var(--danger)" }}>
                  {fmtINR(c.profit)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Top products + payment modes */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Top products" subtitle="Best sellers across all orders" testId="top-products">
          <div className="space-y-3.5 mt-2">
            {top_products.length === 0 && (
              <div className="text-sm" style={{ color: "var(--muted)" }}>No products yet.</div>
            )}
            {top_products.slice(0, 7).map((p) => (
              <div key={p.product} className="flex items-center justify-between text-sm">
                <div className="flex-1 truncate pr-4">
                  <div className="font-medium truncate" style={{ color: "var(--ink)" }}>{p.product || "Unnamed"}</div>
                  <div className="text-xs" style={{ color: "var(--muted)" }}>
                    {p.main_category} · Qty {p.qty} · {p.orders} orders
                  </div>
                </div>
                <div className="serif text-lg num">{fmtINR(p.sales)}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Payments by mode" subtitle="How money flows through your accounts" testId="chart-modes">
          {modes.length === 0 ? (
            <div className="h-52 flex items-center justify-center text-sm" style={{ color: "var(--muted)" }}>
              No payments yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={modes}>
                <CartesianGrid stroke="var(--border-warm)" vertical={false} />
                <XAxis dataKey="mode" stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="var(--muted)" fontSize={11} tickLine={false} axisLine={false}
                       tickFormatter={(v) => v >= 100000 ? `${(v/100000).toFixed(1)}L` : v >= 1000 ? `${(v/1000).toFixed(0)}k` : v} />
                <Tooltip
                  contentStyle={{ background: "#fff", border: "1px solid var(--border-warm)", borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => fmtINR(v)}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="received" fill="#3A5A40" name="Received" radius={[4, 4, 0, 0]} />
                <Bar dataKey="paid" fill="#C55B43" name="Paid" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      <KpiDrawer
        open={!!drawerKpi}
        onOpenChange={(v) => { if (!v) setDrawerKpi(null); }}
        kpiId={drawerKpi}
      />
    </div>
  );
}
