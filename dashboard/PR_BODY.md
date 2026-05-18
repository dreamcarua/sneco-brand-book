# Add Finance (P&L) + Procurement (Planning) dashboards

## Summary

Два нові дашборди — **Finance** (P&L по 5 UAH юр.особах за 2026) і **Procurement** (виробничий баланс свіжого/сушеного сиру + прогноз днів до закінчення). Архітектура — за паттерном v2.51+ (standalone HTML + OTP-gate + fetch з D1 через POST `/api/dashboard/data`).

**Finance** уже unblocked — Vadym підтвердив що `finance-dashboard` block є у Worker. Reuse'имо існуючі `ms_demands` + `ms_payments` (з Sales sync) — окремий sync не потрібен.

**Procurement** потребує нової інфраструктури — додав `ms_processings`/`ms_processing_materials`/`ms_processing_products`/`ms_stocks` schema + sync.py + workflow + entity handlers у Worker (Vadym додає).

Локальний POC (`build.py` + `serve.py`) залишається як fallback — згенерує `local-preview.html`, доступний без D1.

---

## Files added/changed

### Procurement prod pipeline
- `dashboard/procurement/schema.sql` — D1 tables (`ms_processings`, `ms_processing_materials`, `ms_processing_products`, `ms_stocks`). Реюзає існуючий `ms_sync_log`.
- `dashboard/procurement/sync.py` — fetch МойСклад → batch POST `/api/dashboard/ingest`. `--full` для повного 2026, default last 7d incremental.
- `.github/workflows/procurement-sync.yml` — cron daily 00:00 UTC (03:00 Київ EEST).

### Prod static HTML (OTP-gate + POST API fetch)
- `dashboard/finance/finance.html` — OTP-gate `block=finance-dashboard`, POST `/api/dashboard/data` для demands+payments, client-side aggregation, 6 tabs (5 юр.осіб + консолідований).
- `dashboard/procurement/procurement.html` — OTP-gate `block=procurement-dashboard`, читає `ms_stocks` для прогнозу. Якщо schema/entity handlers ще не задеплоєні — показує `⏳ Очікуємо Vadym'а` з лінком на `local-preview.html`. **v2 (повний виробничий баланс з processings) — у roadmap**.

### Local POC (для розробки без D1)
- `dashboard/finance/build.py` + `dashboard/procurement/build.py` — генерують `local-preview.html`.
- `dashboard/finance/local-preview.html` + `dashboard/procurement/local-preview.html` — поточні згенеровані версії (gitignored, бо містять inline дані).
- `dashboard/serve.py` — local HTTP server з refresh button. Адаптовано: показує `*-local-preview.html`.

### Docs
- `dashboard/LAUNCHER_CARDS_FOR_VADYM.md` — HTML snippets для sec-dashboard каталогу.
- `dashboard/PR_BODY.md` — цей файл.
- `CHANGELOG.md` — оновлено секцію Pylyp.

---

## Self-checklist
- [x] `schema.sql` валідний SQLite — `proc_*` → `ms_*` (per Vadym конвенцію)
- [x] `sync.py` локально компілюється; `--dry-run` працює
- [x] Workflow yaml валідний (cron `0 0 * * *` = 03:00 Київ EEST)
- [x] **API виправлено по Vadym уточненню:** POST з JSON-body, не GET; response `{items, limit, offset, count}`, не `{rows, total}`
- [x] HTML використовує `block=finance-dashboard` / `procurement-dashboard` (Vadym підтвердив що `finance-dashboard` вже є у Worker)
- [x] CHANGELOG.md оновлено
- [x] НЕ зачеплено `!snEco_Brand_Guide.html` (snippets у `LAUNCHER_CARDS_FOR_VADYM.md`)
- [x] НЕ зачеплено `dashboard/dashboard.html` (Sales)
- [x] НЕ зачеплено `sneco-auth/src/index.js` (Worker — Vadym застосує)
- [x] `.env` НЕ закомічено

---

## Action items для Vadym

### 🟢 Finance (тільки KV + merge):
1. KV `wl:finance-dashboard` → `vg@sneco.ua, fg@abrisart.com` (через Maintenance UI)
2. Merge цей PR + `publish-sneco` з launcher cards (snippets у `LAUNCHER_CARDS_FOR_VADYM.md`)

> Worker code зміни **НЕ потрібні** — `finance-dashboard` block уже є у `SUPPORTED_BLOCKS` (рядок 21), `DASHBOARD_BLOCKS` Set, `blockNice` (рядок 200). Finance читає існуючі `ms_demands` + `ms_payments`.

### 🟡 Procurement (потребує deploy):
1. **Apply schema** (4 нові таблиці):
   ```bash
   cd ~/snEco/sneco-auth
   npx wrangler d1 execute sneco-bible --file=../sneco-brand-book/dashboard/procurement/schema.sql --remote
   ```

