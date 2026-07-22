import { fmtINR } from "../lib/api";

/**
 * Bug fix (2026-07-22) · Orders table footer column alignment.
 *
 * The `<tfoot>` row in the Orders table must align every aggregate cell
 * to its matching `<thead>` column. Header columns (12 total):
 *
 *   [0] expand icon (width 40)
 *   [1] Date
 *   [2] Client
 *   [3] Items
 *   [4] Realized Rev
 *   [5] Est. Rev
 *   [6] Total Cost
 *   [7] Realized Profit
 *   [8] Est. Profit
 *   [9] Outstanding
 *   [10] Status
 *   [11] actions
 *
 * The footer covers columns [0..3] with one `colSpan={4}` label ("Totals · N orders"),
 * emits one `<td>` per aggregate for columns [4..9], and closes with
 * `colSpan={2}` for the trailing Status + actions columns.
 *
 * Extracted from `pages/Orders.jsx` so the exact column layout is
 * unit-testable without wiring axios/router/context. The parent page
 * imports this component to render the aggregates row.
 */
export default function OrdersTableFooter({ count, totals }) {
  return (
    <tfoot>
      <tr
        style={{
          background: "var(--surface-alt)",
          fontWeight: 600,
          borderTop: "2px solid var(--border-warm)",
        }}
        data-testid="orders-footer-totals"
      >
        <td colSpan={4} className="py-3 px-3 label-caps" style={{ fontSize: 11 }}>
          Totals · {count} orders
        </td>
        <td className="num py-3" data-testid="orders-footer-realized-rev">
          {fmtINR(totals.revenue)}
        </td>
        <td className="num py-3" data-testid="orders-footer-est-rev">
          {fmtINR(totals.est_revenue)}
        </td>
        <td
          className="num py-3"
          style={{ color: "var(--muted)" }}
          data-testid="orders-footer-cost"
        >
          {fmtINR(totals.cost)}
        </td>
        <td
          className="num py-3"
          style={{ color: totals.profit >= 0 ? "var(--sage)" : "var(--danger)" }}
          data-testid="orders-footer-realized-profit"
        >
          {fmtINR(totals.profit)}
        </td>
        <td
          className="num py-3"
          style={{ color: totals.est_profit >= 0 ? "var(--sage)" : "var(--danger)" }}
          data-testid="orders-footer-est-profit"
        >
          {fmtINR(totals.est_profit)}
        </td>
        <td
          className="num py-3"
          style={{ color: totals.outstanding > 0.5 ? "var(--terracotta)" : "var(--sage)" }}
          data-testid="orders-footer-outstanding"
        >
          {fmtINR(totals.outstanding)}
        </td>
        <td colSpan={2}></td>
      </tr>
    </tfoot>
  );
}
