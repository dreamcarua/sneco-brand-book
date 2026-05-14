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

<!-- Pylyp Claude session пише сюди свої зміни. Приклад:

#### Added (DD.MM.YYYY)
- `dashboard/payroll/` — initial scaffold для Payroll Dashboard
- `dashboard/payroll/payroll.html` — UI з KPI: ФОП загальний, по підрозділах, динаміка
- `dashboard/payroll/sync.py` — sync employees + payrolls з МойСклад
- `dashboard/payroll/schema.sql` — pay_employees, pay_payrolls, pay_sync_log
- `.github/workflows/payroll-sync.yml` — cron щоночі 03:00 UTC

#### Blocked (потребує дії від vg)
- [ ] Apply schema.sql до D1 sneco-bible
- [ ] Додати block 'payroll-dashboard' у Worker SUPPORTED_BLOCKS + redeploy
- [ ] Whitelist у KV: vg + fg + Богдан
- [ ] Redeploy через `wrangler deploy`
- [ ] Картка-launcher у Brand Bible sec-dashboard

#### Notes
- Test plan: …
- Open questions for vg: …

-->

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
