-- snEco · D1 schema template для нового дашборду
-- Скопіюй у dashboard/<DOMAIN>/schema.sql, заміни <TABLE_PREFIX> та таблиці нижче.
-- Vadym застосує до базы sneco-bible через Cloudflare API:
--   wrangler d1 execute sneco-bible --file=dashboard/<DOMAIN>/schema.sql --remote

-- ─── Приклад для payroll dashboard (TABLE_PREFIX=pay) ─────────────────────────

-- Працівники
CREATE TABLE IF NOT EXISTS pay_employees (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  email           TEXT,
  department      TEXT,
  position        TEXT,
  hired_at        TEXT,
  archived        INTEGER DEFAULT 0,
  updated         TEXT,
  raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_pay_emp_dept ON pay_employees(department);
CREATE INDEX IF NOT EXISTS idx_pay_emp_archived ON pay_employees(archived);

-- Виплати
CREATE TABLE IF NOT EXISTS pay_payrolls (
  id              TEXT PRIMARY KEY,
  employee_id     TEXT NOT NULL,
  period          TEXT NOT NULL,         -- 'YYYY-MM'
  base_uah        REAL DEFAULT 0,
  bonus_uah       REAL DEFAULT 0,
  total_uah       REAL DEFAULT 0,
  tax_uah         REAL DEFAULT 0,
  paid_at         TEXT,
  created         TEXT,
  raw_json        TEXT,
  FOREIGN KEY (employee_id) REFERENCES pay_employees(id)
);
CREATE INDEX IF NOT EXISTS idx_pay_payrolls_period ON pay_payrolls(period);
CREATE INDEX IF NOT EXISTS idx_pay_payrolls_emp ON pay_payrolls(employee_id);

-- Журнал синку (стандарт для всіх дашбордів)
CREATE TABLE IF NOT EXISTS pay_sync_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  summary_json    TEXT,
  success         INTEGER DEFAULT 1,
  error_msg       TEXT
);
CREATE INDEX IF NOT EXISTS idx_pay_sync_finished ON pay_sync_log(finished_at);

-- ─── End of template ─────────────────────────────────────────────────────────
-- Best practices:
-- 1. Всі таблиці мають префікс <TABLE_PREFIX>_*
-- 2. raw_json колонка для повного payload з API (відсилає debug)
-- 3. *_sync_log таблиця у кожного дашборду (потрібна для last-sync badge)
-- 4. Indexes на колонки які фільтруються/сортуються найчастіше
-- 5. FOREIGN KEY якщо логічно зв'язані
