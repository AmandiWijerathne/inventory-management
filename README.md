# SCM Inventory Management Dashboard

A database-driven inventory management application built with Python, Streamlit,
PostgreSQL, SQLAlchemy, Pandas, and Plotly. The supplied synthetic CSVs are the
only initial dataset; the application does not generate replacement/sample data.
Currency values are reported in LKR.

## Features

- Executive KPIs and interactive value, warehouse, movement, status, and top-product charts.
- Product and warehouse create/update/delete workflows. Deletion is refused when
  inventory or movement history refers to the selected record.
- Searchable, sortable inventory with live stock status and valuation.
- Receipts, issues, adjustments, and atomic transfers with transaction-safe stock
  availability checks and paired transfer movement rows.
- Warehouse-specific low-stock, out-of-stock, overstock, and replenishment alerts.
- Filterable operational reports with CSV and Excel downloads.
- Database credentials are read from `DATABASE_URL`; the repository contains no
  real credentials.

## Project layout

```text
app.py
pages/                 Streamlit pages
backend/               SQLAlchemy database and domain/report services
database/              PostgreSQL schema, initializer, CSV importer
data/                  Supplied CSV files (preserved)
frontend/              Shared Streamlit components and dashboard
tests/                 Offline dataset integrity and export tests
.env.example           PostgreSQL URL template
requirements.txt
```

## Windows PowerShell setup

1. Install PostgreSQL and make sure its service is running. Create or use a
   PostgreSQL role permitted to create databases (or create `scm_inventory_db`
   yourself and use `--no-create-database` in step 5).
2. In PowerShell, enter the project folder and create the virtual environment:

   ```powershell
   Set-Location "$HOME\Desktop\scm_inventory_dashboard"
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If script activation is restricted by your local policy, invoke the
   environment's executables explicitly, for example
   `.\.venv\Scripts\python.exe`.
3. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
4. Create a local environment file and edit the password/host for your own
   PostgreSQL instance:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   Set `DATABASE_URL` using the SQLAlchemy psycopg URL form:
   `postgresql+psycopg://USER:PASSWORD@HOST:5432/scm_inventory_db`.
   URL-encode special characters in the username or password. Do not commit
   `.env`.
5. Create the database only if missing and install the schema. This operation
   uses `CREATE TABLE/INDEX IF NOT EXISTS` and does not drop existing tables or
   records:

   ```powershell
   python -m database.init_db
   ```

   To apply the schema to a database you created yourself without attempting
   database creation:

   ```powershell
   python -m database.init_db --no-create-database
   ```
6. Validate and import the provided CSVs:

   ```powershell
   python -m database.import_data --validate-only
   python -m database.import_data
   ```

   The importer checks key relationships, transfer pairs, quantity splits, and
   opening-stock-plus-movement reconciliation before connecting. It inserts rows
   in foreign-key order and uses `ON CONFLICT DO NOTHING`: existing rows are
   preserved and never updated. Run the importer again to safely skip conflicts.
7. Launch the application:

   ```powershell
   streamlit run app.py
   ```

## Database and inventory rules

- `inventory` has one record per product/warehouse pair. On-hand stock is split
  into available plus reserved quantity; outgoing transactions may consume only
  available stock.
- A new product/warehouse stock row is initialized at zero for incoming stock.
  Its reorder threshold is the product default and the initial maximum is three
  times `max(1, reorder level)`. Existing stock thresholds are not overwritten.
- A transfer is one database transaction: lock rows in warehouse-ID order,
  validate source availability, update both balances, and insert a matched
  `TRANSFER_OUT`/`TRANSFER_IN` pair with one reference. Any failure rolls back
  both stock and movement changes.
- Stock status is derived at query time in this order: zero is **Out of Stock**;
  quantity above maximum is **Overstock**; positive quantity at/below reorder is
  **Low Stock**; otherwise it is **In Stock**.
- Recommended replenishment is `max(0, maximum_stock_level - quantity_on_hand)`
  for low/out-of-stock locations.
- Warehouse capacity utilization is an explicitly indicative unit-count ratio:
  total on-hand units divided by `capacity_units`. It is not volume, pallet, or
  weight utilization and may exceed 100%.
- Monthly dashboard receipts/issues chart only `RECEIPT` and `ISSUE`; transfer
  and adjustment rows remain visible in movement history and reports.
- Inventory valuation reports describe the current stock snapshot and use
  `last_updated` for the date filter; movement reports filter by movement date.

## Testing

Run the offline checks from the project root:

```powershell
python -m unittest discover -s tests -v
python -m database.import_data --validate-only
```

The tests verify source row counts and relationships, the exact quantity
reconciliation for all 295 inventory records, paired transfers, and CSV/Excel
export generation. PostgreSQL-dependent CRUD and transaction behavior must be
tested against a configured local PostgreSQL database after setup; no database
is created or modified by the offline tests.

## Dataset notes

The included dataset is synthetic and for demonstration only. It describes
59 products, 5 warehouses, 12 suppliers, 295 inventory records, and 1,713 stock
movements covering January 1 through November 11, 2026. Validate costs,
reorder levels, supplier details, and warehouse capacity before using this
application with real operational data.
