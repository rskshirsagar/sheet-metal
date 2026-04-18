// SM Production Lot — Client Controller  v2 (Partial Production)
// ================================================================

frappe.ui.form.on("SM Production Lot", {

    refresh(frm) {
        _sm_setup_indicators(frm);
        if (!frm.is_new()) {
            _sm_add_header_buttons(frm);
        }
        _sm_render_op_buttons(frm);
        _sm_render_progress_bar(frm);
    },

    part(frm) {
        if (!frm.doc.part) return;
        frappe.call({
            method: "sheet_metal_mfg.doctype.sm_production_lot.sm_production_lot.get_operations_for_part",
            args: { part: frm.doc.part },
            callback(r) {
                if (!r.message || !r.message.length) {
                    frappe.msgprint(__("No operations found in BOM. Add them manually."));
                    return;
                }
                frm.clear_table("operations");
                r.message.forEach(op => {
                    let row = frm.add_child("operations");
                    row.operation_seq  = op.operation_seq || op.idx;
                    row.operation      = op.operation;
                    row.workstation    = op.workstation;
                    row.wip_item_out   = op.wip_item_out || "";
                    row.execution_type = "In-House";
                    row.qty_planned    = frm.doc.qty || 0;
                    row.qty_open       = frm.doc.qty || 0;
                    row.status         = "Pending";
                });
                frm.refresh_field("operations");
                frappe.show_alert({ message: __("{0} operations loaded.", [r.message.length]), indicator: "green" });
            }
        });
    },

    qty(frm) {
        (frm.doc.operations || []).forEach(row => {
            if (!row.qty_produced) {
                frappe.model.set_value(row.doctype, row.name, "qty_planned", frm.doc.qty);
                frappe.model.set_value(row.doctype, row.name, "qty_open", frm.doc.qty);
            }
        });
    },
});

frappe.ui.form.on("SM Lot Operation", {
    execution_type(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.execution_type === "In-House")
            frappe.model.set_value(cdt, cdn, "supplier", "");
        frm.refresh_field("operations");
    },
    wip_item_out(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.wip_item_out) return;
        frappe.call({
            method: "frappe.client.get_value",
            args: { doctype: "BOM", filters: { item: row.wip_item_out, is_active: 1, is_default: 1 }, fieldname: "name" },
            callback(r) {
                if (r.message && r.message.name)
                    frappe.model.set_value(cdt, cdn, "bom_no", r.message.name);
            }
        });
    }
});

// ── Header buttons ────────────────────────────────────────────────────────────
function _sm_add_header_buttons(frm) {
    if (frm.doc.docstatus !== 1) return;
    frm.add_custom_button(__("Lot Traveller"), () => {
        frappe.route_options = { lot_no: frm.doc.name };
        frappe.set_route("query-report", "Lot Traveller");
    }, __("Reports"));
    frm.add_custom_button(__("WIP Stage Summary"), () => {
        frappe.set_route("query-report", "WIP Stage Summary");
    }, __("Reports"));
    frm.add_custom_button(__("Stage Production Summary"), () => {
        frappe.route_options = { production_lot: frm.doc.name };
        frappe.set_route("query-report", "Stage Production Summary");
    }, __("Reports"));
}

