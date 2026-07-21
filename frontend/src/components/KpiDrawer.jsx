import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "./ui/accordion";
import { Button } from "./ui/button";
import { api, fmtINR } from "../lib/api";
import { ArrowRight, TrendingUp, TrendingDown, Receipt, Wallet, ArrowDownRight, ArrowUpRight, Boxes, Truck } from "lucide-react";

const CONFIG = {
  revenue: {
    title: "Operating Revenue",
    subtitle: "Everything you earned from orders — sales, freight charged, packing recovery and other charges.",
    icon: TrendingUp,
    tone: "var(--ink)",
    ordersFilter: {},
  },
  invoice: {
    title: "Invoice Value",
    subtitle: "Revenue + Tax. Tax is billed to customers but never counted as your income.",
    icon: Receipt,
    tone: "var(--ink)",
    ordersFilter: {},
  },
  profit: {
    title: "Net Profit",
    subtitle: "Revenue − Total Cost. Broken down by main and sub-category.",
    icon: TrendingUp,
    tone: "var(--sage)",
    ordersFilter: {},
  },
  cost: {
    title: "Total Cost",
    subtitle: "Factory (Complete + Glass + Fitting) + Outside + Packing + Freight Paid.",
    icon: TrendingDown,
    tone: "var(--danger)",
    ordersFilter: {},
  },
  receivable: {
    title: "Outstanding Receivable",
    subtitle: "Invoice value on orders still Unpaid or Partial.",
    icon: ArrowDownRight,
    tone: "var(--terracotta)",
    ordersFilter: { payment_status: "Unpaid" },
    ordersLabel: "View unpaid orders",
  },
  payable: {
    title: "Outstanding Payable",
    subtitle: "Total money paid out to your factory, vendors and others.",
    icon: ArrowUpRight,
    tone: "var(--ink)",
    ordersFilter: null,
    ordersLabel: "View payments",
    goTo: "/payments",
  },
  boxes: {
    title: "Boxes Used vs Shipped",
    subtitle: "How many boxes you packed, shipped, and what packing cost per box.",
    icon: Boxes,
    tone: "var(--ink)",
    ordersFilter: {},
  },
  freight: {
    title: "Freight Paid vs Charged",
    subtitle: "What you paid transporters vs what you billed customers for shipping.",
    icon: Truck,
    tone: "var(--ink)",
    ordersFilter: {},
  },
};

function Row({ label, value, tone, right, testId, mono = true }) {
  return (
    <div className="flex items-center justify-between py-2.5 text-sm border-b last:border-b-0"
         style={{ borderColor: "var(--border-warm)" }}
         data-testid={testId}>
      <div className="min-w-0 flex-1">
        <div className="truncate" style={{ color: "var(--ink)" }}>{label}</div>
        {right && (
          <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>{right}</div>
        )}
      </div>
      <div className={`serif text-lg pl-4 ${mono ? "num" : ""}`}
           style={{ color: tone || "var(--ink)" }}>
        {value}
      </div>
    </div>
  );
}

function Section({ value, title, subtitle, children }) {
  return (
    <AccordionItem value={value} className="border-b" style={{ borderColor: "var(--border-warm)" }}>
      <AccordionTrigger className="hover:no-underline py-3 text-left">
        <div>
          <div className="font-medium text-sm" style={{ color: "var(--ink)" }}>{title}</div>
          {subtitle && <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>{subtitle}</div>}
        </div>
      </AccordionTrigger>
      <AccordionContent className="pb-3">
        {children}
      </AccordionContent>
    </AccordionItem>
  );
}

