// Subcontracting Order Form Extension
// Links back to SM Production Lot and shows lot context.

frappe.ui.form.on("Subcontracting Order", {
    refresh(frm) {
        if (frm.doc.sm_production_lot) {
            frm.add_custom_button(
                __("SM Production Lot"),
                () => frappe.set_route("Form", "SM Production Lot", frm.doc.sm_production_lot),
                __("Sheet Metal")
            );

            // Show lot context banner
            frappe.db.get_doc("SM Production Lot", frm.doc.sm_production_lot)
                .then(lot => {
                    let op_row = (lot.operations || []).find(
                        o => o.subcontracting_order === frm.doc.name
                    );
                    if (!op_row) return;

                    let overdue = "";
                    if (frm.doc.schedule_date && frm.doc.schedule_date < frappe.datetime.get_today()) {
                        overdue = `&nbsp;<span class="badge badge-danger">${__("OVERDUE")}</span>`;
                    }

                    let html = `
                        <div class="alert alert-warning" style="margin-bottom:0; padding:8px 12px; font-size:12px;">
                            <b>SM Lot:</b> ${lot.name} &nbsp;|&nbsp;
                            <b>Part:</b> ${lot.part_name} &nbsp;|&nbsp;
                            <b>Operation:</b> ${op_row.operation} (Seq ${op_row.operation_seq}) &nbsp;|&nbsp;
                            <b>Lot Priority:</b> ${lot.priority} ${overdue}
                        </div>`;

                    frm.fields_dict["sm_production_lot"].$wrapper
                        .find(".sm-lot-context").remove();
                    frm.fields_dict["sm_production_lot"].$wrapper
                        .append(`<div class="sm-lot-context mt-2">${html}</div>`);
                });

            // Quick button to create Subcontracting Receipt
            if (frm.doc.docstatus === 1 && frm.doc.status !== "Completed") {
                frm.add_custom_button(
                    __("Create SC Receipt & Mark Complete"),
                    () => _sm_create_sc_receipt(frm),
                    __("Sheet Metal")
                );
            }
        }
    }
});

function _sm_create_sc_receipt(frm) {
    frappe.model.open_mapped_doc({
        method: "erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order.make_subcontracting_receipt",
        frm: frm,
    });
}
