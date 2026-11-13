CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id VARCHAR(20) PRIMARY KEY,
    supplier_name VARCHAR(200) NOT NULL UNIQUE,
    city VARCHAR(100) NOT NULL,
    specialization VARCHAR(200) NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id VARCHAR(20) PRIMARY KEY,
    warehouse_name VARCHAR(200) NOT NULL UNIQUE,
    city VARCHAR(100) NOT NULL,
    province VARCHAR(100) NOT NULL,
    capacity_units INTEGER NOT NULL CHECK (capacity_units > 0)
);

CREATE TABLE IF NOT EXISTS products (
    product_id VARCHAR(20) PRIMARY KEY,
    sku VARCHAR(50) NOT NULL UNIQUE,
    product_name VARCHAR(200) NOT NULL,
    product_type VARCHAR(100) NOT NULL,
    category VARCHAR(100) NOT NULL,
    unit_of_measure VARCHAR(50) NOT NULL,
    unit_cost_lkr NUMERIC(14, 2) NOT NULL CHECK (unit_cost_lkr >= 0),
    default_reorder_level INTEGER NOT NULL CHECK (default_reorder_level >= 0),
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days >= 0),
    supplier_id VARCHAR(20) NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS inventory (
    inventory_id VARCHAR(20) PRIMARY KEY,
    product_id VARCHAR(20) NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(20) NOT NULL REFERENCES warehouses(warehouse_id) ON DELETE RESTRICT,
    opening_quantity INTEGER NOT NULL CHECK (opening_quantity >= 0),
    quantity_on_hand INTEGER NOT NULL CHECK (quantity_on_hand >= 0),
    reorder_level INTEGER NOT NULL CHECK (reorder_level >= 0),
    maximum_stock_level INTEGER NOT NULL CHECK (maximum_stock_level >= reorder_level),
    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
    reserved_quantity INTEGER NOT NULL CHECK (reserved_quantity >= 0),
    last_updated DATE NOT NULL DEFAULT CURRENT_DATE,
    CONSTRAINT uq_inventory_product_warehouse UNIQUE (product_id, warehouse_id),
    CONSTRAINT ck_inventory_quantity_split CHECK (
        quantity_on_hand = available_quantity + reserved_quantity
    )
);

CREATE TABLE IF NOT EXISTS stock_movements (
    movement_id VARCHAR(40) PRIMARY KEY,
    movement_date DATE NOT NULL,
    product_id VARCHAR(20) NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(20) NOT NULL REFERENCES warehouses(warehouse_id) ON DELETE RESTRICT,
    movement_type VARCHAR(20) NOT NULL CHECK (
        movement_type IN (
            'RECEIPT', 'ISSUE', 'TRANSFER_IN', 'TRANSFER_OUT',
            'ADJUSTMENT_IN', 'ADJUSTMENT_OUT'
        )
    ),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    reference_no VARCHAR(100) NOT NULL,
    unit_cost_lkr NUMERIC(14, 2) NOT NULL CHECK (unit_cost_lkr >= 0),
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_products_category ON products(category);
CREATE INDEX IF NOT EXISTS ix_products_supplier ON products(supplier_id);
CREATE INDEX IF NOT EXISTS ix_inventory_warehouse ON inventory(warehouse_id);
CREATE INDEX IF NOT EXISTS ix_inventory_product ON inventory(product_id);
CREATE INDEX IF NOT EXISTS ix_stock_movements_date ON stock_movements(movement_date);
CREATE INDEX IF NOT EXISTS ix_stock_movements_product_date
    ON stock_movements(product_id, movement_date);
CREATE INDEX IF NOT EXISTS ix_stock_movements_warehouse_date
    ON stock_movements(warehouse_id, movement_date);
CREATE INDEX IF NOT EXISTS ix_stock_movements_type_date
    ON stock_movements(movement_type, movement_date);
CREATE INDEX IF NOT EXISTS ix_stock_movements_reference
    ON stock_movements(reference_no);
