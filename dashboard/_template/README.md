# Dashboard Template — як стартувати новий snEco дашборд

> **Для:** Pylyp + його Claude Cowork (та будь-кого хто додає новий дашборд у snEco Brand Bible)
> **Pattern version:** v2.51+
> **Reference:** див. `~/snEco/brand/dashboard/dashboard.html` як еталон (Sales)

---

## TL;DR — 7 кроків від zero до live дашборду

1. **Скопіюй template:**
   ```bash
   cd ~/snEco-brand-book
   mkdir -p dashboard/<your-domain>
   cp dashboard/_template/dashboard-template.html dashboard/<your-domain>/<your-domain>.html
   cp dashboard/_template/sync-template.py dashboard/<your-domain>/sync.py
   cp dashboard/_template/workflow-template.yml .github/workflows/<your-domain>-sync.yml
   ```

2. **Заміни плейсхолдери** у трьох файлах (find&replace):
   - `<DOMAIN>` → твоя назва (e.g. `payroll`, `production`, `finance`)
   - `<BLOCK_NAME>` → `<your-domain>-dashboard` (e.g. `payroll-dashboard`)
   - `<DASHBOARD_TITLE>` → людино-читана назва (e.g. `Payroll Dashboard`)
   - `<TABLE_PREFIX>` → префікс таблиць у D1 (e.g. `pay`, `prod`, `fin`)

3. **Опиши SQL schema** для нових таблиць у `dashboard/<your-domain>/schema.sql`. Vadym застосує до D1 `sneco-bible`.

4. **Напиши логіку sync.py:** як викачувати дані з МойСклад → batch POST на `/api/dashboard/ingest`.

5. **Запиши у `CHANGELOG.md`:**
   ```markdown
   ## [Unreleased] - Pylyp
   ### Added
   - dashboard/<your-domain>/ — initial scaffold
   - .github/workflows/<your-domain>-sync.yml — cron sync
   - dashboard/<your-domain>/schema.sql — D1 tables (потрібен apply від vg)
   ```

6. **Створи feature branch + PR:**
   ```bash
   git checkout -b dashboard/<your-domain>
   git add .
   git commit -m "feat(dashboard/<your-domain>): initial scaffold"
   git push origin dashboard/<your-domain>
   gh pr create --base main --title "Add <your-domain> dashboard" \
     --body-file dashboard/_template/PR_BODY_TEMPLATE.md
   ```

7. **Скажи vg:** «PR #N готовий — потрібен apply schema.sql до D1 + додати block `<BLOCK_NAME>` у Worker SUPPORTED_BLOCKS + redeploy + додати whitelist у KV».

Після того як vg все задеплоїть — твій дашборд буде доступний на:
`https://dreamcarua.github.io/sneco-brand-book/dashboard/<your-domain>/`

---

## Що містить _template/

| Файл | Призначення |
|---|---|
| `dashboard-template.html` | Скелет HTML-сторінки з вбудованим OTP-gate (скопійовано з v2.51 dashboard.html, очищено від Sales-specific коду) |
| `sync-template.py` | Скелет Python-скрипта з МойСклад API client + retry logic + batch ingest до Worker |
| `workflow-template.yml` | GitHub Actions workflow з cron schedule + Python setup + secrets injection |
| `schema-template.sql` | Приклад SQL schema для D1 таблиць (з ms_sync_log аналогом) |
| `PR_BODY_TEMPLATE.md` | Опис для PR body (checklist що зроблено + що треба від vg) |

---

## Архітектура потоку даних

```
МойСклад API
     │ (REST, Bearer MOYSKLAD_TOKEN)
     ▼
GitHub Actions cron (05:00 Київ щодня)
  └─ python sync.py
     │ (POST з SYNC_API_KEY)
     ▼
Worker /api/dashboard/ingest
     │
     ▼
D1 sneco-bible (таблиці <prefix>_*)
     ▲
     │ (GET з JWT)
     │
Worker /api/dashboard/data?type=<table>&from=&to=&limit=
     ▲
     │
Browser: dashboard/<your-domain>/<your-domain>.html
  ↳ OTP-gate (email-OTP) → JWT у localStorage → fetch data → render
```

---

## Domain-specific guidelines

### Payroll dashboard
- Префікс таблиць: `pay_*` (pay_employees, pay_payrolls, pay_taxes)
- Cron: щомісячно або раз на тиждень (зміни рідкі)
- Whitelist: vg + fg + Богдан
- Sensitive! — JWT MUST expire, no caching у browser

### Production dashboard
- Префікс таблиць: `prod_*` (prod_cycles, prod_downtime, prod_quality)
- Cron: кожні 4 год (real-time важливо)
- Whitelist: Pylyp + Bohdan + Valeriia + vg
- Show OEE = Availability × Performance × Quality

### Finance dashboard
- Префікс таблиць: `fin_*` (fin_cashflow, fin_ar, fin_ap, fin_pl)
- Cron: щодня 06:00 Київ (після Sales sync)
- Whitelist: vg + Pylyp + CFO
- Multi-currency: UAH + EUR + USD з ECB rates

---

## Common pitfalls (чого уникати)

1. ❌ **Не дублюй OTP-gate logic.** Скопіюй з template — він уже інтегрований з Worker правильно. Не «оптимізуй» його — воно працює як є.

2. ❌ **Не використовуй iframe для дашборду.** Завжди standalone HTML page. Iframe ламає UX (scroll, height, fullscreen).

3. ❌ **Не запитуй МойСклад API з runtime коду дашборду.** Тільки через cron → D1 → дашборд. Інакше: rate limit, повільно, токен светиться у browser.

4. ❌ **Не зберігай sensitive дані у localStorage поза JWT.** Тільки JWT з coротким TTL.

5. ❌ **Не змінюй `dashboard/dashboard.html` (Sales).** Це чужий дашборд з власним whitelist. Свій — у новій папці.

6. ❌ **Не комить .env або секрети.** `.env` уже у `.gitignore`. Перевір!

7. ❌ **Не намагайся деплоїти Worker.** Тільки vg має CF API access. Якщо потрібна зміна Worker — PR з описом, vg задеплоїть.

---

## Перевірка перед PR (self-review)

- [ ] Файли скопійовано з `_template/`
- [ ] Усі `<DOMAIN>`, `<BLOCK_NAME>`, `<DASHBOARD_TITLE>`, `<TABLE_PREFIX>` замінені
- [ ] OTP-gate логіка не змінена (тільки заміна `block`)
- [ ] sync.py локально запускається без помилок (з твоїм .env)
- [ ] schema.sql валідний SQLite (можна перевірити: `sqlite3 :memory: < schema.sql`)
- [ ] CHANGELOG.md оновлено
- [ ] PR description заповнений (з PR_BODY_TEMPLATE.md)
- [ ] Не зачеплено `!snEco_Brand_Guide.html` (картка-launcher додається окремим commit'ом vg-ом)
- [ ] Не зачеплено інші `dashboard/*` папки

---

*Last updated: 14.05.2026*
