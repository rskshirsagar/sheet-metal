// SM Stage Production Entry — Client Controller

frappe.ui.form.on("SM Stage Production Entry", {

    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            frm.page.set_indicator(__("Submitted"), "green");
            if (frm.doc.stock_entry) {
                frm.add_custom_button(__("View Stock Entry"), () => {
                    frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry);
                });
            }
        }
        if (frm.doc.production_lot) {
            frm.add_custom_button(__("View Production Lot"), () => {
                frappe.set_route("Form", "SM Production Lot", frm.doc.production_lot);
            });
        }
    },

    qty_produced(frm) {
        _update_after_preview(frm);
    },

    qty_rejected(frm) {
        _update_after_preview(frm);
    },

    qty_to_produce(frm) {
        // Default qty_produced = qty_to_produce when user sets session qty
        if (frm.doc.qty_to_produce && !frm.doc.qty_produced) {
            frappe.model.set_value(frm.doctype, frm.docname, "qty_produced", frm.doc.qty_to_produce);
        }
    },
});

function _update_after_preview(frm) {
    const planned    = frm.doc.qty_available_to_produce + frm.doc.qty_cumulative_before;
    const cumBefore  = frm.doc.qty_cumulative_before || 0;
    const produced   = flt(frm.doc.qty_produced);
    frm.set_value("qty_cumulative_after", cumBefore + produced);
    frm.set_value("qty_open_after", Math.max(planned - (cumBefore + produced), 0));
}
