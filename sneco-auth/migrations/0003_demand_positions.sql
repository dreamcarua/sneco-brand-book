-- v2.70: ms_demand_positions — товарні позиції з ms_demands
-- snEco хоче бачити ТОП-10 продуктів per клієнт у Customer 360.
-- Зараз parse_demands створює multiple rows per demand (одну на position),
-- але всі мають той самий id → у D1 зберігається лише ОДНА позиція через INSERT OR REPLACE.
-- Окрема таблиця dimensional модель.

CREATE TABLE IF NOT EXISTS ms_demand_positions (
    demand_id       TEXT NOT NULL,
    position_idx    INTEGER NOT NULL,
    product_name    TEXT,
    product_id      TEXT,
    quantity        REAL,
    price_kop       INTEGER,
    sum_kop         INTEGER,
    discount_pct    REAL,
    agent_id        TEXT,
    agent           TEXT,
    ms_moment       TEXT,
    raw_json        TEXT,
    ingested_at     INTEGER,
    PRIMARY KEY (demand_id, position_idx)
);

-- Indexes для типових queries Customer 360 + Finance Dashboard
CREATE INDEX IF NOT EXISTS idx_demand_positions_agent_id ON ms_demand_positions(agent_id);
CREATE INDEX IF NOT EXISTS idx_demand_positions_product_id ON ms_demand_positions(product_id);
CREATE INDEX IF NOT EXISTS idx_demand_positions_moment ON ms_demand_positions(ms_moment);
CREATE INDEX IF NOT EXISTS idx_demand_positions_agent_product ON ms_demand_positions(agent_id, product_id);
