"""
SM Production Lot — Controller  (v2 — Partial Production)
==========================================================
Governs a multi-stage sheet metal production batch.

v2 CHANGES — Partial Production without Process Loss:
  ─────────────────────────────────────────────────────
  • book_production()  — creates SM Stage Production Entry for partial
    manufacture. Work Order stays "In Process". Repeatable per stage.

  • close_stage()      — stops the Work Order via stop_work_order()
    (status = Stopped, ZERO stock movement, NO process loss SE).
    Sets qty_forwarded. Next stage uses qty_forwarded as its WO qty.

  ERPNext Process Loss — Why It Does NOT Happen Here:
    close_work_order() creates process loss.  We NEVER call it.
    stop_work_order() just sets status = Stopped with no stock impact.
    Remaining open qty stays in source WIP warehouse untouched.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, now_datetime, flt


class SMProductionLot(Document):

    def validate(self):
        self._validate_operation_sequence()
        self._validate_subcontract_supplier()
        self._set_qty_planned_from_lot()
        self._update_summary_counts()
        self._auto_fetch_bom()
        self._refresh_qty_open_on_all_rows()

    def _validate_operation_sequence(self):
        seqs = [row.operation_seq for row in self.operations]
        if len(seqs) != len(set(seqs)):
            frappe.throw(_("Operation sequence numbers must be unique."))
        for i, row in enumerate(self.operations):
            if i > 0 and row.operation_seq <= self.operations[i - 1].operation_seq:
                frappe.throw(
                    _("Operation sequence must be strictly increasing. Check row {0} ({1}).").format(
                        i + 1, row.operation))

    def _validate_subcontract_supplier(self):
        for row in self.operations:
            if row.execution_type == "Subcontract" and not row.supplier:
                frappe.throw(
                    _("Row {0}: Supplier is required for Subcontract operation '{1}'.").format(
                        row.operation_seq, row.operation))

    def _set_qty_planned_from_lot(self):
        for row in self.operations:
            if not row.qty_planned:
                row.qty_planned = self.qty

    def _update_summary_counts(self):
        self.total_operations       = len(self.operations)
        self.completed_operations   = sum(1 for r in self.operations if r.status == "Completed")
        self.in_progress_operations = sum(
            1 for r in self.operations if r.status in ("In Progress", "Partially Produced"))
        self.subcontract_operations = sum(1 for r in self.operations if r.execution_type == "Subcontract")
        self.inhouse_operations     = sum(1 for r in self.operations if r.execution_type == "In-House")

    def _auto_fetch_bom(self):
        for row in self.operations:
            if row.wip_item_out and not row.bom_no:
                bom = frappe.db.get_value(
                    "BOM", {"item": row.wip_item_out, "is_active": 1, "is_default": 1}, "name")
                if bom:
                    row.bom_no = bom

    def _refresh_qty_open_on_all_rows(self):
        for row in self.operations:
            row.qty_open = max(flt(row.qty_planned) - flt(row.qty_produced), 0)

    # ------------------------------------------------------------------
    def on_submit(self):
        self.db_set("status", "In Progress")
        self.db_set("actual_start_date", nowdate())
        frappe.msgprint(
            _("Production Lot {0} submitted. Create Work Orders using the operation row buttons.").format(self.name),
            alert=True)

    def on_cancel(self):
        self._block_cancel_if_open_docs()
        self.db_set("status", "Cancelled")

    def _block_cancel_if_open_docs(self):
        open_wo = frappe.get_all(
            "Work Order",
            filters={"sm_production_lot": self.name,
                     "status": ["not in", ["Completed", "Stopped", "Cancelled"]]},
            pluck="name")
        if open_wo:
            frappe.throw(
                _("Cannot cancel. Open Work Orders: {0}. Stop or cancel them first.").format(
                    ", ".join(open_wo)))
        open_spe = frappe.get_all(
            "SM Stage Production Entry",
            filters={"production_lot": self.name, "docstatus": 1},
            pluck="name")
        if open_spe:
            frappe.throw(
                _("Cannot cancel. Submitted Stage Production Entries exist: {0}.").format(
                    ", ".join(open_spe[:5])))

    # ------------------------------------------------------------------
    # Create Work Order
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def create_work_order(self, operation_row_name):
        row = self._get_operation_row(operation_row_name)
        self._validate_previous_op_closed(row)

        if row.execution_type != "In-House":
            frappe.throw(_("Operation '{0}' is Subcontract, not In-House.").format(row.operation))
        if row.work_order:
            frappe.throw(_("Work Order {0} already exists.").format(row.work_order))
        if not row.bom_no:
            frappe.throw(_("No active default BOM for item '{0}'.").format(row.wip_item_out))

        effective_qty = self._get_effective_qty_for_stage(row)
        source_wh     = self._get_source_warehouse_for_op(row)
        wip_wh        = _get_wip_warehouse_for_item(row.wip_item_out)

        wo = frappe.new_doc("Work Order")
        wo.production_item     = row.wip_item_out
        wo.bom_no              = row.bom_no
        wo.qty                 = effective_qty
        wo.planned_start_date  = self.planned_start_date
        wo.source_warehouse    = source_wh
        wo.wip_warehouse       = wip_wh
        wo.fg_warehouse        = wip_wh
        wo.use_multi_level_bom = 0
        wo.skip_transfer       = 0
        wo.sm_production_lot   = self.name
        wo.insert(ignore_permissions=True)
        wo.submit()

        frappe.db.set_value("SM Lot Operation", row.name, {
            "work_order":   wo.name,
            "qty_planned":  effective_qty,
            "qty_open":     effective_qty,
            "qty_produced": 0,
            "status":       "In Progress",
            "actual_start": now_datetime(),
        })
        self._update_lot_status()
        frappe.msgprint(
            _("Work Order <b>{0}</b> created for '{1}' — Qty: {2}").format(wo.name, row.operation, effective_qty),
            alert=True)
        return wo.name

    # ------------------------------------------------------------------
    # Book Production (partial) — IN-HOUSE
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def book_production(self, operation_row_name, qty_to_produce, qty_produced, qty_rejected=0):
        """
        Books one production session. Creates SM Stage Production Entry
        which creates a partial Manufacture SE. Work Order stays In Process.
        Repeatable — call multiple times per stage.
        """
        row = self._get_operation_row(operation_row_name)

        if row.execution_type != "In-House":
            frappe.throw(_("Book Production is only for In-House operations."))
        if not row.work_order:
            frappe.throw(_("Create a Work Order first."))
        if row.status not in ("In Progress", "Partially Produced"):
            frappe.throw(
                _("Operation must be In Progress or Partially Produced. Current: {0}").format(row.status))

        qty_open = flt(row.qty_planned) - flt(row.qty_produced)
        if qty_open <= 0:
            frappe.throw(_("No open quantity remaining at this stage."))
        if flt(qty_to_produce) > qty_open + 0.001:
            frappe.throw(
                _("Qty to Produce ({0}) exceeds open qty ({1}).").format(qty_to_produce, qty_open))

        source_wh = self._get_source_warehouse_for_op(row)
        target_wh = _get_wip_warehouse_for_item(row.wip_item_out)

        spe = frappe.new_doc("SM Stage Production Entry")
        spe.production_lot            = self.name
        spe.operation_row_name        = row.name
        spe.operation_seq             = row.operation_seq
        spe.operation                 = row.operation
        spe.work_order                = row.work_order
        spe.posting_date              = nowdate()
        spe.posting_time              = now_datetime().strftime("%H:%M:%S")
        spe.wip_item_in               = row.wip_item_in
        spe.wip_item_out              = row.wip_item_out
        spe.source_warehouse          = source_wh
        spe.target_warehouse          = target_wh
        spe.qty_available_to_produce  = qty_open
        spe.qty_to_produce            = flt(qty_to_produce)
        spe.qty_produced              = flt(qty_produced)
        spe.qty_rejected              = flt(qty_rejected)
        spe.uom                       = row.uom
        spe.insert(ignore_permissions=True)
        spe.submit()

        new_open = max(qty_open - flt(qty_produced), 0)
        frappe.msgprint(
            _("Production Entry <b>{0}</b> — {1} pcs produced. {2} pcs open remaining at this stage.").format(
                spe.name, flt(qty_produced), new_open),
            alert=True)
        return spe.name

    # ------------------------------------------------------------------
    # Close Stage — stop WO without process loss
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def close_stage(self, operation_row_name, qty_to_forward=None):
        """
        Finalises a stage after partial or full production.

        CRITICAL: calls wo.stop_work_order("Stopped") — NOT close_work_order().
        stop_work_order() sets WO status = Stopped with NO stock movement.
        Remaining open qty stays in source WIP warehouse. No process loss.
        """
        row = self._get_operation_row(operation_row_name)

        if row.execution_type != "In-House":
            frappe.throw(_("Close Stage is for In-House operations."))
        if row.status not in ("In Progress", "Partially Produced"):
            frappe.throw(
                _("Stage must be In Progress or Partially Produced. Current: {0}").format(row.status))
        if not row.work_order:
            frappe.throw(_("No Work Order linked to this stage."))

        qty_produced = flt(row.qty_produced)
        if qty_produced <= 0:
            frappe.throw(_("No production booked yet. Book at least one session first."))

        forward = flt(qty_to_forward) if qty_to_forward is not None else qty_produced
        if forward > qty_produced + 0.001:
            frappe.throw(
                _("Qty to Forward ({0}) cannot exceed Qty Produced ({1}).").format(forward, qty_produced))
        if forward <= 0:
            frappe.throw(_("Qty to Forward must be > 0."))

        # STOP WO — zero stock movement, no process loss
        wo = frappe.get_doc("Work Order", row.work_order)
        if wo.status not in ("Completed", "Stopped", "Cancelled"):
            wo.stop_work_order("Stopped")

        qty_not_produced = flt(row.qty_planned) - qty_produced
        frappe.db.set_value("SM Lot Operation", row.name, {
            "qty_forwarded": forward,
            "qty_open":      qty_not_produced,
            "status":        "Completed",
            "actual_end":    now_datetime(),
        })
        self._update_lot_status()

        frappe.msgprint(
            _("Stage <b>{0}</b> closed. {1} pcs forwarded. "
              "{2} pcs remain open in WIP warehouse (no process loss booked).").format(
                row.operation, forward, qty_not_produced),
            alert=True)
        return {"qty_forwarded": forward, "qty_open_remaining": qty_not_produced}

    # ------------------------------------------------------------------
    # Create Subcontracting Order
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def create_subcontracting_order(self, operation_row_name):
        row = self._get_operation_row(operation_row_name)
        self._validate_previous_op_closed(row)

        if row.execution_type != "Subcontract":
            frappe.throw(_("Operation '{0}' is In-House, not Subcontract.").format(row.operation))
        if row.subcontracting_order:
            frappe.throw(_("Subcontracting Order {0} already exists.").format(row.subcontracting_order))
        if not row.bom_no:
            frappe.throw(_("BOM is required."))

        effective_qty = self._get_effective_qty_for_stage(row)
        sc = frappe.new_doc("Subcontracting Order")
        sc.supplier          = row.supplier
        sc.schedule_date     = self.planned_end_date or nowdate()
        sc.sm_production_lot = self.name
        sc.append("items", {
            "item_code": row.wip_item_out,
            "qty":       effective_qty,
            "uom":       row.uom or frappe.db.get_value("Item", row.wip_item_out, "stock_uom"),
            "bom":       row.bom_no,
            "warehouse": _get_wip_warehouse_for_item(row.wip_item_out),
        })
        sc.insert(ignore_permissions=True)
        sc.save()

        frappe.db.set_value("SM Lot Operation", row.name, {
            "subcontracting_order": sc.name,
            "qty_planned":          effective_qty,
            "qty_open":             effective_qty,
            "status":               "In Progress",
            "actual_start":         now_datetime(),
        })
        self._update_lot_status()
        frappe.msgprint(
            _("Subcontracting Order <b>{0}</b> created — Qty: {1}").format(sc.name, effective_qty),
            alert=True)
        return sc.name

    # ------------------------------------------------------------------
    # Material Transfer to Subcontractor
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def create_material_transfer_to_subcontractor(self, operation_row_name):
        row = self._get_operation_row(operation_row_name)
        if row.execution_type != "Subcontract":
            frappe.throw(_("Only for Subcontract operations."))
        if not row.subcontracting_order:
            frappe.throw(_("Create Subcontracting Order first."))
        if row.stock_entry_transfer:
            frappe.throw(_("Transfer {0} already created.").format(row.stock_entry_transfer))

        source_wh = self._get_source_warehouse_for_op(row)
        target_wh = _get_subcontract_transit_warehouse()
        se = frappe.new_doc("Stock Entry")
        se.stock_entry_type  = "Material Transfer"
        se.purpose           = "Material Transfer"
        se.sm_production_lot = self.name
        se.append("items", {
            "item_code":            row.wip_item_in,
            "qty":                  flt(row.qty_planned),
            "uom":                  row.uom or frappe.db.get_value("Item", row.wip_item_in, "stock_uom"),
            "s_warehouse":          source_wh,
            "t_warehouse":          target_wh,
            "subcontracting_order": row.subcontracting_order,
        })
        se.insert(ignore_permissions=True)
        se.submit()

        frappe.db.set_value("SM Lot Operation", row.name, {
            "stock_entry_transfer": se.name,
            "status":               "Subcontract Sent",
        })
        frappe.msgprint(_("Material Transfer <b>{0}</b> created.").format(se.name), alert=True)
        return se.name

    # ------------------------------------------------------------------
    # Get production sessions (for JS popup)
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def get_production_sessions(self, operation_row_name):
        return frappe.db.sql("""
            SELECT name, posting_date, posting_time,
                   qty_to_produce, qty_produced, qty_rejected,
                   qty_cumulative_after, qty_open_after, stock_entry, status
            FROM `tabSM Stage Production Entry`
            WHERE production_lot = %s AND operation_row_name = %s AND docstatus != 2
            ORDER BY posting_date, posting_time
        """, (self.name, operation_row_name), as_dict=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_operation_row(self, row_name):
        for row in self.operations:
            if row.name == row_name:
                return row
        frappe.throw(_("Operation row {0} not found.").format(row_name))

    def _validate_previous_op_closed(self, row):
        for prev in self.operations:
            if prev.operation_seq < row.operation_seq:
                if prev.status not in ("Completed", "Skipped"):
                    frappe.throw(
                        _("Operation '{0}' (Seq {1}) must be Completed before starting '{2}' (Seq {3}). "
                          "If partially produced, use 'Close Stage' first. Current status: {4}").format(
                            prev.operation, prev.operation_seq,
                            row.operation, row.operation_seq, prev.status))

    def _get_effective_qty_for_stage(self, row):
        sorted_ops = sorted(self.operations, key=lambda r: r.operation_seq)
        for i, op in enumerate(sorted_ops):
            if op.operation_seq == row.operation_seq and i > 0:
                prev_op = sorted_ops[i - 1]
                if flt(prev_op.qty_forwarded) > 0:
                    return flt(prev_op.qty_forwarded)
        return flt(row.qty_planned)

    def _get_source_warehouse_for_op(self, row):
        if row.operation_seq == 1:
            return self.raw_material_warehouse or _get_rm_warehouse()
        sorted_ops = sorted(self.operations, key=lambda r: r.operation_seq)
        for i, op in enumerate(sorted_ops):
            if op.operation_seq == row.operation_seq and i > 0:
                return _get_wip_warehouse_for_item(sorted_ops[i - 1].wip_item_out)
        return _get_rm_warehouse()

    def _update_lot_status(self):
        self.reload()
        statuses = [r.status for r in self.operations]
        if all(s in ("Completed", "Skipped") for s in statuses):
            self.db_set("status", "Completed")
            self.db_set("actual_end_date", nowdate())
        elif any(s in ("In Progress", "Partially Produced", "Subcontract Sent", "Subcontract Received")
                 for s in statuses):
            self.db_set("status", "In Progress")
        elif any(s == "Completed" for s in statuses):
            self.db_set("status", "Partially Completed")
        total = len(self.operations)
        frappe.db.set_value("SM Production Lot", self.name, {
            "total_operations":       total,
            "completed_operations":   sum(1 for r in self.operations if r.status == "Completed"),
            "in_progress_operations": sum(1 for r in self.operations
                                         if r.status in ("In Progress", "Partially Produced")),
            "subcontract_operations": sum(1 for r in self.operations if r.execution_type == "Subcontract"),
            "inhouse_operations":     sum(1 for r in self.operations if r.execution_type == "In-House"),
        })


# ---------------------------------------------------------------------------
# Doc Events
# ---------------------------------------------------------------------------

def on_subcontracting_receipt_submit(doc, method):
    lot_name = doc.get("sm_production_lot")
    if not lot_name:
        sc_order = frappe.db.get_value(
            "Subcontracting Receipt Item", {"parent": doc.name}, "subcontracting_order")
        if sc_order:
            lot_name = frappe.db.get_value("Subcontracting Order", sc_order, "sm_production_lot")
    if not lot_name:
        return
    lot = frappe.get_doc("SM Production Lot", lot_name)
    for row in lot.operations:
        if not row.subcontracting_order:
            continue
        match = frappe.db.get_value(
            "Subcontracting Receipt Item",
            {"parent": doc.name, "subcontracting_order": row.subcontracting_order}, "name")
        if match:
            received_qty = sum(
                flt(i.qty) for i in doc.items
                if i.get("subcontracting_order") == row.subcontracting_order)
            frappe.db.set_value("SM Lot Operation", row.name, {
                "status":                 "Completed",
                "subcontracting_receipt": doc.name,
                "qty_produced":           received_qty,
                "qty_forwarded":          received_qty,
                "qty_open":               max(flt(row.qty_planned) - received_qty, 0),
                "actual_end":             now_datetime(),
            })
            lot._update_lot_status()
            break


def on_stock_entry_submit(doc, method):
    if doc.purpose != "Material Transfer":
        return
    lot_name = doc.get("sm_production_lot")
    if not lot_name:
        return
    lot = frappe.get_doc("SM Production Lot", lot_name)
    for row in lot.operations:
        if row.stock_entry_transfer == doc.name and row.status == "In Progress":
            frappe.db.set_value("SM Lot Operation", row.name, "status", "Subcontract Sent")
            break


def has_permission(doc, ptype, user):
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _get_wip_warehouse_for_item(item_code):
    wh = frappe.db.get_value(
        "Item Default", {"parent": item_code, "company": _default_company()}, "default_warehouse")
    if not wh:
        wh = frappe.db.get_value("Warehouse", {"warehouse_name": ["like", "WIP%"], "disabled": 0}, "name")
    return wh


def _get_subcontract_transit_warehouse():
    wh = frappe.db.get_value(
        "Warehouse", {"warehouse_name": ["like", "%Subcontract%Transit%"], "disabled": 0}, "name")
    if not wh:
        wh = frappe.db.get_value(
            "Warehouse", {"warehouse_name": ["like", "%Subcontract%"], "disabled": 0}, "name")
    return wh


def _get_rm_warehouse():
    wh = frappe.db.get_value(
        "Warehouse", {"warehouse_name": ["like", "%Raw Material%"], "disabled": 0}, "name")
    if not wh:
        wh = frappe.db.get_value("Warehouse", {"disabled": 0, "is_group": 0}, "name")
    return wh


def _default_company():
    return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
        "Global Defaults", "default_company")


@frappe.whitelist()
def get_operations_for_part(part):
    bom_name = frappe.db.get_value("BOM", {"item": part, "is_active": 1, "is_default": 1}, "name")
    if not bom_name:
        return []
    routing = frappe.db.get_value("BOM", bom_name, "routing")
    if not routing:
        return _infer_ops_from_bom_chain(part)
    return frappe.get_all(
        "BOM Operation", filters={"parent": bom_name},
        fields=["idx", "operation", "workstation", "time_in_mins"], order_by="idx")


def _infer_ops_from_bom_chain(finished_item):
    result, item, visited = [], finished_item, set()
    while item and item not in visited:
        visited.add(item)
        bom = frappe.db.get_value("BOM", {"item": item, "is_active": 1, "is_default": 1}, "name")
        if not bom:
            break
        for op in frappe.get_all("BOM Operation", filters={"parent": bom},
                                  fields=["operation", "workstation"], order_by="idx desc"):
            op["wip_item_out"] = item
            result.insert(0, op)
        raw = frappe.get_all("BOM Item", filters={"parent": bom, "is_sub_contracted_item": 0},
                              fields=["item_code"], order_by="idx", limit=1)
        item = raw[0].item_code if raw else None
    for i, row in enumerate(result):
        row["operation_seq"] = i + 1
    return result
