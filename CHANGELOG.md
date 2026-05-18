# Changelog — snEco Brand Bible repo

> **Як користуватися:** Кожна Claude Cowork сесія (Vadym і Pylyp) пише сюди свої зміни перед PR / push. Це наша shared дошка координації — щоб обидва завжди бачили що хто робить.
>
> **Формат:** [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), [SemVer](https://semver.org/).
> **Версії Brand Bible:** v2.50, v2.51, v2.52 etc. — окрема нумерація головного HTML.

---

## [Unreleased]

### Vadym

#### Added (Pylyp onboarding infrastructure — 14.05.2026)
- `setup-pylyp.sh` — one-time setup script для Pylyp Mac (git/python/node/gh check, repo clone, venv, .env template)
- `PYLYP_ONBOARDING.md` — повний onboarding для Pylyp Claude Cowork сесії (snEco context, архітектура, scope правила, 7 кроків стартап-чеклист, FAQ, glossary)
- `dashboard/_template/` — скелети для нових дашбордів:
  - `README.md` — інструкція як стартувати новий дашборд
  - `dashboard-template.html` — HTML з вбудованим OTP-gate (DO NOT MODIFY auth)
  - `sync-template.py` — Python sync script template
  - `workflow-template.yml` — GitHub Actions cron template
  - `schema-template.sql` — D1 schema приклад (payroll)
  - `PR_BODY_TEMPLATE.md` — PR description template
- `CHANGELOG.md` (цей файл) — shared activity log
- `.github/PULL_REQUEST_TEMPLATE.md` — auto-PR template
- CLAUDE.md → додано секцію «Колаборація з Pylyp»

#### Pending (vg ще зробить)
- [ ] Налаштувати branch protection на `main` через GitHub UI
- [ ] Push v2.51 + v2.52 (потрібно `publish-sneco` з Mac, file > 1MB)
- [ ] Додати MOYSKLAD_TOKEN у GitHub Secrets repo
- [ ] Видалити Cloudflare API token (cfut_*) — тимчасовий
- [ ] Тестувати workflow_dispatch на GitHub Actions для sales-sync

### Pylyp

#### Added (17.05.2026) — Finance + Procurement dashboards (POC → prod migration)

**Local POC (працює зараз без Vadym):**
- `dashboard/finance/build.py` — pull demands+paymentout з МойСклад → агрегує помісячно по 5 юр.особах → генерує self-contained `finance.html` з консолідованою вкладкою + per-org tabs
- `dashboard/procurement/build.py` — pull processings/positions/stock з МойСклад → виробничий баланс (свіжий→сушений, yield 60-67%) + прогноз днів до закінчення сировини
- `dashboard/serve.py` — локальний HTTP сервер з кнопкою «Оновити дані» у кожному дашборді

**Prod pipeline (готово, чекає Vadym):**
- `dashboard/procurement/schema.sql` — D1 tables `proc_processings`, `proc_processing_materials`, `proc_processing_products`, `proc_stocks`, `proc_sync_log`
- `dashboard/procurement/sync.py` — cron-friendly: pull → batch POST `/api/dashboard/ingest` → `proc_*` tables. `--full` для повного 2026, default last 7d incremental
- `.github/workflows/procurement-sync.yml` — cron 00:00 UTC (03:00 Київ EEST)
- Finance використовує EXISTING `ms_demands` + `ms_payments` (з Sales sync), окремий sync не потрібен
- `dashboard/LAUNCHER_CARDS_FOR_VADYM.md` — HTML snippets для sec-dashboard каталогу

#### Blocked (потребує дії від vg)
- [ ] Додати `finance-dashboard` + `procurement-dashboard` у Worker `SUPPORTED_BLOCKS` + `blockNice`
- [ ] Worker `/api/dashboard/ingest`: додати entity handlers для `processings`, `processing_materials`, `processing_products`, `stocks`
- [ ] Apply schema: `npx wrangler d1 execute sneco-bible --file=dashboard/procurement/schema.sql --remote`
- [ ] KV whitelist (через Maintenance UI):
   - `wl:finance-dashboard`: vg@abrisart.com, fg@abrisart.com
   - `wl:procurement-dashboard`: vg@abrisart.com, fg@abrisart.com
- [ ] GitHub Secrets: `MOYSKLAD_TOKEN` (у CHANGELOG позначено як pending), `SYNC_API_KEY` (підтвердити)
- [ ] Redeploy Worker: `cd ~/snEco/sneco-auth && npx wrangler deploy`
- [ ] Додати launcher cards у `!snEco_Brand_Guide.html` sec-dashboard (snippets у `LAUNCHER_CARDS_FOR_VADYM.md`)
- [ ] Підтвердити формат `/api/dashboard/data` — назви таблиць, параметри URL, ліміти, формат відповіді (потрібно щоб дописати read-side HTML)

#### Pending (Pylyp дописує після Vadym)
- [ ] Static `dashboard/finance/finance.html` з OTP-gate + fetch `/api/dashboard/data?type=ms_demands` + `?type=ms_payments` (зараз тільки локальний POC)
- [ ] Static `dashboard/procurement/procurement.html` з OTP-gate + fetch `proc_*` таблиць
- [ ] Manual test workflow_dispatch для `procurement-sync` після deploy

#### Notes
- **Security:** Поточний Sales дашборд має дані inline у public repo → view-source leak. Pylyp + Vadym домовились мігрувати P&L (sensitive) на D1+JWT pattern (data НЕ в HTML, fetch через Worker з JWT). Sales може залишитися на старому паттерні поки не критично.
- **Inter-company elimination:** консолідований P&L view (5 юр.осіб) має категорії «Перемещение / Вивод Средств / На Абрис / на Пет Корп» що подвоюються між фірмами. Не елімінується у POC — окремий backlog item.
- **Dividends in P&L:** Дивіденди (20% від виручки) поки залишаються у категоріях витрат — backlog: винести у окрему секцію «Розподіл прибутку».

---

## [v2.52] — 14.05.2026

### Changed (Vadym)
- Розділ «📊 Sales Dashboard — МойСклад» перейменовано → «📊 Dashboards» (каталог)
- Sec-dashboard переділано на public catalog page з 6 launcher-картками:
  - Sales (live) → vg/fg/bs
  - Production (planned) → Pylyp/Bohdan/Valeriia/vg
  - Finance (planned) → vg/Pylyp/CFO
  - HR (planned) → vg/fg/Pylyp
  - Marketing (planned) → TBD
  - Export (planned) → TBD
- Removed `is-locked` + `data-otp-block` з sec-dashboard (тепер public)
- Додано Pattern block — 5 правил стандарту v2.51+

### Memory (Vadym)
- Saved `project_sneco_dashboards_pattern` як project rule
- Updated CLAUDE.md з секцією «Dashboards pattern (v2.51+)»

---

## [v2.51] — 14.05.2026

### Changed (Vadym)
- Sales Dashboard більше не iframe — standalone HTML page `dashboard/dashboard.html`
- Додано inline OTP-gate overlay у самий dashboard.html
- Block name: `dashboard`, localStorage key: `snEco-jwt-dashboard`
- 🔒 Lock badge top-right для logout
- Auto-unlock якщо session ще активна

---

## [v2.50] — 14.05.2026

### Added (Vadym)
- Sales Analytics Dashboard з МойСклад data
- Cloudflare D1 (`sneco-bible`) з 9 ms_* таблицями
- Cloudflare Worker endpoints: `/api/dashboard/{ingest,last-sync,data}`
- GitHub Actions cron `.github/workflows/sales-sync.yml` (03:00 UTC щодня)
- `dashboard/sales-sync.py` — Python sync скрипт
- Brand Bible: secret card sec-dashboard з iframe (later refactored у v2.51)

### Worker
- `SUPPORTED_BLOCKS` += `'dashboard'`
- `DASHBOARD_TABLES` whitelist для 9 ms_* entities
- Дані у D1 sneco-bible (ID: aaa513f5-5a90-4b57-a73a-e907c640fd3a)

---

## [v2.49 та раніше]

→ Див. історію commits у git log + детально у `MEMORY_NEW.md` (Vadym local)

Ключові віхи раніше:
- v2.49: Fix OTP whitelist UX
- v2.48: Logistics block move + prices link
- v2.46: 5-EU Markets dossier
- v2.45: sec-exhibitions у Strategy
- v2.40: Production & R&D
- v2.30: SK переклад 100%
- v2.26: OTP authentication замість статичних паролів
- v2.20: Sneco SK команда
- v2.10: Packaging gallery 90×160 мм
- v2.0: Trilingual (UK + EN + SK)

---

*Maintainers: Vadym Hryshyn (vg@abrisart.com) · Pylyp Hryshyn (fg@abrisart.com)*
