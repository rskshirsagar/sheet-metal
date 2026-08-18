"""
Subcontract Status Tracker
==========================
All open subcontract operations across lots — tracks material sent,
material received, pending receipt, and aging at each supplier.

Critical for purchase follow-up and supplier performance.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate, date_diff, getdate


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
        {"label": _("Lot No"),              "fieldname": "lot_no",           "fieldtype": "Link",     "options": "SM Production Lot",     "width": 140},
        {"label": _("Part"),                "fieldname": "part",             "fieldtype": "Link",     "options": "Item",                  "width": 130},
        {"label": _("Part Name"),           "fieldname": "part_name",        "fieldtype": "Data",                                         "width": 170},
        {"label": _("Operation"),           "fieldname": "operation",        "fieldtype": "Data",                                         "width": 140},
        {"label": _("Seq"),                 "fieldname": "operation_seq",    "fieldtype": "Int",                                          "width":  50},
        {"label": _("Supplier"),            "fieldname": "supplier",         "fieldtype": "Link",     "options": "Supplier",              "width": 150},
        {"label": _("WIP Item Out"),        "fieldname": "wip_item_out",     "fieldtype": "Link",     "options": "Item",                  "width": 150},
        {"label": _("Qty Planned"),         "fieldname": "qty_planned",      "fieldtype": "Float",                                        "width":  90},
        {"label": _("Op Status"),           "fieldname": "status",           "fieldtype": "Data",                                         "width": 130},
        {"label": _("Material Sent"),       "fieldname": "material_sent",    "fieldtype": "Check",                                        "width":  90},
        {"label": _("SC Order"),            "fieldname": "subcontracting_order", "fieldtype": "Link", "options": "Subcontracting Order",  "width": 140},
        {"label": _("SC Order Date"),       "fieldname": "sc_order_date",    "fieldtype": "Date",                                         "width": 110},
        {"label": _("Expected Receipt"),    "fieldname": "schedule_date",    "fieldtype": "Date",                                         "width": 120},
        {"label": _("Days at Supplier"),    "fieldname": "days_at_supplier", "fieldtype": "Int",                                          "width": 110},
        {"label": _("Overdue Days"),        "fieldname": "overdue_days",     "fieldtype": "Int",                                          "width":  90},
        {"label": _("Qty Received"),        "fieldname": "qty_received",     "fieldtype": "Float",                                        "width":  90},
        {"label": _("SC Receipt"),          "fieldname": "subcontracting_receipt", "fieldtype": "Link", "options": "Subcontracting Receipt", "width": 140},
        {"label": _("Transfer SE"),         "fieldname": "stock_entry_transfer", "fieldtype": "Link", "options": "Stock Entry",           "width": 120},
        {"label": _("Priority"),            "fieldname": "priority",         "fieldtype": "Data",                                         "width":  80},
        {"label": _("Remarks"),             "fieldname": "remarks",          "fieldtype": "Data",                                         "width": 180},
    ]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def get_data(filters):
    supplier_filter = filters.get("supplier")
    status_filter   = filters.get("op_status")
    overdue_only    = filters.get("overdue_only")
    from_date       = filters.get("from_date")
    to_date         = filters.get("to_date")

    conds = [
        "spl.docstatus = 1",
        "spl.status NOT IN ('Cancelled')",
        "slo.execution_type = 'Subcontract'",
        "slo.status NOT IN ('Completed', 'Skipped', 'Pending')",
    ]
    vals = {}

    if supplier_filter:
        conds.append("slo.supplier = %(supplier)s")
        vals["supplier"] = supplier_filter
    if status_filter:
        conds.append("slo.status = %(op_status)s")
        vals["op_status"] = status_filter
    if from_date:
        conds.append("spl.planned_start_date >= %(from_date)s")
        vals["from_date"] = from_date
    if to_date:
        conds.append("spl.planned_start_date <= %(to_date)s")
        vals["to_date"] = to_date

    where = " AND ".join(conds)

    rows = frappe.db.sql("""
        SELECT
            spl.name                AS lot_no,
            spl.part,
            spl.part_name,
            spl.priority,
            slo.operation,
            slo.operation_seq,
            slo.supplier,
            slo.wip_item_out,
            slo.qty_planned,
            slo.status,
            slo.subcontracting_order,
            slo.subcontracting_receipt,
            slo.stock_entry_transfer,
            slo.actual_start,
            slo.actual_end,
            slo.remarks
        FROM `tabSM Production Lot` spl
        INNER JOIN `tabSM Lot Operation` slo ON slo.parent = spl.name
        WHERE {where}
        ORDER BY
            FIELD(spl.priority, 'Urgent', 'High', 'Normal'),
            slo.actual_start
    """.format(where=where), vals, as_dict=True)

    today = nowdate()
    result = []

    for row in rows:
        # SC Order details
        sc_details = {}
        if row.subcontracting_order:
            sc_details = frappe.db.get_value(
                "Subcontracting Order",
                row.subcontracting_order,
                ["transaction_date", "schedule_date", "status"],
                as_dict=True,
            ) or {}

        row.sc_order_date = sc_details.get("transaction_date")
        row.schedule_date = sc_details.get("schedule_date")

        # Days at supplier — from material transfer date
        if row.stock_entry_transfer:
            se_date = frappe.db.get_value("Stock Entry", row.stock_entry_transfer, "posting_date")
            row.days_at_supplier = date_diff(today, se_date) if se_date else 0
            row.material_sent    = 1
        else:
            row.days_at_supplier = 0
            row.material_sent    = 0

        # Overdue days
        if row.schedule_date and row.schedule_date < today and row.status != "Completed":
            row.overdue_days = date_diff(today, row.schedule_date)
        else:
            row.overdue_days = 0

        # Qty received from SC Receipt
        if row.subcontracting_receipt:
            qty_rcvd = frappe.db.sql("""
                SELECT SUM(qty) FROM `tabSubcontracting Receipt Item`
                WHERE parent = %s
            """, row.subcontracting_receipt)
            row.qty_received = flt(qty_rcvd[0][0]) if qty_rcvd else 0
        else:
            row.qty_received = 0

        if overdue_only and not row.overdue_days:
            continue

        result.append(row)

    return result


# ---------------------------------------------------------------------------
# Chart — aging bar by supplier
# ---------------------------------------------------------------------------

def get_chart(data):
    if not data:
        return None

    supplier_days = {}
    for row in data:
        sup = row.get("supplier") or "Unknown"
        days = flt(row.get("days_at_supplier", 0))
        if sup not in supplier_days:
            supplier_days[sup] = []
        supplier_days[sup].append(days)

    # Average days per supplier
    labels = list(supplier_days.keys())
    values = [round(sum(v) / len(v), 1) for v in supplier_days.values()]

    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Avg Days at Supplier"), "values": values}],
        },
        "type": "bar",
        "colors": ["#9b59b6"],
        "title": _("Average Days at Supplier"),
    }


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

def get_summary(data):
    total      = len(data)
    overdue    = sum(1 for r in data if r.get("overdue_days", 0) > 0)
    sent       = sum(1 for r in data if r.get("material_sent"))
    not_sent   = total - sent
    avg_age    = round(sum(flt(r.get("days_at_supplier", 0)) for r in data) / total, 1) if total else 0

    return [
        {"label": _("Open Subcon Ops"),    "value": total,    "indicator": "blue"},
        {"label": _("Material Not Sent"),  "value": not_sent, "indicator": "orange"},
        {"label": _("Overdue"),            "value": overdue,  "indicator": "red"},
        {"label": _("Avg Days at Vendor"), "value": avg_age,  "indicator": "grey"},
    ]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def get_filters():
    return [
        {
            "fieldname": "supplier",
            "label": _("Supplier"),
            "fieldtype": "Link",
            "options": "Supplier",
        },
        {
            "fieldname": "op_status",
            "label": _("Op Status"),
            "fieldtype": "Select",
            "options": "\nIn Progress\nSubcontract Sent\nSubcontract Received",
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
            "fieldname": "overdue_only",
            "label": _("Overdue Only"),
            "fieldtype": "Check",
            "default": 0,
        },
    ]
