-- snEco · D1 schema для payments-dashboard (рахунки на оплату → Приват24)
-- Префікс: pmt_*  (щоб не колідувати з ms_payments / payroll pay_*)
-- Застосувати до бази sneco-bible:
--   npx wrangler d1 execute sneco-bible --file=dashboard/payments/schema.sql --remote

-- Партія (один завантажений архів)
CREATE TABLE IF NOT EXISTS pmt_batches (
  id            TEXT PRIMARY KEY,          -- batch id (timestamp/uuid)
  filename      TEXT,                      -- назва архіву
  uploaded_by   TEXT,                      -- email
  uploaded_at   TEXT,
  file_count    INTEGER DEFAULT 0,
  total_kop     INTEGER DEFAULT 0,         -- сума всіх рахунків, копійки
  status        TEXT DEFAULT 'uploaded',   -- uploaded | parsed | error
  raw_json      TEXT,
  ingested_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pmt_batches_status ON pmt_batches(status);

-- Рахунок (одна платіжка)
CREATE TABLE IF NOT EXISTS pmt_invoices (
  id            TEXT PRIMARY KEY,          -- batch:seq:hash
  batch_id      TEXT,
  file          TEXT,                      -- ім'я файлу-джерела
  recipient     TEXT,                      -- отримувач (продавець)
  edrpou        TEXT,                      -- ЄДРПОУ отримувача
  iban          TEXT,                      -- IBAN отримувача
  iban_valid    INTEGER DEFAULT 0,         -- 1 = пройшов контрольну суму
  invoice_no    TEXT,
  invoice_date  TEXT,                      -- DD.MM.YYYY
  amount_kop    INTEGER,                   -- сума з ПДВ, копійки
  vat_kop       INTEGER,                   -- сума ПДВ, копійки
  vat_rate      INTEGER,                   -- 20 / 7 / 0
  currency      TEXT DEFAULT 'UAH',
  purpose       TEXT,                      -- готове призначення платежу (з ПДВ)
  severity      TEXT DEFAULT 'ok',         -- ok | amber | red
  flags         TEXT,                      -- перелік попереджень
  status        TEXT DEFAULT 'new',        -- new | approved | draft_created | paid | skipped
  raw_json      TEXT,
  ingested_at   INTEGER,
  FOREIGN KEY (batch_id) REFERENCES pmt_batches(id)
);
CREATE INDEX IF NOT EXISTS idx_pmt_inv_batch    ON pmt_invoices(batch_id);
CREATE INDEX IF NOT EXISTS idx_pmt_inv_status   ON pmt_invoices(status);
CREATE INDEX IF NOT EXISTS idx_pmt_inv_severity ON pmt_invoices(severity);
CREATE INDEX IF NOT EXISTS idx_pmt_inv_edrpou   ON pmt_invoices(edrpou);

-- Журнал синку (стандарт)
CREATE TABLE IF NOT EXISTS pmt_sync_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  summary_json  TEXT,
  success       INTEGER DEFAULT 1,
  error_msg     TEXT
);
CREATE INDEX IF NOT EXISTS idx_pmt_sync_finished ON pmt_sync_log(finished_at);
