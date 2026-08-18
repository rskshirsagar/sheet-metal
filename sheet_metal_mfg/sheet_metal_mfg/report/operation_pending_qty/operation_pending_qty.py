"""
Operation Pending Qty
=====================
Shows operations where material is waiting (WIP stock exists in the
input warehouse) but the operation has NOT yet been started.
Identifies bottleneck operations across all active lots.

Grouped by Operation for workstation-level planning.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate, date_diff


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data    = get_data(filters)
    chart   = get_chart(data)
    summary = get_summary(data)
    return columns, data, None, chart, summary


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def get_columns():
    return [
        {"label": _("Operation"),        "fieldname": "operation",       "fieldtype": "Data",                              "width": 150},
        {"label": _("Workstation"),      "fieldname": "workstation",     "fieldtype": "Link",  "options": "Workstation",  "width": 140},
        {"label": _("Lot No"),           "fieldname": "lot_no",          "fieldtype": "Link",  "options": "SM Production Lot", "width": 140},
        {"label": _("Part"),             "fieldname": "part",            "fieldtype": "Link",  "options": "Item",          "width": 130},
        {"label": _("Part Name"),        "fieldname": "part_name",       "fieldtype": "Data",                              "width": 180},
        {"label": _("Priority"),         "fieldname": "priority",        "fieldtype": "Data",                              "width":  80},
        {"label": _("WIP Item Waiting"), "fieldname": "wip_item_in",     "fieldtype": "Link",  "options": "Item",          "width": 150},
        {"label": _("Qty Planned"),      "fieldname": "qty_planned",     "fieldtype": "Float",                             "width":  90},
        {"label": _("Stock Available"),  "fieldname": "stock_available", "fieldtype": "Float",                             "width": 110},
        {"label": _("Execution Type"),   "fieldname": "execution_type",  "fieldtype": "Data",                              "width":  90},
        {"label": _("Supplier"),         "fieldname": "supplier",        "fieldtype": "Link",  "options": "Supplier",     "width": 140},
        {"label": _("Op Status"),        "fieldname": "status",          "fieldtype": "Data",                              "width": 110},
        {"label": _("Prev Op End"),      "fieldname": "prev_op_end",     "fieldtype": "Datetime",                          "width": 140},
        {"label": _("Days Waiting"),     "fieldname": "days_waiting",    "fieldtype": "Int",                               "width":  90},
        {"label": _("Planned Start"),    "fieldname": "planned_start",   "fieldtype": "Date",                              "width": 110},
        {"label": _("Overdue"),          "fieldname": "overdue",         "fieldtype": "Check",                             "width":  70},
    ]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def get_data(filters):
    operation_filter = filters.get("operation")
    execution_filter = filters.get("execution_type")
    priority_filter  = filters.get("priority")
    overdue_only     = filters.get("overdue_only")

    conds = [
        "spl.docstatus = 1",
        "spl.status NOT IN ('Completed', 'Cancelled')",
        "slo.status = 'Pending'",
    ]
    vals = {}

    if operation_filter:
        conds.append("slo.operation = %(operation)s")
        vals["operation"] = operation_filter
    if execution_filter:
        conds.append("slo.execution_type = %(execution_type)s")
        vals["execution_type"] = execution_filter
    if priority_filter:
        conds.append("spl.priority = %(priority)s")
        vals["priority"] = priority_filter

    where = " AND ".join(conds)

    rows = frappe.db.sql("""
        SELECT
            slo.operation,
            slo.workstation,
            spl.name            AS lot_no,
            spl.part,
            spl.part_name,
            spl.priority,
            spl.planned_start_date AS planned_start,
            slo.wip_item_in,
            slo.wip_item_out,
            slo.qty_planned,
            slo.execution_type,
            slo.supplier,
            slo.status,
            slo.operation_seq,
            slo.name            AS op_row_name
        FROM `tabSM Production Lot` spl
        INNER JOIN `tabSM Lot Operation` slo ON slo.parent = spl.name
        WHERE {where}
        ORDER BY
            FIELD(spl.priority, 'Urgent', 'High', 'Normal'),
            spl.planned_start_date,
            slo.operation_seq
    """.format(where=where), vals, as_dict=True)

    # Enrich: get previous op end time and current WIP stock
    result = []
    today  = nowdate()

    for row in rows:
        # Previous op actual_end
        prev_end = frappe.db.sql("""
            SELECT actual_end FROM `tabSM Lot Operation`
            WHERE parent = %s AND operation_seq < %s
            ORDER BY operation_seq DESC LIMIT 1
        """, (row.lot_no, row.operation_seq))
        row.prev_op_end = prev_end[0][0] if prev_end else None

        # Days waiting since previous op ended
        if row.prev_op_end:
            from frappe.utils import getdate
            row.days_waiting = date_diff(today, getdate(row.prev_op_end))
        else:
            row.days_waiting = 0

        # Actual stock of WIP item in
        if row.wip_item_in:
            stock = frappe.db.sql("""
                SELECT SUM(b.actual_qty)
                FROM `tabBin` b
                INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
                WHERE b.item_code = %s
                  AND (w.warehouse_name LIKE '%%WIP%%'
                       OR w.warehouse_name LIKE '%%Raw Material%%')
            """, row.wip_item_in)
            row.stock_available = flt(stock[0][0]) if stock else 0
        else:
            row.stock_available = 0

        # Overdue flag
        row.overdue = 1 if row.planned_start and row.planned_start < today else 0

        if overdue_only and not row.overdue:
            continue

        result.append(row)

    return result


# ---------------------------------------------------------------------------
# Chart — pending qty grouped by operation
# ---------------------------------------------------------------------------

def get_chart(data):
    if not data:
        return None

    op_qty = {}
    for row in data:
        op = row.get("operation", "")
        op_qty[op] = op_qty.get(op, 0) + flt(row.get("qty_planned", 0))

    # Sort by qty descending
    sorted_ops = sorted(op_qty.items(), key=lambda x: -x[1])
    labels = [o[0] for o in sorted_ops]
    values = [o[1] for o in sorted_ops]

    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Pending Qty"), "values": values}],
        },
        "type": "bar",
        "colors": ["#f39c12"],
        "title": _("Pending Qty by Operation"),
    }


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

def get_summary(data):
    total_pending  = len(data)
    urgent_pending = sum(1 for r in data if r.get("priority") == "Urgent")
    overdue        = sum(1 for r in data if r.get("overdue"))
    subcon_pending = sum(1 for r in data if r.get("execution_type") == "Subcontract")

    return [
        {"label": _("Total Pending Ops"),  "value": total_pending,  "indicator": "blue"},
        {"label": _("Urgent"),             "value": urgent_pending, "indicator": "red"},
        {"label": _("Overdue"),            "value": overdue,        "indicator": "orange"},
        {"label": _("Pending Subcontract"),"value": subcon_pending, "indicator": "purple"},
    ]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def get_filters():
    return [
        {
            "fieldname": "operation",
            "label": _("Operation"),
            "fieldtype": "Link",
            "options": "Operation",
        },
        {
            "fieldname": "execution_type",
            "label": _("Execution Type"),
            "fieldtype": "Select",
            "options": "\nIn-House\nSubcontract",
        },
        {
            "fieldname": "priority",
            "label": _("Priority"),
            "fieldtype": "Select",
            "options": "\nNormal\nHigh\nUrgent",
        },
        {
            "fieldname": "overdue_only",
            "label": _("Overdue Only"),
            "fieldtype": "Check",
            "default": 0,
        },
    ]
