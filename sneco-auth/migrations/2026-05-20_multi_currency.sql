-- snEco · Multi-Currency Migration · 2026-05-20
-- Додає 3 колонки до 10 транзакційних таблиць щоб правильно обробляти EUR/USD documents.
--
-- Контекст: MoySklad зберігає sum у валюті документа (EUR-document → sum в євроцентах).
-- Поточний код множив на 1 (припускав UAH) → дані EUR-операцій були в 35-45× менші реальної суми у UAH.
--
-- Fix: зберігаємо ОБИДВА:
--   sum_kop          — нормалізовано в UAH (вже сконвертовано × rate_to_uah)
--   sum_orig_kop     — оригінал у валюті документа
--   currency         — код 'UAH'/'EUR'/'USD' тощо
--   rate_to_uah      — курс на момент транзакції (з MoySklad rate.value)
--
-- Backward compatibility: для default 'UAH' rows ці поля = (sum_kop, 'UAH', 1.0) — нічого не ламається.

-- ── Demands (відвантаження) ──────────────────────────────────────
ALTER TABLE ms_demands ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_demands ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_demands ADD COLUMN sum_orig_kop INTEGER;

-- ── Payments (оплати, надходження) ───────────────────────────────
ALTER TABLE ms_payments ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_payments ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_payments ADD COLUMN sum_orig_kop INTEGER;

-- ── Orders (замовлення) ──────────────────────────────────────────
ALTER TABLE ms_orders ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_orders ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_orders ADD COLUMN sum_orig_kop INTEGER;

-- ── Returns (повернення) ─────────────────────────────────────────
ALTER TABLE ms_returns ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_returns ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_returns ADD COLUMN sum_orig_kop INTEGER;

-- ── Invoices Out (рахунки) ───────────────────────────────────────
ALTER TABLE ms_invoices_out ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_invoices_out ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_invoices_out ADD COLUMN sum_orig_kop INTEGER;

-- ── Demand Positions (позиції відвантажень) ──────────────────────
ALTER TABLE ms_demand_positions ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_demand_positions ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_demand_positions ADD COLUMN sum_orig_kop INTEGER;
ALTER TABLE ms_demand_positions ADD COLUMN price_orig_kop INTEGER;

-- ── Processings (виробничі операції) ─────────────────────────────
ALTER TABLE ms_processings ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_processings ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_processings ADD COLUMN processing_sum_orig_kop INTEGER;

-- ── Processing Materials (вхідні матеріали виробництва) ──────────
ALTER TABLE ms_processing_materials ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_processing_materials ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_processing_materials ADD COLUMN price_orig_kop INTEGER;

-- ── Processing Products (вихідні продукти) ───────────────────────
ALTER TABLE ms_processing_products ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_processing_products ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_processing_products ADD COLUMN price_orig_kop INTEGER;

-- ── Stocks (поточні залишки) ─────────────────────────────────────
ALTER TABLE ms_stocks ADD COLUMN currency TEXT DEFAULT 'UAH';
ALTER TABLE ms_stocks ADD COLUMN rate_to_uah REAL DEFAULT 1.0;
ALTER TABLE ms_stocks ADD COLUMN price_orig_kop INTEGER;
ALTER TABLE ms_stocks ADD COLUMN sale_price_orig_kop INTEGER;

-- ── Verify ───────────────────────────────────────────────────────
-- SELECT name, sql FROM sqlite_schema WHERE name LIKE 'ms_%' AND name NOT LIKE '%_sync_log%';
-- SELECT COUNT(*) AS uah_count FROM ms_demands WHERE currency='UAH' OR currency IS NULL;
-- SELECT COUNT(*) AS eur_count FROM ms_demands WHERE currency='EUR';
