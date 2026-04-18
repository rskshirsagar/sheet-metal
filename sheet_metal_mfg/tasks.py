"""
Scheduled Tasks — v2
Syncs lot operation status from linked Work Orders and Subcontracting Orders.
Note: SM Stage Production Entry updates ops directly on submit/cancel,
so this task is mainly a safety net for edge cases.
"""

import frappe
from frappe.utils import flt, now_datetime


def sync_lot_operation_status():
    active_lots = frappe.get_all(
        "SM Production Lot",
        filters={"docstatus": 1, "status": ["in", ["In Progress", "Partially Completed"]]},
        pluck="name",
    )
    for lot_name in active_lots:
        try:
            _sync_lot(lot_name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"SM Lot Sync Error: {lot_name}")


def _sync_lot(lot_name):
    lot = frappe.get_doc("SM Production Lot", lot_name)
    changed = False

    for row in lot.operations:
        # Recompute qty_produced from submitted Stage Production Entries
        result = frappe.db.sql("""
            SELECT COALESCE(SUM(qty_produced),0), COALESCE(SUM(qty_rejected),0)
            FROM `tabSM Stage Production Entry`
            WHERE production_lot = %s AND operation_row_name = %s AND docstatus = 1
        """, (lot_name, row.name))

        db_produced  = flt(result[0][0])
        db_rejected  = flt(result[0][1])
        qty_open     = max(flt(row.qty_planned) - db_produced, 0)

        update_vals = {}
        if abs(flt(row.qty_produced) - db_produced) > 0.001:
            update_vals["qty_produced"] = db_produced
            changed = True
        if abs(flt(row.qty_open) - qty_open) > 0.001:
            update_vals["qty_open"] = qty_open
            changed = True
        if db_rejected != flt(row.qty_rejected):
            update_vals["qty_rejected"] = db_rejected
            changed = True

        # Sync subcontract operation status from SC Order
        if row.execution_type == "Subcontract" and row.subcontracting_order:
            sc_status = frappe.db.get_value(
                "Subcontracting Order", row.subcontracting_order, "status")
            if sc_status == "Completed" and row.status != "Completed":
                rcvd = frappe.db.sql("""
                    SELECT COALESCE(SUM(i.qty),0)
                    FROM `tabSubcontracting Receipt Item` i
                    INNER JOIN `tabSubcontracting Receipt` r ON r.name = i.parent
                    WHERE i.subcontracting_order = %s AND r.docstatus = 1
                """, row.subcontracting_order)
                update_vals["qty_produced"]  = flt(rcvd[0][0])
                update_vals["qty_forwarded"] = flt(rcvd[0][0])
                update_vals["status"]        = "Completed"
                update_vals["actual_end"]    = now_datetime()
                changed = True

        if update_vals:
            frappe.db.set_value("SM Lot Operation", row.name, update_vals)

    if changed:
        lot._update_lot_status()
