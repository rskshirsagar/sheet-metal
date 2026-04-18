// Work Order Form Extension
// Adds a quick-link back to the SM Production Lot and highlights
// which operation this WO belongs to.

frappe.ui.form.on("Work Order", {
    refresh(frm) {
        if (frm.doc.sm_production_lot) {
            frm.add_custom_button(
                __("SM Production Lot"),
                () => frappe.set_route("Form", "SM Production Lot", frm.doc.sm_production_lot),
                __("Sheet Metal")
            );

            // Show lot operation context
            frappe.call({
                method: "frappe.client.get",
                args: {
                    doctype: "SM Production Lot",
                    name: frm.doc.sm_production_lot,
                },
                callback(r) {
                    if (!r.message) return;
                    let lot = r.message;
                    let op_row = (lot.operations || []).find(o => o.work_order === frm.doc.name);
                    if (!op_row) return;

                    let html = `
                        <div class="alert alert-info" style="margin-bottom:0; padding:8px 12px; font-size:12px;">
                            <b>SM Lot:</b> ${lot.name} &nbsp;|&nbsp;
                            <b>Part:</b> ${lot.part_name} &nbsp;|&nbsp;
                            <b>Operation:</b> ${op_row.operation} (Seq ${op_row.operation_seq}) &nbsp;|&nbsp;
                            <b>Lot Status:</b> ${lot.status}
                        </div>`;

                    frm.fields_dict["sm_production_lot"].$wrapper
                        .find(".sm-lot-context").remove();
                    frm.fields_dict["sm_production_lot"].$wrapper
                        .append(`<div class="sm-lot-context mt-2">${html}</div>`);
                }
            });
        }
    }
});
