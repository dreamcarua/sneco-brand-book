-- v2.61: agent_id для матчингу demands/payments/orders/invoices/returns
-- з counterparties (по MoySklad UUID, не по string name).
ALTER TABLE ms_demands ADD COLUMN agent_id TEXT;
ALTER TABLE ms_payments ADD COLUMN agent_id TEXT;
ALTER TABLE ms_orders ADD COLUMN agent_id TEXT;
ALTER TABLE ms_invoices_out ADD COLUMN agent_id TEXT;
ALTER TABLE ms_returns ADD COLUMN agent_id TEXT;
CREATE INDEX IF NOT EXISTS idx_demands_agent_id ON ms_demands(agent_id);
CREATE INDEX IF NOT EXISTS idx_payments_agent_id ON ms_payments(agent_id);
CREATE INDEX IF NOT EXISTS idx_orders_agent_id ON ms_orders(agent_id);
CREATE INDEX IF NOT EXISTS idx_invoices_out_agent_id ON ms_invoices_out(agent_id);
CREATE INDEX IF NOT EXISTS idx_returns_agent_id ON ms_returns(agent_id);
