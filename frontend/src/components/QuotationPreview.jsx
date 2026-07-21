import { useRef } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Printer, Pencil, X } from "lucide-react";
import { fmtINR, fmtDate } from "../lib/api";

// Compact, print-ready quotation preview matched to the Artisan design system.
// Uses window.print() with a scoped print stylesheet so only the sheet prints.
export default function QuotationPreview({ open, onOpenChange, quotation, onEdit }) {
  const sheetRef = useRef(null);

  if (!quotation) return null;

  const q = quotation;
  const bill = [q.billing_address, q.billing_city, q.billing_pincode].filter(Boolean).join(", ");
  const ship = q.shipping_same_as_billing
    ? bill
    : [q.shipping_address, q.shipping_city, q.shipping_pincode].filter(Boolean).join(", ");
  const items = q.items || [];
  const freightExtra = q.freight_type === "extra";

  const doPrint = () => {
    // Add temporary body class so print CSS scopes to the sheet only
    document.body.classList.add("printing-quotation");
    window.print();
    // Chrome fires afterprint reliably; fallback timeout just in case
    const cleanup = () => document.body.classList.remove("printing-quotation");
    window.addEventListener("afterprint", cleanup, { once: true });
    setTimeout(cleanup, 4000);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-4xl max-h-[92vh] overflow-y-auto no-print-dialog-chrome"
        data-testid="quotation-preview"
      >
        <DialogHeader className="no-print">
          <div className="flex items-center justify-between gap-4">
            <div>
              <DialogTitle className="serif text-3xl">
                {q.quote_number || "Quotation"}
              </DialogTitle>
              <DialogDescription className="text-xs" style={{ color: "var(--muted)" }}>
                Preview & print. Save as PDF from your browser's print dialog.
              </DialogDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={onEdit}
                data-testid="quot-preview-edit"
                className="border-[var(--border-warm)] gap-1.5"
              >
                <Pencil size={13} /> Edit
              </Button>
              <Button
                type="button"
                onClick={doPrint}
                data-testid="quot-preview-print"
                className="bg-[var(--terracotta)] hover:bg-[var(--terracotta-hover)] text-white gap-1.5"
              >
                <Printer size={13} /> Print / Save PDF
              </Button>
            </div>
          </div>
        </DialogHeader>

        {/* The printable sheet */}
        <div id="quotation-print-sheet" ref={sheetRef}
             className="quotation-sheet"
             style={{ background: "white", color: "var(--ink)", padding: "40px 44px", borderRadius: 8,
                      border: "1px solid var(--border-warm)" }}>
          {/* Header band */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                        borderBottom: "1px solid var(--border-warm)", paddingBottom: 20, marginBottom: 20 }}>
            <div>
              <div className="label-caps" style={{ letterSpacing: 2 }}>Artisan Ledger</div>
              <h1 className="serif" style={{ fontSize: 40, lineHeight: 1, margin: "6px 0 4px",
                                              color: "var(--ink)" }}>
                Quotation
              </h1>
              <div className="text-xs" style={{ color: "var(--muted)" }}>
                Handcrafted lighting · workshop-direct
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="label-caps">Quote number</div>
              <div className="serif" style={{ fontSize: 22, color: "var(--terracotta)" }}>
                {q.quote_number || "—"}
              </div>
              <div className="text-xs mt-2">
                <span style={{ color: "var(--muted)" }}>Date · </span>{fmtDate(q.quote_date)}
              </div>
              {q.valid_until && (
                <div className="text-xs">
                  <span style={{ color: "var(--muted)" }}>Valid until · </span>{fmtDate(q.valid_until)}
                </div>
              )}
              <div className="text-xs mt-2">
                <span className="inline-block px-2 py-0.5 rounded-full"
                      style={{ background: "var(--surface-alt)", color: "var(--muted)", fontSize: 10 }}>
                  {q.status}
                </span>
              </div>
            </div>
          </div>

          {/* Addresses */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
            <div>
              <div className="label-caps mb-1">Billed to</div>
              <div className="serif" style={{ fontSize: 18 }}>{q.client_name || "—"}</div>
              {bill && <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>{bill}</div>}
              {(q.client_phone || q.client_email) && (
                <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                  {q.client_phone}{q.client_phone && q.client_email && " · "}{q.client_email}
                </div>
              )}
            </div>
            <div>
              <div className="label-caps mb-1">Shipped to</div>
              <div className="text-xs" style={{ color: "var(--muted)" }}>
                {ship || "—"}
              </div>
            </div>
          </div>

          {/* Items table */}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginBottom: 16 }}>
            <thead>
              <tr style={{ background: "var(--surface-alt)" }}>
                <th style={{ textAlign: "left",  padding: "10px 12px", fontSize: 10, letterSpacing: 1.5,
                             textTransform: "uppercase", color: "var(--muted)" }}>#</th>
                <th style={{ textAlign: "left",  padding: "10px 12px", fontSize: 10, letterSpacing: 1.5,
                             textTransform: "uppercase", color: "var(--muted)" }}>Description</th>
                <th style={{ textAlign: "right", padding: "10px 12px", fontSize: 10, letterSpacing: 1.5,
                             textTransform: "uppercase", color: "var(--muted)" }}>Qty</th>
                <th style={{ textAlign: "right", padding: "10px 12px", fontSize: 10, letterSpacing: 1.5,
                             textTransform: "uppercase", color: "var(--muted)" }}>Rate</th>
                <th style={{ textAlign: "right", padding: "10px 12px", fontSize: 10, letterSpacing: 1.5,
                             textTransform: "uppercase", color: "var(--muted)" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={it.id || i} style={{ borderBottom: "1px solid var(--border-warm)" }}>
                  <td style={{ padding: "12px", verticalAlign: "top", color: "var(--muted)" }}>{i + 1}</td>
                  <td style={{ padding: "12px" }}>
                    <div style={{ fontWeight: 500 }}>{it.product_name || "—"}</div>
                    {it.description && (
                      <div className="text-xs mt-1" style={{ color: "var(--muted)" }}>{it.description}</div>
                    )}
                  </td>
                  <td style={{ padding: "12px", textAlign: "right" }}>{it.qty}</td>
                  <td style={{ padding: "12px", textAlign: "right" }}>{fmtINR(it.rate)}</td>
                  <td style={{ padding: "12px", textAlign: "right", fontWeight: 500 }}>
                    {fmtINR((Number(it.qty) || 0) * (Number(it.rate) || 0))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Totals */}
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 24 }}>
            <div style={{ minWidth: 300 }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
                <span style={{ color: "var(--muted)" }}>Subtotal</span>
                <span>{fmtINR(q.subtotal)}</span>
              </div>
              {freightExtra && (Number(q.freight_amount) || 0) > 0 && (
                <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
                  <span style={{ color: "var(--muted)" }}>Freight</span>
                  <span>{fmtINR(q.freight_amount)}</span>
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0" }}>
                <span style={{ color: "var(--muted)" }}>GST @ {q.gst_rate}%</span>
                <span>{fmtINR(q.tax_amount)}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between",
                            padding: "12px 0", borderTop: "1px solid var(--border-warm)",
                            marginTop: 6 }}>
                <span className="label-caps">Grand total</span>
                <span className="serif" style={{ fontSize: 28, color: "var(--terracotta)" }}>
                  {fmtINR(q.total)}
                </span>
              </div>
              {q.freight_type === "included" && (
                <div className="text-xs" style={{ color: "var(--muted)", textAlign: "right" }}>
                  Freight included in rates
                </div>
              )}
              {q.freight_type === "none" && (
                <div className="text-xs" style={{ color: "var(--muted)", textAlign: "right" }}>
                  Freight to be paid separately by the customer
                </div>
              )}
            </div>
          </div>

          {/* Terms & signatory */}
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 24,
                        paddingTop: 20, borderTop: "1px solid var(--border-warm)" }}>
            <div>
              <div className="label-caps mb-2">Terms</div>
              <div className="text-xs" style={{ color: "var(--muted)", whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
                {q.terms || "—"}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="label-caps mb-8">Authorised signatory</div>
              <div style={{ borderTop: "1px solid var(--ink)", paddingTop: 6, marginTop: 40 }}>
                <div className="text-xs" style={{ color: "var(--muted)" }}>For Artisan Ledger</div>
              </div>
            </div>
          </div>

          {q.notes && (
            <div className="mt-6 text-xs" style={{ color: "var(--muted)" }}>
              <span className="label-caps mr-2">Internal notes</span>{q.notes}
            </div>
          )}
        </div>

        <DialogFooter className="no-print">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="border-[var(--border-warm)] gap-1.5"
          >
            <X size={13} /> Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
