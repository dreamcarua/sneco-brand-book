-- Migration 0005 (v2.75.0): CRM-log backend table
-- Replaces localStorage CRM-лог з team-shared D1-backed storage.
-- Кожен новий запис ще додається у МойСклад counterparty.description (write-back).
--
-- Apply: cd ~/snEco/sneco-auth && npx wrangler d1 execute sneco-bible --file=migrations/0005_customer_notes.sql --remote

CREATE TABLE IF NOT EXISTS customer_notes (
  id              TEXT PRIMARY KEY,           -- uuid (генерує Worker)
  customer_key    TEXT NOT NULL,              -- c.__key (cp.id або cp.name) — primary FK у memory
  customer_id     TEXT,                       -- MoySklad cp.id (для PATCH counterparty)
  customer_name   TEXT NOT NULL,              -- для зручності + audit
  note_date       TEXT NOT NULL,              -- YYYY-MM-DD (дата контакту)
  note_type       TEXT NOT NULL,              -- '📞 Дзвінок' / '✉ Email' / '🤝 Зустріч' / '💬 Месенджер' / '📝 Нотатка'
  summary         TEXT NOT NULL,              -- короткий звіт (manager-typed)
  next_step       TEXT,                       -- що далі (опціонально)
  next_date       TEXT,                       -- дата наступного контакту (опціонально)
  author_email    TEXT NOT NULL,              -- хто додав (з JWT)
  author_name     TEXT,                       -- для display
  created_at      INTEGER NOT NULL,           -- unix ts
  updated_at      INTEGER,                    -- unix ts (для edits)
  ms_synced       INTEGER DEFAULT 0,          -- 0/1 — чи задано у MoySklad
  ms_sync_at      INTEGER,                    -- коли успішно sync-нувся
  ms_sync_error   TEXT,                       -- остання помилка sync (для діагностики)
  deleted         INTEGER DEFAULT 0           -- soft delete (історія лишається)
);

CREATE INDEX IF NOT EXISTS idx_notes_customer ON customer_notes(customer_key, note_date DESC) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_notes_author   ON customer_notes(author_email, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_next     ON customer_notes(next_date) WHERE next_date IS NOT NULL AND deleted = 0;
CREATE INDEX IF NOT EXISTS idx_notes_ms_pending ON customer_notes(ms_synced) WHERE ms_synced = 0 AND deleted = 0;