// KPI-specific rendering
function RenderRevenue({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["components", "by-main"]} className="w-full">
      <Section value="components" title="Components"
               subtitle="Where the revenue is coming from">
        <Row label="Product sales" value={fmtINR(d.product_sales)} testId="rev-product-sales" />
        <Row label="Freight charged to customers" value={fmtINR(d.freight_charged)} testId="rev-freight" />
        <Row label="Packing charged to customers" value={fmtINR(d.packing_charged || 0)} testId="rev-packing" />
        <Row label="Other revenue" value={fmtINR(d.other_revenue)} testId="rev-other" />
        <Row label="Total revenue" value={fmtINR(d.total)} tone="var(--terracotta)" mono />
      </Section>
      {d.other_revenue_by_description && d.other_revenue_by_description.length > 0 && (
        <Section value="other-rev" title="Other revenue by description"
                 subtitle={`${d.other_revenue_by_description.length} labels`}>
          {d.other_revenue_by_description.map((r) => (
            <Row key={r.description} label={r.description} value={fmtINR(r.amount)}
                 right={`${r.count} entries`} />
          ))}
        </Section>
      )}
      <Section value="by-main" title="By main category"
               subtitle={`${d.by_main_category.length} categories · click to see sub-categories`}>
        <Accordion type="multiple" className="w-full">
          {d.by_main_category.map((c) => (
            <AccordionItem key={c.main_category} value={c.main_category}
                           className="border-b" style={{ borderColor: "var(--border-warm)" }}>
              <AccordionTrigger className="hover:no-underline py-2 text-sm">
                <div className="flex items-center justify-between w-full pr-3">
                  <span>{c.main_category}</span>
                  <span className="serif text-base num">{fmtINR(c.amount)}</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="pl-2">
                {(d.by_sub_category[c.main_category] || []).map((s) => (
                  <Row key={s.sub_category} label={s.sub_category} value={fmtINR(s.amount)} />
                ))}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </Section>
    </Accordion>
  );
}

function RenderInvoice({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["build", "by-tax"]} className="w-full">
      <Section value="build" title="How invoice value is built">
        <Row label="Operating revenue" value={fmtINR(d.operating_revenue)} />
        <Row label="Tax collected" value={fmtINR(d.tax_amount)} tone="var(--terracotta)" />
        <Row label="Invoice total" value={fmtINR(d.invoice_total)} tone="var(--sage)" />
        <Row label="Non-taxable revenue" value={fmtINR(d.non_taxable_revenue)}
             right="orders where tax was not applied" />
      </Section>
      {d.by_tax_type.length > 0 && (
        <Section value="by-tax" title="By tax type">
          {d.by_tax_type.map((t) => (
            <Row key={t.label} label={t.label} value={fmtINR(t.invoice_total)}
                 right={`${t.count} orders · tax ${fmtINR(t.tax_amount)}`} />
          ))}
        </Section>
      )}
    </Accordion>
  );
}

function RenderProfit({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["build", "by-main"]} className="w-full">
      <Section value="build" title="Profit build">
        <Row label="Operating revenue" value={fmtINR(d.operating_revenue)} />
        <Row label="Total cost" value={`− ${fmtINR(d.total_cost)}`} tone="var(--muted)" />
        <Row label="Net profit" value={fmtINR(d.net_profit)}
             tone={d.net_profit >= 0 ? "var(--sage)" : "var(--danger)"}
             right={`${d.margin_percent.toFixed(1)}% margin`} />
      </Section>
      <Section value="by-main" title="Profit by main category"
               subtitle="Order-level cost is allocated to items by their sales share">
        {d.by_main_category.map((c) => (
          <Row key={c.main_category}
               label={c.main_category}
               value={fmtINR(c.profit)}
               tone={c.profit >= 0 ? "var(--sage)" : "var(--danger)"}
               right={`revenue ${fmtINR(c.revenue)} · ${c.margin_percent.toFixed(1)}%`} />
        ))}
      </Section>
    </Accordion>
  );
}

