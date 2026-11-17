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

CREATE TABLE IF NOT EXISTS purchase_orders (
    purchase_order_id VARCHAR(32) PRIMARY KEY,
    purchase_order_no VARCHAR(80) NOT NULL UNIQUE,
    supplier_id VARCHAR(20) NOT NULL REFERENCES suppliers(supplier_id) ON DELETE RESTRICT,
    order_date DATE NOT NULL,
    expected_delivery_date DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'Draft' CHECK (
        status IN (
            'Draft', 'Pending Approval', 'Approved', 'Ordered',
            'Partially Received', 'Received', 'Cancelled'
        )
    ),
    notes TEXT NOT NULL DEFAULT '',
    total_amount_lkr NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (total_amount_lkr >= 0),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    purchase_order_item_id VARCHAR(32) PRIMARY KEY,
    purchase_order_id VARCHAR(32) NOT NULL REFERENCES purchase_orders(purchase_order_id) ON DELETE CASCADE,
    product_id VARCHAR(20) NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_lkr NUMERIC(14, 2) NOT NULL CHECK (unit_price_lkr >= 0),
    received_quantity INTEGER NOT NULL DEFAULT 0 CHECK (received_quantity >= 0),
    line_total_lkr NUMERIC(14, 2) NOT NULL CHECK (line_total_lkr >= 0),
    UNIQUE (purchase_order_id, product_id)
);

CREATE TABLE IF NOT EXISTS goods_received (
    goods_received_id VARCHAR(32) PRIMARY KEY,
    purchase_order_id VARCHAR(32) NOT NULL REFERENCES purchase_orders(purchase_order_id) ON DELETE RESTRICT,
    receipt_no VARCHAR(80) NOT NULL UNIQUE,
    warehouse_id VARCHAR(20) NOT NULL REFERENCES warehouses(warehouse_id) ON DELETE RESTRICT,
    received_date DATE NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goods_received_items (
    goods_received_item_id VARCHAR(32) PRIMARY KEY,
    goods_received_id VARCHAR(32) NOT NULL REFERENCES goods_received(goods_received_id) ON DELETE CASCADE,
    purchase_order_item_id VARCHAR(32) NOT NULL REFERENCES purchase_order_items(purchase_order_item_id) ON DELETE RESTRICT,
    product_id VARCHAR(20) NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    quantity_received INTEGER NOT NULL CHECK (quantity_received > 0),
    unit_cost_lkr NUMERIC(14, 2) NOT NULL CHECK (unit_cost_lkr >= 0),
    line_total_lkr NUMERIC(14, 2) NOT NULL CHECK (line_total_lkr >= 0)
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
CREATE INDEX IF NOT EXISTS ix_purchase_orders_supplier ON purchase_orders(supplier_id);
CREATE INDEX IF NOT EXISTS ix_purchase_orders_status ON purchase_orders(status);
CREATE INDEX IF NOT EXISTS ix_purchase_order_items_product ON purchase_order_items(product_id);
CREATE INDEX IF NOT EXISTS ix_goods_received_purchase_order ON goods_received(purchase_order_id);
CREATE INDEX IF NOT EXISTS ix_goods_received_warehouse ON goods_received(warehouse_id);
