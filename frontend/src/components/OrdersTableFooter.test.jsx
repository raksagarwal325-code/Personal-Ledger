/**
 * Bug fix (2026-07-22) · Orders table footer column alignment.
 *
 * Regression test: guarantees that every aggregate cell in the Orders
 * table `<tfoot>` maps to its matching header column, and that the
 * "Est. Profit" total (previously missing) is now emitted.
 *
 * Fixed totals from the bug report:
 *   • Realized Revenue → ₹1,10,700
 *   • Estimated Revenue → ₹1,10,700
 *   • Total Cost → ₹84,725
 *   • Realized Profit → ₹25,975
 *   • Estimated Profit → ₹25,975
 *   • Outstanding → ₹38,292
 *
 * Header order (12 columns):
 *   0 expand · 1 Date · 2 Client · 3 Items · 4 Realized Rev ·
 *   5 Est. Rev · 6 Total Cost · 7 Realized Profit · 8 Est. Profit ·
 *   9 Outstanding · 10 Status · 11 actions
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import OrdersTableFooter from "./OrdersTableFooter";

const TOTALS = {
  revenue: 110700,
  est_revenue: 110700,
  cost: 84725,
  profit: 25975,
  est_profit: 25975,
  outstanding: 38292,
};

function renderFooter(count = 3, totals = TOTALS) {
  return render(
    <table>
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
      <OrdersTableFooter count={count} totals={totals} />
    </table>
  );
}

describe("OrdersTableFooter column alignment", () => {
  test("emits ALL six aggregate cells (Realized Rev, Est. Rev, Cost, Realized Profit, Est. Profit, Outstanding)", () => {
    renderFooter();
    // Each column has a dedicated testId — verifies the missing
    // "Est. Profit" total is now present.
    for (const id of [
      "orders-footer-realized-rev",
      "orders-footer-est-rev",
      "orders-footer-cost",
      "orders-footer-realized-profit",
      "orders-footer-est-profit",
      "orders-footer-outstanding",
    ]) {
      // Regression guard: getByTestId throws if the node is missing.
      // In particular this catches the pre-fix bug where "Est. Profit"
      // had no footer cell at all.
      expect(screen.getByTestId(id)).not.toBeNull();
    }
  });

  test("aggregate values appear in the exact expected order under matching header columns", () => {
    renderFooter();
    const row = screen.getByTestId("orders-footer-totals");
    const cells = Array.from(row.querySelectorAll("td"));
    // 1 label cell (colSpan=4) + 6 aggregate cells + 1 empty tail cell (colSpan=2) = 8 <td> nodes
    expect(cells).toHaveLength(8);

    // Label cell colSpan=4 covers expand/Date/Client/Items.
    expect(cells[0].getAttribute("colspan")).toBe("4");
    expect(cells[0].textContent).toMatch(/Totals · 3 orders/);

    // Ordered aggregate cells align to header columns 4..9.
    const orderedTestIds = [
      "orders-footer-realized-rev",   // → column 4  (Realized Rev)
      "orders-footer-est-rev",        // → column 5  (Est. Rev)
      "orders-footer-cost",           // → column 6  (Total Cost)
      "orders-footer-realized-profit",// → column 7  (Realized Profit)
      "orders-footer-est-profit",     // → column 8  (Est. Profit)
      "orders-footer-outstanding",    // → column 9  (Outstanding)
    ];
    orderedTestIds.forEach((id, i) => {
      expect(cells[i + 1].getAttribute("data-testid")).toBe(id);
    });

    // Trailing empty cell covers Status + actions.
    expect(cells[7].getAttribute("colspan")).toBe("2");
    expect(cells[7].textContent).toBe("");

    // Sum of colspans MUST equal the 12 header columns.
    const totalColspan = cells.reduce(
      (sum, td) => sum + (parseInt(td.getAttribute("colspan") || "1", 10) || 1),
      0
    );
    expect(totalColspan).toBe(12);
  });

  test("expected totals map to the correct aggregate cells (no more shifted values)", () => {
    renderFooter(3, TOTALS);
    // Indian locale formatting: ₹1,10,700 etc.
    expect(screen.getByTestId("orders-footer-realized-rev").textContent).toContain("1,10,700");
    expect(screen.getByTestId("orders-footer-est-rev").textContent).toContain("1,10,700");
    expect(screen.getByTestId("orders-footer-cost").textContent).toContain("84,725");
    expect(screen.getByTestId("orders-footer-realized-profit").textContent).toContain("25,975");
    expect(screen.getByTestId("orders-footer-est-profit").textContent).toContain("25,975");
    expect(screen.getByTestId("orders-footer-outstanding").textContent).toContain("38,292");
  });
});
