"""
WIP Stage Summary
=================
Shows current stock (qty + value) of all WIP items across all WIP warehouses.
Filters: company, warehouse (optional), item_group (optional), as_of_date.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data    = get_data(filters)
    chart   = get_chart(data)
    return columns, data, None, chart


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

def get_columns():
    return [
        {"label": _("Warehouse / Stage"), "fieldname": "warehouse",      "fieldtype": "Link",     "options": "Warehouse",  "width": 200},
        {"label": _("Item Code"),          "fieldname": "item_code",      "fieldtype": "Link",     "options": "Item",       "width": 160},
        {"label": _("Item Name"),          "fieldname": "item_name",      "fieldtype": "Data",                              "width": 200},
        {"label": _("Item Group"),         "fieldname": "item_group",     "fieldtype": "Link",     "options": "Item Group", "width": 130},
        {"label": _("Qty in Hand"),        "fieldname": "qty_in_hand",    "fieldtype": "Float",                             "width": 110},
        {"label": _("UOM"),                "fieldname": "uom",            "fieldtype": "Link",     "options": "UOM",        "width":  80},
        {"label": _("Valuation Rate"),     "fieldname": "valuation_rate", "fieldtype": "Currency",                          "width": 130},
        {"label": _("Stock Value"),        "fieldname": "stock_value",    "fieldtype": "Currency",                          "width": 140},
        {"label": _("Pending Next Op"),    "fieldname": "pending_next",   "fieldtype": "Check",                             "width": 120},
        {"label": _("Next Operation"),     "fieldname": "next_operation", "fieldtype": "Data",                              "width": 150},
        {"label": _("Lot No"),             "fieldname": "lot_no",         "fieldtype": "Link",     "options": "SM Production Lot", "width": 140},
    ]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def get_data(filters):
    company     = filters.get("company") or frappe.defaults.get_user_default("Company")
    as_of_date  = filters.get("as_of_date") or nowdate()
    wh_filter   = filters.get("warehouse")
    grp_filter  = filters.get("item_group")

    # Base query — get current stock from bin for WIP warehouses
    wh_cond = ""
    if wh_filter:
        wh_cond = "AND b.warehouse = %(warehouse)s"

    grp_cond = ""
    if grp_filter:
        grp_cond = "AND i.item_group = %(item_group)s"

    rows = frappe.db.sql("""
        SELECT
            b.warehouse,
            b.item_code,
            i.item_name,
            i.item_group,
            i.stock_uom  AS uom,
            b.actual_qty AS qty_in_hand,
            b.valuation_rate,
            b.stock_value
        FROM `tabBin` b
        INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
        INNER JOIN `tabItem` i      ON i.name = b.item_code
        WHERE
            b.actual_qty  > 0
            AND w.disabled = 0
            AND (
                w.warehouse_name LIKE '%%WIP%%'
                OR w.warehouse_name LIKE '%%Subcontract%%Transit%%'
            )
            {wh_cond}
            {grp_cond}
        ORDER BY b.warehouse, b.item_code
    """.format(wh_cond=wh_cond, grp_cond=grp_cond),
    {"warehouse": wh_filter, "item_group": grp_filter},
    as_dict=True)

    # Enrich with lot and next operation info
    lot_map = _build_lot_map()

    result = []
    for row in rows:
        key = row.item_code
        lot_info = lot_map.get(key, {})
        row.pending_next  = lot_info.get("pending_next", 0)
        row.next_operation = lot_info.get("next_operation", "")
        row.lot_no        = lot_info.get("lot_no", "")
        result.append(row)

    return result


def _build_lot_map():
    """
    For each WIP item currently in an active lot, identify whether
    the next operation has been started yet.
    """
    active_ops = frappe.db.sql("""
        SELECT
            slo.wip_item_out   AS item_code,
            slo.status,
            slo.operation      AS current_op,
            slo.parent         AS lot_no,
            slo.operation_seq
        FROM `tabSM Lot Operation` slo
        INNER JOIN `tabSM Production Lot` spl ON spl.name = slo.parent
        WHERE spl.docstatus = 1
          AND spl.status NOT IN ('Completed', 'Cancelled')
          AND slo.status IN ('Completed', 'In Progress', 'Subcontract Sent')
        ORDER BY slo.operation_seq
    """, as_dict=True)

    lot_map = {}
    for op in active_ops:
        # Find the NEXT pending op in the same lot
        next_ops = frappe.db.sql("""
            SELECT operation FROM `tabSM Lot Operation`
            WHERE parent = %s AND operation_seq > %s AND status = 'Pending'
            ORDER BY operation_seq LIMIT 1
        """, (op.lot_no, op.operation_seq), as_dict=True)

        lot_map[op.item_code] = {
            "lot_no": op.lot_no,
            "pending_next": 1 if next_ops else 0,
            "next_operation": next_ops[0].operation if next_ops else "",
        }
    return lot_map


# ---------------------------------------------------------------------------
# Chart — bar chart of stock value per warehouse
# ---------------------------------------------------------------------------

def get_chart(data):
    if not data:
        return None

    wh_value = {}
    for row in data:
        wh = row.get("warehouse", "")
        wh_value[wh] = wh_value.get(wh, 0) + flt(row.get("stock_value", 0))

    labels  = list(wh_value.keys())
    values  = [wh_value[l] for l in labels]

    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Stock Value"), "values": values}],
        },
        "type": "bar",
        "colors": ["#e74c3c"],
        "title": _("WIP Stock Value by Stage"),
    }


# ---------------------------------------------------------------------------
# Filters definition (returned to Frappe report framework)
# ---------------------------------------------------------------------------

def get_filters():
    return [
        {
            "fieldname": "company",
            "label": _("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company"),
        },
        {
            "fieldname": "warehouse",
            "label": _("Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
        },
        {
            "fieldname": "item_group",
            "label": _("Item Group"),
            "fieldtype": "Link",
            "options": "Item Group",
        },
        {
            "fieldname": "as_of_date",
            "label": _("As of Date"),
            "fieldtype": "Date",
            "default": nowdate(),
        },
    ]