// ── Status indicator ──────────────────────────────────────────────────────────
function _sm_setup_indicators(frm) {
    const map = {
        "Draft": "grey", "In Progress": "blue",
        "Partially Completed": "orange", "Completed": "green", "Cancelled": "red"
    };
    frm.page.set_indicator(frm.doc.status, map[frm.doc.status] || "grey");
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function _sm_render_progress_bar(frm) {
    if (frm.is_new() || !frm.doc.operations?.length) return;
    let ops       = frm.doc.operations;
    let completed = ops.filter(o => o.status === "Completed").length;
    let partial   = ops.filter(o => o.status === "Partially Produced").length;
    let total     = ops.length;
    let pct       = Math.round((completed / total) * 100);
    let partPct   = Math.round((partial / total) * 100);
    let color     = pct === 100 ? "success" : (pct > 0 ? "warning" : "secondary");

    let html = `
        <div class="row mt-2 mb-2">
          <div class="col-sm-12">
            <small class="text-muted">${__("Stages")}: ${completed} completed / ${partial} partial / ${total} total</small>
            <div class="progress" style="height:10px;margin-top:4px;">
              <div class="progress-bar bg-${color}" style="width:${pct}%" title="${pct}% complete"></div>
              <div class="progress-bar bg-warning" style="width:${partPct}%" title="${partPct}% partial"></div>
            </div>
          </div>
        </div>`;

    let $sec = frm.fields_dict["total_operations"].$wrapper;
    $sec.find(".sm-progress-bar").remove();
    $sec.prepend(`<div class="sm-progress-bar">${html}</div>`);
}

// ── Per-row action buttons ────────────────────────────────────────────────────
function _sm_render_op_buttons(frm) {
    if (frm.doc.docstatus !== 1) return;
    setTimeout(() => {
        frm.fields_dict.operations.grid.grid_rows.forEach(grid_row => {
            let row = grid_row.doc;
            if (!row) return;

            let $cell = $(grid_row.row).find('[data-fieldname="status"]');
            $cell.find(".sm-btn-wrap").remove();

            let btns = _sm_get_row_buttons(row);
            if (!btns.length) return;

            let $wrap = $('<div class="sm-btn-wrap" style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;"></div>');
            btns.forEach(({ label, cls, action }) => {
                let $b = $(`<button class="btn btn-xs ${cls}">${label}</button>`);
                $b.on("click", e => { e.stopPropagation(); action(frm, row); });
                $wrap.append($b);
            });
            $cell.append($wrap);
        });
    }, 400);
}

function _sm_get_row_buttons(row) {
    let btns = [];
    if (row.execution_type === "In-House") {
        if (row.status === "Pending") {
            btns.push({ label: __("Create WO"), cls: "btn-primary", action: _sm_create_wo });
        }
        if (["In Progress", "Partially Produced"].includes(row.status) && row.work_order) {
            btns.push({ label: __("Book Production"), cls: "btn-success", action: _sm_book_production });
            btns.push({ label: __("Close Stage"), cls: "btn-warning", action: _sm_close_stage });
        }
        if (["In Progress", "Partially Produced", "Completed"].includes(row.status) && row.work_order) {
            btns.push({ label: __("Sessions"), cls: "btn-default", action: _sm_show_sessions });
        }
    } else {
        // Subcontract
        if (row.status === "Pending") {
            btns.push({ label: __("Create SC Order"), cls: "btn-primary", action: _sm_create_sc });
        }
        if (row.status === "In Progress" && !row.stock_entry_transfer) {
            btns.push({ label: __("Send Material"), cls: "btn-warning", action: _sm_send_material });
        }
        if (["In Progress", "Subcontract Sent"].includes(row.status)) {
            btns.push({ label: __("Mark Complete"), cls: "btn-success", action: _sm_mark_complete });
        }
    }
    return btns;
}

// ── Create Work Order ─────────────────────────────────────────────────────────
function _sm_create_wo(frm, row) {
    frappe.confirm(
        __("Create Work Order for <b>{0}</b>?", [row.operation]),
        () => frappe.call({
            method: "create_work_order", doc: frm.doc,
            args: { operation_row_name: row.name },
            freeze: true, freeze_message: __("Creating Work Order..."),
            callback(r) { if (!r.exc) { frm.reload_doc(); } }
        })
    );
}

// ── Book Production Dialog ────────────────────────────────────────────────────
function _sm_book_production(frm, row) {
    let qty_open = flt(row.qty_planned) - flt(row.qty_produced);
    let d = new frappe.ui.Dialog({
        title: __("Book Production — {0}", [row.operation]),
        fields: [
            {
                fieldtype: "HTML", fieldname: "summary_html",
                options: `<div class="alert alert-info" style="font-size:12px;margin-bottom:8px;">
                    <b>${__("Stage")}:</b> ${row.operation} &nbsp;|&nbsp;
                    <b>${__("Planned")}:</b> ${row.qty_planned} &nbsp;|&nbsp;
                    <b>${__("Produced so far")}:</b> ${flt(row.qty_produced)} &nbsp;|&nbsp;
                    <b class="text-danger">${__("Open")}:</b> ${qty_open}
                  </div>`
            },
            { label: __("Qty to Produce (This Session)"), fieldname: "qty_to_produce",
              fieldtype: "Float", reqd: 1, default: qty_open,
              description: __("Max: {0}", [qty_open]) },
            { fieldtype: "Column Break" },
            { label: __("Qty Produced (Good)"), fieldname: "qty_produced",
              fieldtype: "Float", reqd: 1, default: qty_open },
            { label: __("Qty Rejected"), fieldname: "qty_rejected",
              fieldtype: "Float", default: 0 },
            { fieldtype: "Section Break" },
            { label: __("Remarks"), fieldname: "remarks", fieldtype: "Small Text" },
        ],
        primary_action_label: __("Submit Production Entry"),
        primary_action(vals) {
            frappe.call({
                method: "book_production", doc: frm.doc,
                args: {
                    operation_row_name: row.name,
                    qty_to_produce: vals.qty_to_produce,
                    qty_produced:   vals.qty_produced,
                    qty_rejected:   vals.qty_rejected || 0,
                },
                freeze: true, freeze_message: __("Creating Production Entry..."),
                callback(r) {
                    if (!r.exc) { d.hide(); frm.reload_doc(); }
                }
            });
        }
    });
    d.show();
}

// ── Close Stage Dialog ────────────────────────────────────────────────────────
function _sm_close_stage(frm, row) {
    let qty_produced    = flt(row.qty_produced);
    let qty_not_produced = flt(row.qty_planned) - qty_produced;

    let d = new frappe.ui.Dialog({
        title: __("Close Stage — {0}", [row.operation]),
        fields: [
            {
                fieldtype: "HTML", fieldname: "info_html",
                options: `<div class="alert alert-warning" style="font-size:12px;margin-bottom:12px;">
                    <b>${__("Planned")}:</b> ${row.qty_planned} pcs &nbsp;|&nbsp;
                    <b>${__("Produced")}:</b> ${qty_produced} pcs &nbsp;|&nbsp;
                    <b>${__("Not Produced")}:</b> <span class="text-danger">${qty_not_produced} pcs</span>
                    <br><br>
                    <b>⚠ ${__("The {0} unproduced pieces will remain open in the WIP warehouse — no process loss will be booked.", [qty_not_produced])}</b>
                  </div>`
            },
            { label: __("Qty to Forward to Next Stage"), fieldname: "qty_to_forward",
              fieldtype: "Float", reqd: 1, default: qty_produced,
              description: __("Cannot exceed {0} (qty produced)", [qty_produced]) },
            { fieldtype: "Section Break" },
            {
                fieldtype: "HTML", fieldname: "note_html",
                options: `<div class="text-muted" style="font-size:11px;">
                    The Work Order will be <b>Stopped</b> (not closed) — no process loss or scrap entry will be created.
                    The next stage Work Order will be created for the forwarded quantity only.
                  </div>`
            },
        ],
        primary_action_label: __("Close Stage & Forward"),
        primary_action(vals) {
            if (flt(vals.qty_to_forward) > qty_produced) {
                frappe.msgprint(__("Cannot forward more than produced quantity."));
                return;
            }
            frappe.confirm(
                __("Close stage <b>{0}</b>? Work Order will be Stopped. {1} pcs forwarded, {2} pcs remain in WIP.",
                    [row.operation, vals.qty_to_forward, qty_not_produced]),
                () => frappe.call({
                    method: "close_stage", doc: frm.doc,
                    args: { operation_row_name: row.name, qty_to_forward: vals.qty_to_forward },
                    freeze: true, freeze_message: __("Closing stage..."),
                    callback(r) { if (!r.exc) { d.hide(); frm.reload_doc(); } }
                })
            );
        }
    });
    d.show();
}

// ── Sessions History Popup ────────────────────────────────────────────────────
function _sm_show_sessions(frm, row) {
    frappe.call({
        method: "get_production_sessions", doc: frm.doc,
        args: { operation_row_name: row.name },
        callback(r) {
            if (!r.message || !r.message.length) {
                frappe.msgprint(__("No production sessions recorded yet for this stage."));
                return;
            }
            let rows_html = r.message.map((s, i) =>
                `<tr style="background:${i%2===0?'#fff':'#f8f9fa'}">
                  <td>${s.posting_date}</td>
                  <td>${s.qty_to_produce}</td>
                  <td><b>${s.qty_produced}</b></td>
                  <td>${s.qty_rejected || 0}</td>
                  <td>${s.qty_cumulative_after}</td>
                  <td class="text-danger">${s.qty_open_after}</td>
                  <td><span class="badge badge-${s.status==='Submitted'?'success':'secondary'}">${s.status}</span></td>
                  <td><a href="/app/stock-entry/${s.stock_entry}" target="_blank">${s.stock_entry||''}</a></td>
                </tr>`
            ).join("");

            let total_produced = r.message.reduce((s, e) => s + flt(e.qty_produced), 0);
            let total_rejected = r.message.reduce((s, e) => s + flt(e.qty_rejected), 0);

            let html = `
              <div style="font-size:12px;">
                <div class="alert alert-info" style="padding:6px 12px;margin-bottom:8px;">
                  <b>${__("Stage")}:</b> ${row.operation} &nbsp;|&nbsp;
                  <b>${__("Planned")}:</b> ${row.qty_planned} &nbsp;|&nbsp;
                  <b>${__("Total Produced")}:</b> ${total_produced} &nbsp;|&nbsp;
                  <b>${__("Total Rejected")}:</b> ${total_rejected} &nbsp;|&nbsp;
                  <b class="text-danger">${__("Open")}:</b> ${flt(row.qty_planned) - total_produced}
                </div>
                <table class="table table-bordered" style="font-size:11px;">
                  <thead style="background:#1F4E79;color:#fff;">
                    <tr>
                      <th>${__("Date")}</th>
                      <th>${__("Session Qty")}</th>
                      <th>${__("Produced")}</th>
                      <th>${__("Rejected")}</th>
                      <th>${__("Cumulative")}</th>
                      <th>${__("Open After")}</th>
                      <th>${__("Status")}</th>
                      <th>${__("Stock Entry")}</th>
                    </tr>
                  </thead>
                  <tbody>${rows_html}</tbody>
                </table>
              </div>`;

            let d = new frappe.ui.Dialog({
                title: __("Production Sessions — {0}", [row.operation]),
                fields: [{ fieldtype: "HTML", fieldname: "table_html", options: html }],
                size: "extra-large",
            });
            d.show();
        }
    });
}

// ── Subcontract actions ───────────────────────────────────────────────────────
function _sm_create_sc(frm, row) {
    frappe.confirm(
        __("Create Subcontracting Order for <b>{0}</b> with supplier <b>{1}</b>?",
            [row.operation, row.supplier]),
        () => frappe.call({
            method: "create_subcontracting_order", doc: frm.doc,
            args: { operation_row_name: row.name },
            freeze: true, freeze_message: __("Creating SC Order..."),
            callback(r) { if (!r.exc) frm.reload_doc(); }
        })
    );
}

function _sm_send_material(frm, row) {
    frappe.confirm(
        __("Create material transfer to subcontractor for <b>{0}</b>?", [row.operation]),
        () => frappe.call({
            method: "create_material_transfer_to_subcontractor", doc: frm.doc,
            args: { operation_row_name: row.name },
            freeze: true, callback(r) { if (!r.exc) frm.reload_doc(); }
        })
    );
}

function _sm_mark_complete(frm, row) {
    let d = new frappe.ui.Dialog({
        title: __("Mark Complete — {0}", [row.operation]),
        fields: [
            { label: __("Qty Received (Good)"), fieldname: "qty_actual", fieldtype: "Float",
              default: row.qty_planned, reqd: 1 },
            { label: __("Qty Rejected"),        fieldname: "qty_rejected", fieldtype: "Float", default: 0 },
        ],
        primary_action_label: __("Mark Complete"),
        primary_action(vals) {
            frappe.db.set_value("SM Lot Operation", row.name, {
                status:       "Completed",
                qty_produced: vals.qty_actual,
                qty_forwarded: vals.qty_actual,
                qty_rejected: vals.qty_rejected,
                actual_end:   frappe.datetime.now_datetime(),
            }).then(() => { d.hide(); frm.reload_doc(); });
        }
    });
    d.show();
}
