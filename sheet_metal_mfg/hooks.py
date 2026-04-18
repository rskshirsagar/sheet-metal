app_name = "sheet_metal_mfg"
app_title = "Sheet Metal Mfg"
app_publisher = "Your Company"
app_description = "Sheet Metal WIP & Production Lot Management for ERPNext V16"
app_icon = "octicon octicon-tools"
app_color = "#e74c3c"
app_email = "info@yourcompany.com"
app_license = "MIT"

fixtures = [
    {"dt": "Custom Field",    "filters": [["module", "=", "Sheet Metal Mfg"]]},
    {"dt": "Property Setter", "filters": [["module", "=", "Sheet Metal Mfg"]]},
]

doctype_js = {
    "Work Order":             "public/js/work_order_extend.js",
    "Subcontracting Order":   "public/js/subcontracting_order_extend.js",
}

scheduler_events = {
    "hourly": [
        "sheet_metal_mfg.tasks.sync_lot_operation_status",
    ],
}

has_permission = {
    "SM Production Lot": "sheet_metal_mfg.doctype.sm_production_lot.sm_production_lot.has_permission",
}

doc_events = {
    # NOTE: on_job_card_submit removed in v2 — production is now booked via
    # SM Stage Production Entry, not via Job Card submit.
    # Job Cards are still used for time tracking but do NOT auto-complete ops.
    "Subcontracting Receipt": {
        "on_submit": "sheet_metal_mfg.doctype.sm_production_lot.sm_production_lot.on_subcontracting_receipt_submit",
    },
    "Stock Entry": {
        "on_submit": "sheet_metal_mfg.doctype.sm_production_lot.sm_production_lot.on_stock_entry_submit",
    },
}
