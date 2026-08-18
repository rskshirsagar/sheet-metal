"""
Lot Traveller
=============
Full operation-by-operation status card for a single SM Production Lot.
Used as the shop-floor traveller document printed and attached to the job.

Filters: lot_no (mandatory), or date range to list multiple lots.
"""

import frappe
from frappe import _
from frappe.utils import flt, fmt_money


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data    = get_data(filters)
    return columns, data


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def get_columns():
    return [
        {"label": _("Lot No"),          "fieldname": "lot_no",           "fieldtype": "Link",     "options": "SM Production Lot", "width": 140},
        {"label": _("Part"),            "fieldname": "part",             "fieldtype": "Link",     "options": "Item",             "width": 130},
        {"label": _("Part Name"),       "fieldname": "part_name",        "fieldtype": "Data",                                    "width": 180},
        {"label": _("Lot Qty"),         "fieldname": "lot_qty",          "fieldtype": "Float",                                   "width":  80},
        {"label": _("Seq"),             "fieldname": "operation_seq",    "fieldtype": "Int",                                     "width":  50},
        {"label": _("Operation"),       "fieldname": "operation",        "fieldtype": "Data",                                    "width": 140},
        {"label": _("Execution"),       "fieldname": "execution_type",   "fieldtype": "Data",                                    "width":  90},
        {"label": _("Supplier"),        "fieldname": "supplier",         "fieldtype": "Link",     "options": "Supplier",         "width": 140},
        {"label": _("WIP Item In"),     "fieldname": "wip_item_in",      "fieldtype": "Link",     "options": "Item",             "width": 140},
        {"label": _("WIP Item Out"),    "fieldname": "wip_item_out",     "fieldtype": "Link",     "options": "Item",             "width": 140},
        {"label": _("Qty Planned"),     "fieldname": "qty_planned",      "fieldtype": "Float",                                   "width":  90},
        {"label": _("Qty Actual"),      "fieldname": "qty_actual",       "fieldtype": "Float",                                   "width":  90},
        {"label": _("Qty Rejected"),    "fieldname": "qty_rejected",     "fieldtype": "Float",                                   "width":  90},
        {"label": _("Yield %"),         "fieldname": "yield_pct",        "fieldtype": "Percent",                                 "width":  80},
        {"label": _("Status"),          "fieldname": "status",           "fieldtype": "Data",                                    "width": 130},
        {"label": _("Work Order"),      "fieldname": "work_order",       "fieldtype": "Link",     "options": "Work Order",       "width": 130},
        {"label": _("SC Order"),        "fieldname": "subcontracting_order", "fieldtype": "Link", "options": "Subcontracting Order", "width": 130},
        {"label": _("Actual Start"),    "fieldname": "actual_start",     "fieldtype": "Datetime",                                "width": 140},
        {"label": _("Actual End"),      "fieldname": "actual_end",       "fieldtype": "Datetime",                                "width": 140},
        {"label": _("Cycle Time (h)"),  "fieldname": "cycle_hours",      "fieldtype": "Float",                                   "width":  90},
        {"label": _("Remarks"),         "fieldname": "remarks",          "fieldtype": "Data",                                    "width": 180},
    ]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def get_data(filters):
    lot_no          = filters.get("lot_no")
    from_date       = filters.get("from_date")
    to_date         = filters.get("to_date")
    status_filter   = filters.get("status")
    part_filter     = filters.get("part")

    conditions = ["spl.docstatus = 1"]
    values = {}

    if lot_no:
        conditions.append("spl.name = %(lot_no)s")
        values["lot_no"] = lot_no
    if from_date:
        conditions.append("spl.planned_start_date >= %(from_date)s")
        values["from_date"] = from_date
    if to_date:
        conditions.append("spl.planned_start_date <= %(to_date)s")
        values["to_date"] = to_date
    if status_filter:
        conditions.append("spl.status = %(lot_status)s")
        values["lot_status"] = status_filter
    if part_filter:
        conditions.append("spl.part = %(part)s")
        values["part"] = part_filter

    where = " AND ".join(conditions)

    rows = frappe.db.sql("""
        SELECT
            spl.name            AS lot_no,
            spl.part,
            spl.part_name,
            spl.qty             AS lot_qty,
            spl.status          AS lot_status,
            spl.priority,
            spl.planned_start_date,
            slo.operation_seq,
            slo.operation,
            slo.execution_type,
            slo.supplier,
            slo.wip_item_in,
            slo.wip_item_out,
            slo.qty_planned,
            slo.qty_actual,
            slo.qty_rejected,
            slo.status,
            slo.work_order,
            slo.job_card,
            slo.subcontracting_order,
            slo.subcontracting_receipt,
            slo.stock_entry_transfer,
            slo.actual_start,
            slo.actual_end,
            slo.remarks
        FROM `tabSM Production Lot` spl
        INNER JOIN `tabSM Lot Operation` slo ON slo.parent = spl.name
        WHERE {where}
        ORDER BY spl.planned_start_date, spl.name, slo.operation_seq
    """.format(where=where), values, as_dict=True)

    result = []
    prev_lot = None

    for row in rows:
        # Insert a group header row when lot changes
        if row.lot_no != prev_lot:
            result.append(_make_lot_header(row))
            prev_lot = row.lot_no

        # Yield %
        if flt(row.qty_planned) > 0 and flt(row.qty_actual) > 0:
            row.yield_pct = round((flt(row.qty_actual) / flt(row.qty_planned)) * 100, 1)
        else:
            row.yield_pct = 0

        # Cycle time in hours
        if row.actual_start and row.actual_end:
            from frappe.utils import time_diff_in_hours
            row.cycle_hours = round(time_diff_in_hours(row.actual_end, row.actual_start), 2)
        else:
            row.cycle_hours = 0

        row["indent"] = 1
        result.append(row)

    return result


def _make_lot_header(row):
    return {
        "lot_no":           row.lot_no,
        "part":             row.part,
        "part_name":        row.part_name,
        "lot_qty":          row.lot_qty,
        "operation":        "── LOT: {0} | Part: {1} | Status: {2} | Priority: {3}".format(
                                row.lot_no, row.part_name, row.lot_status, row.priority),
        "bold":             1,
        "indent":           0,
    }


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def get_filters():
    return [
        {
            "fieldname": "lot_no",
            "label": _("Lot No"),
            "fieldtype": "Link",
            "options": "SM Production Lot",
        },
        {
            "fieldname": "part",
            "label": _("Part"),
            "fieldtype": "Link",
            "options": "Item",
        },
        {
            "fieldname": "from_date",
            "label": _("From Date"),
            "fieldtype": "Date",
        },
        {
            "fieldname": "to_date",
            "label": _("To Date"),
            "fieldtype": "Date",
        },
        {
            "fieldname": "status",
            "label": _("Lot Status"),
            "fieldtype": "Select",
            "options": "\nIn Progress\nPartially Completed\nCompleted",
        },
    ]
