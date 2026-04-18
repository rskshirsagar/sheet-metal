# Sheet Metal Mfg — ERPNext V16 Custom App

WIP inventory management for multi-stage sheet metal stamping processes.
Handles in-house and per-lot subcontract decisions with full stock traceability.

---

## Features

| Feature | Detail |
|---|---|
| **SM Production Lot** | Central control document — one per batch, governs all operations |
| **Per-operation execution** | Each op independently set to In-House or Subcontract at lot creation |
| **WIP stock traceability** | Separate Item + Warehouse per stage, real stock ledger at every step |
| **Work Order integration** | Auto-creates WO per in-house op, linked back to lot |
| **Subcontracting integration** | Auto-creates Subcontracting Order, material transfer SE, SC Receipt |
| **Status auto-sync** | Hourly scheduler reconciles op status from linked documents |
| **4 reports** | WIP Stage Summary, Lot Traveller, Operation Pending Qty, Subcontract Tracker |
| **Workspace** | Dedicated sidebar module with shortcuts and KPI counts |

---

## Installation

### Prerequisites
- ERPNext V16 (Frappe V16)
- `bench` CLI access

### Step 1: Get the App
```bash
# From your frappe-bench directory:
bench get-app /path/to/sheet_metal_mfg
# OR from git:
bench get-app https://github.com/yourorg/sheet_metal_mfg
```

### Step 2: Install on Site
```bash
bench --site your-site.local install-app sheet_metal_mfg
bench --site your-site.local migrate
bench build
bench restart
```

The migrate step runs the patch `create_wip_warehouses` which:
- Creates the WIP warehouse tree (`Sheet Metal WIP` group + 7 sub-warehouses)
- Adds `sm_production_lot` custom Link field to Work Order, Subcontracting Order, Stock Entry
- Creates Item Groups: Sheet Metal WIP, Sheet Metal Finished

---

## Master Data Setup (Do Before First Lot)

### 1. Operations
Go to **Manufacturing → Setup → Operation** and create:

| Operation | Description |
|---|---|
| Blanking | Strip cut to blank shape |
| Piercing | Holes punched |
| Bending | Sheet bent to angle |
| Forming | Final form/draw operation |
| Trimming | Edge trimming |
| *(Add your operations)* | |

### 2. Workstations
**Manufacturing → Setup → Workstation** — one per press/machine.

### 3. WIP Items — one per Part per Stage

Naming convention: `{PART-CODE}-{STAGE-ABB}`

Example for part `BRACKET-001`:
```
BRACKET-001-RAW   → Raw strip (stock item, has_batch_no=Yes)
BRACKET-001-BLK   → After Blanking  (item_group=Sheet Metal WIP)
BRACKET-001-PRC   → After Piercing
BRACKET-001-BND   → After Bending
BRACKET-001-FRM   → Finished (item_group=Sheet Metal Finished)
```

**Item settings for each WIP item:**
- `Is Stock Item = Yes`
- `Has Batch No = Yes` (for lot traceability)
- `Default Warehouse` = appropriate WIP-* warehouse

### 4. BOMs — one per WIP Output Item (Bottom-Up)

```
BOM: BRACKET-001-BLK (v1)
  Operations: Blanking → Workstation: Press-01
  Raw Materials: BRACKET-001-RAW  →  X kg

BOM: BRACKET-001-PRC (v1)
  Operations: Piercing → Workstation: Press-02
  Raw Materials: BRACKET-001-BLK  →  1 pc

BOM: BRACKET-001-BND (v1)
  Operations: Bending → Workstation: Press-03
  Raw Materials: BRACKET-001-PRC  →  1 pc

BOM: BRACKET-001-FRM (v1)
  Operations: Forming → Workstation: Press-04
  Raw Materials: BRACKET-001-BND  →  1 pc
```

Mark the **top-level finished item BOM as Default**.

### 5. Routing (Optional)
If you use ERPNext Routing, link operations to the BOM. The app will
auto-populate ops from the routing when you select a part on the lot form.

---

## Creating a Production Lot

1. Go to **Sheet Metal Mfg → SM Production Lot → New**
2. Select **Finished Part** → system auto-populates operations from BOM chain
3. Set **Lot Qty**, **Planned Start Date**
4. Set **Raw Material Item** + batch + warehouse
5. For each operation row:
   - Set **WIP Item In** / **WIP Item Out** (auto-populated if BOM chain is clean)
   - Choose **Execution Type**: In-House or Subcontract
   - If Subcontract: choose **Supplier**
6. **Submit** the lot → Status becomes "In Progress"

---

## Running Operations

### In-House Operation
1. On the lot form, find the operation row with status **Pending**
2. Click **Create Work Order** button on the row
3. System creates a Work Order linked to this lot
4. Operator opens the Work Order, starts the Job Card
5. On Job Card submit → operation auto-marked **Completed**
6. Stock is transferred: Input WIP warehouse → Output WIP warehouse (via WO stock entries)

