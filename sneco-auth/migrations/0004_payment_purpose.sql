-- Migration 0004 (v2.72): додаємо payment_purpose + expense_item_id у ms_payments
-- Контекст: parse_payments (moysklad_sync.py v2.72) тепер вивантажує "Призначення" платежу
-- і ID статті витрат окремо. Для Finance Dashboard "Витрати по напрямах" + drill-down.
-- Apply: cd ~/snEco/sneco-auth && npx wrangler d1 execute sneco-bible --file=migrations/0004_payment_purpose.sql --remote

ALTER TABLE ms_payments ADD COLUMN payment_purpose TEXT;
ALTER TABLE ms_payments ADD COLUMN expense_item_id TEXT;

CREATE INDEX IF NOT EXISTS idx_payments_expense_item ON ms_payments(expense_item, ms_moment DESC);
CREATE INDEX IF NOT EXISTS idx_payments_expense_item_id ON ms_payments(expense_item_id, ms_moment DESC);
