-- v2.67: розширення картки контрагента у D1
-- Додаємо поля з MoySklad картки, які ігнорувалися: legalTitle, fax,
-- legalAddressFull (commentar), balance, overdueDebt, state, description.
-- Для Customer 360 + Finance Dashboard.

ALTER TABLE ms_counterparties ADD COLUMN full_name TEXT;
ALTER TABLE ms_counterparties ADD COLUMN fax TEXT;
ALTER TABLE ms_counterparties ADD COLUMN legal_address_comment TEXT;
ALTER TABLE ms_counterparties ADD COLUMN balance_kop INTEGER DEFAULT 0;
ALTER TABLE ms_counterparties ADD COLUMN overdue_debt_kop INTEGER DEFAULT 0;
ALTER TABLE ms_counterparties ADD COLUMN state TEXT;
ALTER TABLE ms_counterparties ADD COLUMN description TEXT;
-- legal_address, actual_address, email, phone, tags, company_type, code, inn, archived вже існують

CREATE INDEX IF NOT EXISTS idx_counterparties_overdue ON ms_counterparties(overdue_debt_kop);
