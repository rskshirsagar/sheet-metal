"""
Patch: create_wip_warehouses
============================
Runs once on app install (bench migrate).
1. Creates the WIP warehouse tree under the company's main warehouse.
2. Adds sm_production_lot Link field to Work Order and Subcontracting Order.
3. Creates a default Item Group "Sheet Metal WIP" if not exists.
"""

import frappe
from frappe import _
from frappe.utils import now


def execute():
    company = frappe.defaults.get_global_default("company")
    if not company:
        print("No default company set — skipping SM warehouse creation.")
        return

    _create_wip_warehouses(company)
    _add_custom_fields()
    _create_item_group()
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

WAREHOUSES = [
    # (warehouse_name, parent_name, is_group)
    ("Sheet Metal WIP",                "All Warehouses", True),
    ("RM-Coil-Store",                  "Sheet Metal WIP", False),
    ("WIP-Blanking",                   "Sheet Metal WIP", False),
    ("WIP-Piercing",                   "Sheet Metal WIP", False),
    ("WIP-Bending",                    "Sheet Metal WIP", False),
    ("WIP-Forming",                    "Sheet Metal WIP", False),
    ("WIP-Subcontract-Transit",        "Sheet Metal WIP", False),
    ("Sheet Metal Finished Goods",     "Sheet Metal WIP", False),
]


def _create_wip_warehouses(company):
    abbr = frappe.db.get_value("Company", company, "abbr")

    for wh_name, parent_name, is_group in WAREHOUSES:
        full_name = "{0} - {1}".format(wh_name, abbr)
        if frappe.db.exists("Warehouse", full_name):
            continue

        # Resolve parent
        parent_full = "{0} - {1}".format(parent_name, abbr)
        if not frappe.db.exists("Warehouse", parent_full):
            # Try exact name (for "All Warehouses")
            parent_full = parent_name if frappe.db.exists("Warehouse", parent_name) else None

        if not parent_full:
            print("Parent warehouse '{0}' not found — skipping '{1}'.".format(parent_name, wh_name))
            continue

        wh = frappe.new_doc("Warehouse")
        wh.warehouse_name = wh_name
        wh.parent_warehouse = parent_full
        wh.is_group = 1 if is_group else 0
        wh.company = company
        wh.insert(ignore_permissions=True)
        print("Created warehouse: {0}".format(full_name))


# ---------------------------------------------------------------------------
# Custom Fields
# ---------------------------------------------------------------------------

CUSTOM_FIELDS = [
    # (doctype, fieldname, label, fieldtype, options, insert_after, read_only)
    (
        "Work Order",
        "sm_production_lot",
        "SM Production Lot",
        "Link",
        "SM Production Lot",
        "sales_order",
        1,
    ),
    (
        "Subcontracting Order",
        "sm_production_lot",
        "SM Production Lot",
        "Link",
        "SM Production Lot",
        "supplier",
        1,
    ),
    (
        "Stock Entry",
        "sm_production_lot",
        "SM Production Lot",
        "Link",
        "SM Production Lot",
        "work_order",
        1,
    ),
]


def _add_custom_fields():
    for doctype, fieldname, label, fieldtype, options, insert_after, read_only in CUSTOM_FIELDS:
        if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}):
            continue

        cf = frappe.new_doc("Custom Field")
        cf.dt            = doctype
        cf.fieldname     = fieldname
        cf.label         = label
        cf.fieldtype     = fieldtype
        cf.options       = options
        cf.insert_after  = insert_after
        cf.read_only     = read_only
        cf.module        = "Sheet Metal Mfg"
        cf.insert(ignore_permissions=True)
        print("Custom field added: {0}.{1}".format(doctype, fieldname))


# ---------------------------------------------------------------------------
# Item Group
# ---------------------------------------------------------------------------

def _create_item_group():
    groups = [
        ("Sheet Metal WIP",       "All Item Groups"),
        ("Sheet Metal Finished",  "All Item Groups"),
    ]
    for grp_name, parent in groups:
        if frappe.db.exists("Item Group", grp_name):
            continue
        ig = frappe.new_doc("Item Group")
        ig.item_group_name = grp_name
        ig.parent_item_group = parent
        ig.insert(ignore_permissions=True)
        print("Item Group created: {0}".format(grp_name))