### Subcontract Operation
1. Click **Create Subcon Order** → Subcontracting Order created
2. Click **Send Material** → Stock Entry created (Input WIP → Subcontract Transit)
3. When material returns: open the Subcontracting Order, create Subcontracting Receipt
4. On SC Receipt submit → operation auto-marked **Completed**
5. Stock posts to the output WIP warehouse automatically

### Manual Override
If you need to mark an op complete without a WO/SC (e.g. rework, prototype):
- Click **Mark Complete** → dialog asks for Qty Actual and Qty Rejected

---

## Reports

### WIP Stage Summary
**Path:** Sheet Metal Mfg → WIP Stage Summary

Live snapshot of all WIP stock across warehouses. Shows:
- Qty in hand per warehouse per item
- Valuation rate and stock value
- Whether next operation is pending (bottleneck flag)
- Lot number linked to each WIP item
- Bar chart: stock value by stage

### Lot Traveller
**Path:** Sheet Metal Mfg → Lot Traveller

Filter by Lot No (or date range) to get a full operation card:
- Every operation: planned vs actual qty, yield %, cycle time
- Status of each op with linked documents
- Print and attach to physical job card

### Operation Pending Qty
**Path:** Sheet Metal Mfg → Operation Pending Qty

All operations in Pending status where previous op is done:
- Grouped by Operation (workstation planning view)
- Days waiting, overdue flag
- Priority-sorted (Urgent first)
- KPI summary: total pending, urgent, overdue, subcontract pending

### Subcontract Status Tracker
**Path:** Sheet Metal Mfg → Subcontract Status Tracker

All open subcontract operations:
- Days material has been at supplier
- Overdue days (past schedule date)
- Material sent / not sent
- Bar chart: avg days by supplier (supplier performance view)

---

## Workflow Diagram

```
SM Production Lot (Draft)
        │  Submit
        ▼
SM Production Lot (In Progress)
        │
        ├─ Op 1: Blanking (In-House)
        │    ├─ [Create Work Order] ──► Work Order ──► Job Card
        │    └─ Job Card Submit ──► Op status: Completed ─────────────┐
        │                                                              │
        ├─ Op 2: Piercing (Subcontract)  ◄─────────────── WIP stock ──┘
        │    ├─ [Create Subcon Order] ──► Subcontracting Order
        │    ├─ [Send Material] ──────► Stock Entry (WIP → Transit)
        │    └─ SC Receipt Submit ───► Op status: Completed ──────────┐
        │                                                              │
        ├─ Op 3: Bending (In-House) ◄──────────────────── WIP stock ──┘
        │    └─ ...
        │
        └─ All ops Completed ──► Lot Status: Completed
```

---

## Architecture Reference

```
sheet_metal_mfg/
├── setup.py
├── requirements.txt
└── sheet_metal_mfg/
    ├── __init__.py
    ├── hooks.py                        ← doc events, scheduler, JS extensions
    ├── modules.txt
    ├── patches.txt
    ├── tasks.py                        ← hourly status sync scheduler
    ├── doctype/
    │   ├── sm_production_lot/
    │   │   ├── sm_production_lot.json  ← DocType definition
    │   │   ├── sm_production_lot.py    ← Controller + doc event callbacks
    │   │   └── sm_production_lot.js   ← Form JS: buttons, BOM auto-load, progress
    │   └── sm_lot_operation/
    │       └── sm_lot_operation.json   ← Child table definition
    ├── report/
    │   ├── wip_stage_summary/          ← Live WIP stock by stage + chart
    │   ├── lot_traveller/              ← Per-lot shop floor card
    │   ├── operation_pending_qty/      ← Bottleneck ops + KPI summary
    │   └── subcontract_status_tracker/ ← Vendor tracking + aging chart
    ├── patches/
    │   └── v1_0/
    │       └── create_wip_warehouses.py ← Auto-creates warehouses + custom fields
    ├── public/js/
    │   ├── work_order_extend.js        ← Adds SM Lot context to WO form
    │   └── subcontracting_order_extend.js
    └── workspace/
        └── sheet_metal_mfg.json        ← Sidebar module with shortcuts
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| "No operations found in BOM" | Ensure BOM is Active + Default for the finished item |
| Work Order not linked to lot | Check `sm_production_lot` custom field was created (run migrate) |
| WIP stock not showing in report | Verify WIP item's default warehouse name contains "WIP" |
| SC Receipt not auto-completing op | Ensure SC Order has `sm_production_lot` set (created via lot form) |
| Status not updating | Run `bench execute sheet_metal_mfg.tasks.sync_lot_operation_status` manually |

---

## License
MIT
