-- snEco · Procurement Dashboard · D1 schema
-- Apply: npx wrangler d1 execute sneco-bible --file=dashboard/procurement/schema.sql --remote
-- Table prefix: proc_*

-- ─── Processing-операції (виробничі цикли) ──────────────────────────────────
-- Кожна операція має заголовок (це таблиця) + matrices через ms_processing_materials
-- та ms_processing_products (нижче).

CREATE TABLE IF NOT EXISTS ms_processings (
  id                   TEXT PRIMARY KEY,
  ms_moment            TEXT NOT NULL,         -- 'YYYY-MM-DD HH:MM:SS.000'
  name                 TEXT,                  -- номер документу
  organization_id      TEXT,
  organization         TEXT,                  -- денормалізовано для зручності
  processing_plan_id   TEXT,
  processing_plan_name TEXT,
  quantity             REAL DEFAULT 0,        -- скільки разів виконано план
  processing_sum_kop   INTEGER DEFAULT 0,     -- собівартість, копійки
  applicable           INTEGER DEFAULT 1,     -- 0 = скасовано
  raw_json             TEXT,
  updated_at           TEXT                   -- момент останнього оновлення у МойСклад
);
CREATE INDEX IF NOT EXISTS idx_ms_proc_moment ON ms_processings(ms_moment);
CREATE INDEX IF NOT EXISTS idx_ms_proc_org    ON ms_processings(organization_id);
CREATE INDEX IF NOT EXISTS idx_ms_proc_appl   ON ms_processings(applicable);

-- ─── Матеріали, що були ВИТРАЧЕНІ у processing ──────────────────────────────
-- assortment_id посилається на існуючу таблицю ms_products (з Sales sync),
-- щоб ми могли join'ити для назви, папки, ваги тощо. FOREIGN KEY не ставимо
-- (Worker може писати позиції раніше за продукти при холодному старті).

CREATE TABLE IF NOT EXISTS ms_processing_materials (
  id                   TEXT PRIMARY KEY,           -- composite: <processing_id>:<position_id>
  processing_id        TEXT NOT NULL,
  position_id          TEXT,                       -- ідентифікатор позиції з МС
  assortment_id        TEXT NOT NULL,              -- продукт/варіант
  quantity             REAL DEFAULT 0,             -- у нативних одиницях продукту (кг/шт)
  price_kop            INTEGER DEFAULT 0,
  raw_json             TEXT
);
CREATE INDEX IF NOT EXISTS idx_ms_proc_mat_proc ON ms_processing_materials(processing_id);
CREATE INDEX IF NOT EXISTS idx_ms_proc_mat_ass  ON ms_processing_materials(assortment_id);

-- ─── Продукти, що були ВИРОБЛЕНІ у processing ───────────────────────────────

CREATE TABLE IF NOT EXISTS ms_processing_products (
  id                   TEXT PRIMARY KEY,           -- composite: <processing_id>:<position_id>
  processing_id        TEXT NOT NULL,
  position_id          TEXT,
  assortment_id        TEXT NOT NULL,
  quantity             REAL DEFAULT 0,
  price_kop            INTEGER DEFAULT 0,
  raw_json             TEXT
);
CREATE INDEX IF NOT EXISTS idx_ms_proc_prod_proc ON ms_processing_products(processing_id);
CREATE INDEX IF NOT EXISTS idx_ms_proc_prod_ass  ON ms_processing_products(assortment_id);

-- ─── Snapshot залишків на складах ───────────────────────────────────────────
-- НЕ growing table — кожен sync ПЕРЕЗАПИСУЄ актуальний знімок (TRUNCATE + INSERT).
-- Для історичних залишків будемо мати окрему `proc_stock_history` (наступний крок).

CREATE TABLE IF NOT EXISTS ms_stocks (
  assortment_id        TEXT PRIMARY KEY,           -- product/variant ID
  name                 TEXT,
  code                 TEXT,
  article              TEXT,
  folder_name          TEXT,
  folder_path          TEXT,                       -- pathName з МС
  uom_name             TEXT,                       -- 'кг' / 'шт'
  stock                REAL DEFAULT 0,             -- доступний залишок
  in_transit           REAL DEFAULT 0,
  reserve              REAL DEFAULT 0,
  quantity             REAL DEFAULT 0,             -- stock + in_transit - reserve
  price_kop            INTEGER DEFAULT 0,          -- собівартість
  sale_price_kop       INTEGER DEFAULT 0,
  stock_days           REAL DEFAULT 0,             -- з МС
  snapshot_at          TEXT NOT NULL,              -- iso8601
  raw_json             TEXT
);
CREATE INDEX IF NOT EXISTS idx_ms_stock_folder ON ms_stocks(folder_path);
CREATE INDEX IF NOT EXISTS idx_ms_stock_snap   ON ms_stocks(snapshot_at);

-- ─── Журнал sync ────────────────────────────────────────────────────────────
-- Реюзаємо існуючий ms_sync_log (від Sales sync) — entities_json у procurement
-- буде містити {processings, processing_materials, processing_products, stocks}.
