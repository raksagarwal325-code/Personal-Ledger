import { API } from "../lib/api";
import PageHeader from "../components/PageHeader";
import { FileSpreadsheet, FileText, Package } from "lucide-react";

const sections = [
  {
    title: "Orders",
    desc: "One row per shipment — dates, client, revenue, cost, profit, tax, packing & freight.",
    csv: `${API}/export/orders.csv`,
    xlsx: `${API}/export/orders.xlsx`,
    testId: "export-orders",
    icon: FileSpreadsheet,
  },
  {
    title: "Order Items",
    desc: "One row per product line — the detailed breakdown by main category, sub-category and product.",
    csv: null,
    xlsx: `${API}/export/order-items.xlsx`,
    testId: "export-order-items",
    icon: Package,
  },
  {
    title: "Payments",
    desc: "Cash-flow ledger — money received and paid, by party and mode.",
    csv: `${API}/export/payments.csv`,
    xlsx: `${API}/export/payments.xlsx`,
    testId: "export-payments",
    icon: FileSpreadsheet,
  },
];

function DownloadBtn({ href, label, filename, testId, Icon, primary }) {
  const style = primary ? "text-white" : "text-[var(--ink)]";
  return (
    <a href={href} download={filename} data-testid={testId}
       className={`inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${style}`}
       style={{
         background: primary ? "var(--terracotta)" : "var(--surface-alt)",
         border: primary ? "none" : "1px solid var(--border-warm)",
       }}>
      <Icon size={14} strokeWidth={1.75} />
      {label}
    </a>
  );
}

export default function Exports() {
  return (
    <div>
      <PageHeader
        eyebrow="Take it with you"
        title="Exports"
        subtitle="Excel with ₹ formatting for your accountant, CSV for portability into other tools."
      />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 max-w-6xl">
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.title} className="card-warm p-7" data-testid={`${s.testId}-card`}>
              <div className="p-3 rounded-md w-fit mb-5" style={{ background: "var(--surface-alt)" }}>
                <Icon size={22} strokeWidth={1.5} style={{ color: "var(--terracotta)" }} />
              </div>
              <h3 className="serif text-2xl leading-none mb-2">{s.title}</h3>
              <p className="text-sm min-h-[3rem]" style={{ color: "var(--muted)" }}>{s.desc}</p>
              <div className="mt-5 flex flex-wrap gap-2">
                <DownloadBtn href={s.xlsx} label="Excel"
                             filename={`${s.title.toLowerCase().replace(/ /g, "-")}.xlsx`}
                             testId={`${s.testId}-xlsx`} Icon={FileSpreadsheet} primary />
                {s.csv && (
                  <DownloadBtn href={s.csv} label="CSV"
                               filename={`${s.title.toLowerCase().replace(/ /g, "-")}.csv`}
                               testId={`${s.testId}-csv`} Icon={FileText} />
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-12 card-warm p-6 max-w-6xl">
        <div className="label-caps mb-3">Format notes</div>
        <ul className="text-sm space-y-2" style={{ color: "var(--muted)" }}>
          <li>• Excel files use ₹ formatting, dd-mmm-yyyy dates and a frozen header row.</li>
          <li>• Orders export includes Operating Revenue, Invoice Total, Tax and Margin per order.</li>
          <li>• Order Items export is the closest to a raw line-item spreadsheet — best for pivot tables.</li>
        </ul>
      </div>
    </div>
  );
}
