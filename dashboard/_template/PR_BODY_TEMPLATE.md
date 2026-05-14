# Add `<DOMAIN>` dashboard

## Summary
<!-- 1-2 речення про що цей дашборд показує і кому потрібен -->

## Files added
- `dashboard/<DOMAIN>/<DOMAIN>.html` — standalone HTML page з OTP-gate
- `dashboard/<DOMAIN>/sync.py` — Python скрипт sync з МойСклад
- `dashboard/<DOMAIN>/schema.sql` — D1 schema для таблиць `<TABLE_PREFIX>_*`
- `.github/workflows/<DOMAIN>-sync.yml` — cron sync (schedule: ___)

## Self-checklist
- [ ] OTP-gate logic скопійований з template, не змінений (тільки `BLOCK` constant)
- [ ] `sync.py` локально запускається без помилок (`python sync.py --dry-run`)
- [ ] `schema.sql` валідний SQLite (перевірено `sqlite3 :memory: < schema.sql`)
- [ ] CHANGELOG.md оновлено (секція [Unreleased] / Pylyp)
- [ ] Не зачеплено `!snEco_Brand_Guide.html` (картка-launcher додасть Vadym окремо)
- [ ] Не зачеплено `dashboard/dashboard.html` (Sales)
- [ ] Не зачеплено `sneco-auth/src/index.js` (Worker)
- [ ] `.env` НЕ закомічено

## Action items для Vadym (потрібно після merge)
- [ ] Apply schema:
  ```
  cd ~/snEco/sneco-auth
  npx wrangler d1 execute sneco-bible --file=../brand/dashboard/<DOMAIN>/schema.sql --remote
  ```
- [ ] Додати block у Worker `SUPPORTED_BLOCKS`:
  ```js
  const SUPPORTED_BLOCKS = ['hr','prices','admin','production','dashboard','<BLOCK_NAME>'];
  ```
  + оновити `blockNice` для UA/EN/SK email subject
- [ ] Redeploy Worker:
  ```
  cd ~/snEco/sneco-auth && npx wrangler deploy
  ```
- [ ] Додати whitelist у KV через Maintenance UI:
  - Block: `<BLOCK_NAME>`
  - Emails: `<list>`
- [ ] Запустити workflow_dispatch вручну для перевірки
- [ ] Додати картку-launcher у `!snEco_Brand_Guide.html` → секція sec-dashboard
- [ ] `publish-sneco "feat: add <DOMAIN> dashboard"`

## Test plan
1. Після merge + deploy відкрити https://dreamcarua.github.io/sneco-brand-book/dashboard/<DOMAIN>/
2. Ввести email з whitelist
3. Перевірити що приходить OTP-код
4. Ввести код → дашборд має розблокуватися
5. Перевірити що last-sync badge показує актуальну дату
6. Перевірити KPI/charts завантажуються
7. Натиснути 🔒 Lock → перевірити що ловер з'являється знову

## Screenshots (опціонально)
<!-- За можливості додай screenshot готового дашборду -->
