"""
Stage Production Summary
=========================
Shows every production session (SM Stage Production Entry) across all lots
and operations, with running balance: cumulative produced, open remaining,
yield per session.

Primary use:
  - Shop floor supervisor: how many produced today per operation
  - Management: WIP balance at each stage in real time
  - Auditor: full trail of every partial booking linked to its stock entry
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate


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
        {"label": _("Lot No"),           "fieldname": "production_lot",     "fieldtype": "Link",  "options": "SM Production Lot",       "width": 140},
        {"label": _("Part"),             "fieldname": "part",               "fieldtype": "Link",  "options": "Item",                    "width": 120},
        {"label": _("Part Name"),        "fieldname": "part_name",          "fieldtype": "Data",                                        "width": 160},
        {"label": _("Seq"),              "fieldname": "operation_seq",      "fieldtype": "Int",                                         "width":  50},
        {"label": _("Operation"),        "fieldname": "operation",          "fieldtype": "Data",                                        "width": 130},
        {"label": _("WIP Item Out"),     "fieldname": "wip_item_out",       "fieldtype": "Link",  "options": "Item",                    "width": 140},
        {"label": _("Session Date"),     "fieldname": "posting_date",       "fieldtype": "Date",                                        "width": 100},
        {"label": _("Session Time"),     "fieldname": "posting_time",       "fieldtype": "Time",                                        "width":  80},
        {"label": _("Session Qty"),      "fieldname": "qty_to_produce",     "fieldtype": "Float",                                       "width":  90},
        {"label": _("Produced (Good)"),  "fieldname": "qty_produced",       "fieldtype": "Float",                                       "width": 110},
        {"label": _("Rejected"),         "fieldname": "qty_rejected",       "fieldtype": "Float",                                       "width":  80},
        {"label": _("Cumul. Produced"),  "fieldname": "qty_cumulative_after","fieldtype": "Float",                                       "width": 110},
        {"label": _("Open Balance"),     "fieldname": "qty_open_after",     "fieldtype": "Float",                                       "width": 100},
        {"label": _("Stage Planned"),    "fieldname": "qty_planned",        "fieldtype": "Float",                                       "width": 100},
        {"label": _("Yield %"),          "fieldname": "yield_pct",          "fieldtype": "Percent",                                     "width":  80},
        {"label": _("Entry Status"),     "fieldname": "entry_status",       "fieldtype": "Data",                                        "width":  90},
        {"label": _("Op Status"),        "fieldname": "op_status",          "fieldtype": "Data",                                        "width": 110},
        {"label": _("Work Order"),       "fieldname": "work_order",         "fieldtype": "Link",  "options": "Work Order",              "width": 130},
        {"label": _("Stock Entry"),      "fieldname": "stock_entry",        "fieldtype": "Link",  "options": "Stock Entry",             "width": 130},
        {"label": _("SPE Name"),         "fieldname": "spe_name",           "fieldtype": "Link",  "options": "SM Stage Production Entry","width": 140},
    ]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def get_data(filters):
    lot_filter       = filters.get("production_lot")
    part_filter      = filters.get("part")
    operation_filter = filters.get("operation")
    from_date        = filters.get("from_date")
    to_date          = filters.get("to_date")
    op_status_filter = filters.get("op_status")

    conds = ["spe.docstatus != 2"]
    vals  = {}

    if lot_filter:
        conds.append("spe.production_lot = %(lot)s")
        vals["lot"] = lot_filter
    if part_filter:
        conds.append("spl.part = %(part)s")
        vals["part"] = part_filter
    if operation_filter:
        conds.append("spe.operation = %(operation)s")
        vals["operation"] = operation_filter
    if from_date:
        conds.append("spe.posting_date >= %(from_date)s")
        vals["from_date"] = from_date
    if to_date:
        conds.append("spe.posting_date <= %(to_date)s")
        vals["to_date"] = to_date
    if op_status_filter:
        conds.append("slo.status = %(op_status)s")
        vals["op_status"] = op_status_filter

    where = " AND ".join(conds)

    rows = frappe.db.sql("""
        SELECT
            spe.name              AS spe_name,
            spe.production_lot,
            spl.part,
            spl.part_name,
            spe.operation_seq,
            spe.operation,
            spe.wip_item_out,
            spe.posting_date,
            spe.posting_time,
            spe.qty_to_produce,
            spe.qty_produced,
            spe.qty_rejected,
            spe.qty_cumulative_after,
            spe.qty_open_after,
            spe.stock_entry,
            spe.status            AS entry_status,
            slo.qty_planned,
            slo.status            AS op_status,
            slo.work_order,
            slo.qty_forwarded
        FROM `tabSM Stage Production Entry` spe
        INNER JOIN `tabSM Production Lot` spl
            ON spl.name = spe.production_lot
        LEFT JOIN `tabSM Lot Operation` slo
            ON slo.name = spe.operation_row_name
        WHERE {where}
        ORDER BY spe.production_lot, spe.operation_seq, spe.posting_date, spe.posting_time
    """.format(where=where), vals, as_dict=True)

    result = []
    prev_lot_op = None

    for row in rows:
        # Group header when lot+operation changes
        lot_op_key = (row.production_lot, row.operation_seq)
        if lot_op_key != prev_lot_op:
            result.append(_make_group_header(row))
            prev_lot_op = lot_op_key

        # Yield per session
        if flt(row.qty_to_produce) > 0:
            row.yield_pct = round(flt(row.qty_produced) / flt(row.qty_to_produce) * 100, 1)
        else:
            row.yield_pct = 0

        row["indent"] = 1
        result.append(row)

    return result


def _make_group_header(row):
    op_status_label = row.get("op_status", "")
    status_icon = {"Completed": "✔", "Partially Produced": "⏳", "In Progress": "▶", "Pending": "○"}.get(
        op_status_label, ""
    )
    return {
        "production_lot": row.production_lot,
        "part":           row.part,
        "part_name":      row.part_name,
        "operation":      f"── Lot: {row.production_lot}  |  Seq {row.operation_seq}: {row.operation}  "
                          f"|  Planned: {row.qty_planned}  |  Status: {status_icon} {op_status_label}",
        "qty_planned":    row.qty_planned,
        "bold":           1,
        "indent":         0,
    }


# ---------------------------------------------------------------------------
# Chart — produced vs open per operation (latest snapshot)
# ---------------------------------------------------------------------------

def get_chart(data):
    if not data:
        return None

    # Take the latest session per operation as the snapshot
    op_snap = {}
    for row in data:
        if not row.get("operation_seq"):
            continue
        key = (row.get("production_lot"), row.get("operation_seq"))
        op_snap[key] = row   # last row wins (already ordered by date/time)

    labels   = [f"{v['operation']} ({v['production_lot']})" for v in op_snap.values()]
    produced = [flt(v.get("qty_cumulative_after", 0)) for v in op_snap.values()]
    open_qty = [flt(v.get("qty_open_after", 0))       for v in op_snap.values()]

    if not labels:
        return None

    return {
        "data": {
            "labels":   labels[:20],   # cap at 20 bars
            "datasets": [
                {"name": _("Cumulative Produced"), "values": produced[:20]},
                {"name": _("Open Balance"),        "values": open_qty[:20]},
            ],
        },
        "type":   "bar",
        "colors": ["#2E75B6", "#e74c3c"],
        "title":  _("Produced vs Open Balance by Stage"),
        "barOptions": {"stacked": 1},
    }


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

def get_summary(data):
    sessions    = [r for r in data if r.get("indent") == 1]
    total_prod  = sum(flt(r.get("qty_produced", 0)) for r in sessions)
    total_rej   = sum(flt(r.get("qty_rejected", 0)) for r in sessions)
    lots        = len(set(r.get("production_lot") for r in sessions))
    ops_partial = len(set(
        (r.get("production_lot"), r.get("operation_seq"))
        for r in sessions if r.get("op_status") == "Partially Produced"
    ))

    return [
        {"label": _("Total Sessions"),      "value": len(sessions),   "indicator": "blue"},
        {"label": _("Total Pcs Produced"),  "value": total_prod,      "indicator": "green"},
        {"label": _("Total Pcs Rejected"),  "value": total_rej,       "indicator": "red"},
        {"label": _("Active Lots"),         "value": lots,            "indicator": "orange"},
        {"label": _("Partial Stages Open"), "value": ops_partial,     "indicator": "yellow"},
    ]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def get_filters():
    return [
        {
            "fieldname": "production_lot",
            "label":     _("Production Lot"),
            "fieldtype": "Link",
            "options":   "SM Production Lot",
        },
        {
            "fieldname": "part",
            "label":     _("Part"),
            "fieldtype": "Link",
            "options":   "Item",
        },
        {
            "fieldname": "operation",
            "label":     _("Operation"),
            "fieldtype": "Link",
            "options":   "Operation",
        },
        {
            "fieldname": "from_date",
            "label":     _("From Date"),
            "fieldtype": "Date",
            "default":   nowdate(),
        },
        {
            "fieldname": "to_date",
            "label":     _("To Date"),
            "fieldtype": "Date",
            "default":   nowdate(),
        },
        {
            "fieldname": "op_status",
            "label":     _("Stage Status"),
            "fieldtype": "Select",
            "options":   "\nIn Progress\nPartially Produced\nCompleted",
        },
    ]
