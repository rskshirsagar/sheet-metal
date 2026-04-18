"""
SM Stage Production Entry
==========================
Records one production session (partial or full) at a single WIP stage.

KEY DESIGN PRINCIPLE:
  Standard ERPNext books remaining quantity as "Process Loss" when a Work
  Order is Closed with produced_qty < qty.  This module NEVER closes a Work
  Order via the standard close path.  Instead:

  1.  Each booking session creates a partial Manufacture Stock Entry linked
      to the Work Order.  The WO produced_qty accumulates across sessions.
  2.  The Work Order is kept in "In Process" state between sessions.
  3.  When the user decides to move forward with whatever has been produced,
      the "Close Stage" action calls stop_work_order() — this merely sets
      WO status = "Stopped" with ZERO stock movement (no process loss).
  4.  The remaining open qty stays physically in the source WIP warehouse.
  5.  The next stage Work Order is created with qty = qty actually produced
      (qty_forwarded), not the original planned qty.

Stock flow per session:
  Source WH   → (consumed as raw material in Manufacture SE)
  Target WH   ← (finished output in Manufacture SE)
  qty_produced pieces move from in-process → output WIP warehouse
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, flt, get_time


class SMStageProductionEntry(Document):

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self):
        self._validate_qty()
        self._set_balance_fields()
        self.status = "Draft"

    def _validate_qty(self):
        if flt(self.qty_produced) <= 0:
            frappe.throw(_("Qty Produced must be greater than zero."))
        if flt(self.qty_produced) > flt(self.qty_to_produce):
            frappe.throw(
                _("Qty Produced ({0}) cannot exceed Qty to Produce ({1}).").format(
                    self.qty_produced, self.qty_to_produce
                )
            )
        if flt(self.qty_produced) + flt(self.qty_rejected) > flt(self.qty_to_produce):
            frappe.throw(
                _("Qty Produced + Qty Rejected ({0}) cannot exceed Qty to Produce ({1}).").format(
                    flt(self.qty_produced) + flt(self.qty_rejected), self.qty_to_produce
                )
            )
        # Validate against available qty
        available = flt(self.qty_available_to_produce)
        if flt(self.qty_to_produce) > available + 0.001:   # small tolerance
            frappe.throw(
                _("Qty to Produce ({0}) exceeds available open qty at this stage ({1}). "
                  "Check if earlier sessions already produced this quantity.").format(
                    self.qty_to_produce, available
                )
            )

    def _set_balance_fields(self):
        """Compute before/after running balance from previous sessions."""
        cumulative_before = self._get_cumulative_produced_before()
        planned = self._get_qty_planned()
        self.qty_cumulative_before = cumulative_before
        self.qty_open_before       = max(flt(planned) - cumulative_before, 0)
        self.qty_cumulative_after  = cumulative_before + flt(self.qty_produced)
        self.qty_open_after        = max(flt(planned) - self.qty_cumulative_after, 0)

    def _get_cumulative_produced_before(self):
        """Sum of qty_produced from all SUBMITTED entries for the same lot+operation,
        excluding the current document."""
        result = frappe.db.sql("""
            SELECT COALESCE(SUM(qty_produced), 0)
            FROM `tabSM Stage Production Entry`
            WHERE production_lot     = %s
              AND operation_row_name = %s
              AND docstatus          = 1
              AND name              != %s
        """, (self.production_lot, self.operation_row_name, self.name or ""))
        return flt(result[0][0]) if result else 0.0

    def _get_qty_planned(self):
        return flt(
            frappe.db.get_value("SM Lot Operation", self.operation_row_name, "qty_planned")
        )

    # ------------------------------------------------------------------
    # On Submit — create the partial Manufacture Stock Entry
    # ------------------------------------------------------------------

    def on_submit(self):
        self._create_manufacture_stock_entry()
        self._update_lot_operation()
        self.status = "Submitted"
        self.db_set("status", "Submitted")

    def _create_manufacture_stock_entry(self):
        """
        Creates a Manufacture-type Stock Entry for qty_produced.

        The SE is linked to the Work Order so ERPNext automatically updates
        WO.produced_qty.  Raw material consumption is proportional to qty_produced
        using the BOM rate.  The WO is NOT closed — it remains In Process.
        """
        wo = frappe.get_doc("Work Order", self.work_order)

        se = frappe.new_doc("Stock Entry")
        se.purpose            = "Manufacture"
        se.stock_entry_type   = "Manufacture"
        se.work_order         = self.work_order
        se.production_item    = self.wip_item_out
        se.bom_no             = wo.bom_no
        se.fg_completed_qty   = flt(self.qty_produced)
        se.posting_date       = self.posting_date
        se.posting_time       = self.posting_time
        se.from_bom           = 1
        se.use_multi_level_bom = 0
        se.sm_production_lot  = self.production_lot

        # Get items from BOM proportionally for qty_produced
        se.get_items()

        # Ensure source / target warehouses match the lot stage
        for item in se.items:
            if item.is_finished_item:
                item.t_warehouse = self.target_warehouse
            elif item.s_warehouse:
                item.s_warehouse = self.source_warehouse

        se.insert(ignore_permissions=True)
        se.submit()

        self.db_set("stock_entry", se.name)
        self.db_set("status", "Submitted")

        frappe.msgprint(
            _("Manufacture Stock Entry <b>{0}</b> created — {1} pcs moved to {2}.").format(
                se.name, self.qty_produced, self.target_warehouse
            ),
            alert=True,
        )

    def _update_lot_operation(self):
        """
        Refresh cumulative qty_produced and qty_open on the SM Lot Operation row.
        Uses DB aggregation to be safe against concurrent entries.
        """
        cumulative = frappe.db.sql("""
            SELECT COALESCE(SUM(qty_produced), 0), COALESCE(SUM(qty_rejected), 0)
            FROM `tabSM Stage Production Entry`
            WHERE production_lot     = %s
              AND operation_row_name = %s
              AND docstatus          = 1
        """, (self.production_lot, self.operation_row_name))

        total_produced  = flt(cumulative[0][0])
        total_rejected  = flt(cumulative[0][1])
        qty_planned     = self._get_qty_planned()
        qty_open        = max(qty_planned - total_produced, 0)

        # Determine new status
        if qty_open <= 0:
            new_status = "Completed"
            actual_end = now_datetime()
        else:
            new_status = "Partially Produced"
            actual_end = None

        update_vals = {
            "qty_produced":  total_produced,
            "qty_rejected":  total_rejected,
            "qty_open":      qty_open,
            "status":        new_status,
        }
        if actual_end:
            update_vals["actual_end"] = actual_end

        frappe.db.set_value("SM Lot Operation", self.operation_row_name, update_vals)

        # Refresh lot-level status
        lot = frappe.get_doc("SM Production Lot", self.production_lot)
        lot._update_lot_status()

    # ------------------------------------------------------------------
    # On Cancel — reverse the manufacture stock entry
    # ------------------------------------------------------------------

    def on_cancel(self):
        if self.stock_entry:
            se = frappe.get_doc("Stock Entry", self.stock_entry)
            if se.docstatus == 1:
                se.cancel()
            self.db_set("stock_entry", None)

        self.status = "Cancelled"
        self.db_set("status", "Cancelled")

        # Recompute lot operation balance
        self._update_lot_operation_after_cancel()

    def _update_lot_operation_after_cancel(self):
        cumulative = frappe.db.sql("""
            SELECT COALESCE(SUM(qty_produced), 0), COALESCE(SUM(qty_rejected), 0)
            FROM `tabSM Stage Production Entry`
            WHERE production_lot     = %s
              AND operation_row_name = %s
              AND docstatus          = 1
        """, (self.production_lot, self.operation_row_name))

        total_produced = flt(cumulative[0][0])
        total_rejected = flt(cumulative[0][1])
        qty_planned    = self._get_qty_planned()
        qty_open       = max(qty_planned - total_produced, 0)

        new_status = "In Progress" if total_produced > 0 else "In Progress"

        frappe.db.set_value("SM Lot Operation", self.operation_row_name, {
            "qty_produced": total_produced,
            "qty_rejected": total_rejected,
            "qty_open":     qty_open,
            "status":       new_status,
            "actual_end":   None,
        })

        lot = frappe.get_doc("SM Production Lot", self.production_lot)
        lot._update_lot_status()


# ---------------------------------------------------------------------------
# Whitelist — called from SM Production Lot JS
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_stage_production_summary(production_lot, operation_row_name):
    """
    Returns all production sessions for a lot + operation row.
    Used to populate the production history popup on the lot form.
    """
    entries = frappe.db.sql("""
        SELECT
            name, posting_date, posting_time,
            qty_to_produce, qty_produced, qty_rejected,
            qty_cumulative_after, qty_open_after,
            stock_entry, status, remarks
        FROM `tabSM Stage Production Entry`
        WHERE production_lot     = %s
          AND operation_row_name = %s
          AND docstatus         != 2
        ORDER BY posting_date, posting_time
    """, (production_lot, operation_row_name), as_dict=True)
    return entries