function RenderCost({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["factory", "outside", "other", "other-exp"]} className="w-full">
      <Section value="factory" title="Factory purchase"
               subtitle={`${fmtINR(d.factory.total)} — Complete + Glass + Fitting`}>
        <Row label="Complete" value={fmtINR(d.factory.complete)} testId="fac-complete" />
        <Row label="Glass" value={fmtINR(d.factory.glass)} testId="fac-glass" />
        <Row label="Fitting" value={fmtINR(d.factory.fitting)} testId="fac-fitting" />
      </Section>
      <Section value="outside" title="Outside purchase"
               subtitle={`${fmtINR(d.outside.total)} — Complete + Glass + Fitting`}>
        <Row label="Complete" value={fmtINR(d.outside.complete)} />
        <Row label="Glass" value={fmtINR(d.outside.glass)} />
        <Row label="Fitting" value={fmtINR(d.outside.fitting)} />
      </Section>
      <Section value="other" title="Packing & Freight">
        <Row label="Packing cost" value={fmtINR(d.packing)} />
        <Row label="Freight paid" value={fmtINR(d.freight)} />
      </Section>
      <Section value="other-exp" title="Other expenses"
               subtitle="Discounts, labour, local transport, loading — anything else that adds to cost">
        <Row label="Total other expense" value={fmtINR(d.other_expense || 0)}
             testId="cost-other-total" />
        {(d.other_expense_by_description || []).map((r) => (
          <Row key={r.description} label={r.description} value={fmtINR(r.amount)}
               right={`${r.count} entries`} />
        ))}
      </Section>
      <div className="flex items-center justify-between mt-4 pt-3 border-t"
           style={{ borderColor: "var(--border-warm)" }}>
        <div className="label-caps">Total cost</div>
        <div className="serif text-2xl num" style={{ color: "var(--danger)" }}>{fmtINR(d.total)}</div>
      </div>
    </Accordion>
  );
}

function RenderReceivable({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["by-status", "by-client"]} className="w-full">
      <Section value="by-status" title="By status">
        {d.by_status.map((s) => (
          <Row key={s.status} label={s.status} value={fmtINR(s.amount)}
               right={`${s.count} orders`}
               tone={s.status === "Unpaid" ? "var(--danger)"
                    : s.status === "Partial" ? "#8a5a2c" : "var(--sage)"} />
        ))}
      </Section>
      <Section value="by-client" title="By client (Unpaid + Partial)">
        {d.by_client.length === 0 && (
          <div className="text-sm py-3" style={{ color: "var(--muted)" }}>No outstanding.</div>
        )}
        {d.by_client.map((c) => (
          <Row key={c.client} label={c.client} value={fmtINR(c.amount)}
               right={`${c.orders} orders`} />
        ))}
      </Section>
    </Accordion>
  );
}

function RenderPayable({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["summary", "by-party"]} className="w-full">
      <Section value="summary" title="Cash-flow summary">
        <Row label="Total paid out" value={fmtINR(d.total_paid)} tone="var(--terracotta)" />
        <Row label="Total received" value={fmtINR(d.total_received)} tone="var(--sage)" />
        <Row label="Net (out)" value={fmtINR(d.net_out)}
             tone={d.net_out >= 0 ? "var(--danger)" : "var(--sage)"} />
      </Section>
      <Section value="by-party" title="By party">
        {d.by_party.map((p) => (
          <Row key={p.party} label={p.party} value={fmtINR(p.paid)}
               right={`received ${fmtINR(p.received)} · net ${fmtINR(p.net)}`} />
        ))}
      </Section>
      <Section value="by-mode" title="By mode">
        {d.by_mode.map((m) => (
          <Row key={m.mode} label={m.mode} value={fmtINR(m.paid)}
               right={`received ${fmtINR(m.received)}`} />
        ))}
      </Section>
    </Accordion>
  );
}

function RenderBoxes({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["summary", "by-transporter"]} className="w-full">
      <Section value="summary" title="Summary">
        <Row label="Boxes used (packing)" value={d.used.toLocaleString("en-IN")} mono={false} />
        <Row label="Boxes shipped" value={d.shipped.toLocaleString("en-IN")} mono={false} />
        <Row label="Gap (used − shipped)" value={d.gap.toLocaleString("en-IN")} mono={false} />
        <Row label="Packing cost total" value={fmtINR(d.packing_cost)} />
        <Row label="Avg cost / box" value={fmtINR(d.avg_cost_per_box)} />
      </Section>
      <Section value="by-transporter" title="By transporter">
        {d.by_transporter.length === 0 && (
          <div className="text-sm py-3" style={{ color: "var(--muted)" }}>
            No transporter data yet.
          </div>
        )}
        {d.by_transporter.map((t) => (
          <Row key={t.transporter} label={t.transporter}
               value={t.boxes_shipped.toLocaleString("en-IN") + " boxes"}
               right={`${t.orders} orders · freight ${fmtINR(t.freight_paid)}`} mono={false} />
        ))}
      </Section>
    </Accordion>
  );
}