2. **Додати у Worker `sneco-auth/src/index.js`:**
   ```js
   // SUPPORTED_BLOCKS + DASHBOARD_BLOCKS Set + blockNice
   'procurement-dashboard'
   
   // blockNice
   'procurement-dashboard': { uk: 'Закупки', en: 'Procurement', sk: 'Nákup' }
   
   // DASHBOARD_TABLES (рядок 594) — 4 нові entities → tables:
   'processings':           'ms_processings',
   'processing_materials':  'ms_processing_materials',
   'processing_products':   'ms_processing_products',
   'stocks':                'ms_stocks',
   ```

   Column mapping (per row, що `sync.py` посилає): дивись build функції у `dashboard/procurement/sync.py` (рядки 145-205) — `build_processing_row()`, `build_position_rows()`, `build_stock_row()`. Колонки збігаються 1:1 з schema.

   **Special case для `ms_stocks`:** це snapshot table — кожен sync має робити `DELETE FROM ms_stocks; INSERT ...` замість upsert. Або upsert на PK `assortment_id` теж OK.

3. **Redeploy:**
   ```bash
   cd ~/snEco/sneco-auth && npx wrangler deploy
   ```

4. **KV** `wl:procurement-dashboard` → `vg@sneco.ua, fg@abrisart.com`

5. **Запустити перший sync вручну:**
   - GitHub Actions → "Procurement Sync" → Run workflow → `full=true`
   - ETA: ~10 хв (1144 processings + 2288 position GET'ів)
   - Verify: `wrangler d1 execute sneco-bible --command "SELECT COUNT(*) FROM ms_processings" --remote`

### Спільне:
6. **Launcher cards у Brand Bible** — snippets у `dashboard/LAUNCHER_CARDS_FOR_VADYM.md`:
   - Оновити KPI strip `3` → `5` live, `4+` → `2+` planned
   - Додати 2 нові cards у Live секції
   - Видалити Finance з "Planned"
   - `publish-sneco "feat: finance + procurement launcher cards"`

---

## Test plan

### Finance (тестуємо одразу після KV додавання):
1. https://brand.sneco.ua/dashboard/finance/ → OTP-gate
2. fg@abrisart.com → код → unlock
3. Має побачити: badge `Останній sync: <дата> · 6 орг (вкл. консолідований) · 5 міс · ~2270 demands + ~1340 payments`
4. 6 tabs, перша «Всі юр.особи (5)» — жовта, з note про inter-company
5. KPI + stacked chart (категорії % від виручки) + помісячна таблиця
6. 🔒 Lock → знову gate

### Procurement (тестуємо після schema apply + sync run):
1. https://brand.sneco.ua/dashboard/procurement/ → OTP-gate `procurement-dashboard`
2. Має побачити: список 50+ матеріалів з прогнозом днів вистачить (від МойСклад's `stockDays`)
3. Якщо `ms_stocks` пуста — показує `⏳ Очікуємо перший sync`
4. Якщо entity handlers відсутні у Worker — показує `⏳ Очікуємо Vadym deployment`

---

## Open questions / next iterations

1. **Procurement v2 (повний виробничий баланс):** поточна prod-версія показує тільки прогноз з `ms_stocks` (1 snapshot). Повна агрегація з processing операцій + матеріали/продукти positions потребує або client-side fetch ~12k рядків (24MB JSON, повільно), або серверного pre-aggregation endpoint у Worker (наприклад `POST /api/dashboard/procurement-summary` що повертає готовий summary). Запропоную окремий PR після того як побачимо реальну швидкість Workера на нашій вибірці.

2. **Pagination у `/api/dashboard/data`:** finance.html робить fetch по 10k за раз, але `count` = page size, не total. Якщо у нас з'явиться > 10k demands за рік — буде O(N) pages. Для 2026 OK (2.2k demands), для багаторічних запитів — оптимізувати.

3. **Inter-company elimination (P&L):** консолідований view подвоює внутрішньогрупові потоки (Перемещение / На Абрис / на Пет Корп). Потрібна логіка маркування трансакцій. Backlog.

4. **Dividends в P&L:** дивіденди (20% від виручки) поки у категоріях витрат. Backlog: винести у окрему секцію «Розподіл прибутку».

5. **Inventory vs Procurement overlap:** у каталозі вже є `inventory-dashboard`. Procurement більше про планування закупок (yield, days-to-stockout). Як назвати/розмежувати? Думки?

---

## Screenshots

Локальні POC версії доступні через `python3 dashboard/serve.py` на Pylyp Mac:
- Finance: 5 юр.осіб + консолідований tab, P&L таблиця, chart
- Procurement: KPI, виробничий баланс, прогноз стоку з кольоровою маркуванням

Prod скріни додам коли Vadym задеплоїть і Finance запрацює на brand.sneco.ua.