function RenderFreight({ d }) {
  return (
    <Accordion type="multiple" defaultValue={["summary", "by-transporter"]} className="w-full">
      <Section value="summary" title="Summary">
        <Row label="Freight charged to customer" value={fmtINR(d.charged)} tone="var(--sage)" />
        <Row label="Freight paid to transporter" value={fmtINR(d.paid)} tone="var(--terracotta)" />
        <Row label="Recovery gap (charged − paid)" value={fmtINR(d.recovery_gap)}
             tone={d.recovery_gap >= 0 ? "var(--sage)" : "var(--danger)"}
             right={d.recovery_gap >= 0 ? "You're recovering freight" : "You're absorbing freight"} />
      </Section>
      <Section value="by-transporter" title="By transporter">
        {d.by_transporter.length === 0 && (
          <div className="text-sm py-3" style={{ color: "var(--muted)" }}>
            No transporter data yet.
          </div>
        )}
        {d.by_transporter.map((t) => (
          <Row key={t.transporter} label={t.transporter} value={fmtINR(t.paid)}
               right={`charged ${fmtINR(t.charged)} · gap ${fmtINR(t.gap)} · ${t.orders} orders`} />
        ))}
      </Section>
    </Accordion>
  );
}

const RENDERERS = {
  revenue: RenderRevenue,
  invoice: RenderInvoice,
  profit: RenderProfit,
  cost: RenderCost,
  receivable: RenderReceivable,
  payable: RenderPayable,
  boxes: RenderBoxes,
  freight: RenderFreight,
};

export default function KpiDrawer({ open, onOpenChange, kpiId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open || !kpiId) return;
    setLoading(true);
    api.get("/dashboard/breakdown")
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, [open, kpiId]);

  if (!kpiId) return null;
  const cfg = CONFIG[kpiId];
  if (!cfg) return null;
  const Icon = cfg.icon;
  const Renderer = RENDERERS[kpiId];
  const section = data?.[kpiId];

  const handleViewOrders = () => {
    onOpenChange(false);
    if (cfg.goTo) {
      navigate(cfg.goTo);
      return;
    }
    const params = new URLSearchParams(cfg.ordersFilter || {});
    const q = params.toString();
    navigate(q ? `/orders?${q}` : "/orders");
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right"
                    className="w-full sm:max-w-lg overflow-y-auto"
                    style={{ background: "var(--bg)", borderColor: "var(--border-warm)" }}
                    data-testid={`kpi-drawer-${kpiId}`}>
        <SheetHeader className="pb-4 border-b" style={{ borderColor: "var(--border-warm)" }}>
          <div className="flex items-start gap-3 mb-2">
            <div className="p-2.5 rounded-md" style={{ background: "var(--surface-alt)" }}>
              <Icon size={18} strokeWidth={1.5} style={{ color: cfg.tone }} />
            </div>
            <div className="flex-1">
              <div className="label-caps mb-1">Drill down</div>
              <SheetTitle className="serif text-3xl leading-none text-left"
                          style={{ color: cfg.tone }}>{cfg.title}</SheetTitle>
            </div>
          </div>
          <SheetDescription className="text-xs text-left" style={{ color: "var(--muted)" }}>
            {cfg.subtitle}
          </SheetDescription>
        </SheetHeader>

        <div className="py-4">
          {loading && (
            <div className="py-16 text-center text-sm" style={{ color: "var(--muted)" }}>
              Loading breakdown…
            </div>
          )}
          {!loading && section && Renderer && <Renderer d={section} />}
        </div>

        <div className="sticky bottom-0 pt-4 pb-6 border-t bg-[var(--bg)]"
             style={{ borderColor: "var(--border-warm)" }}>
          <Button onClick={handleViewOrders}
                  data-testid={`view-orders-${kpiId}`}
                  className="w-full bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-2">
            {cfg.ordersLabel || "View Related Orders"}
            <ArrowRight size={14} />
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
