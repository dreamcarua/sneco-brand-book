# payments-dashboard — рахунки на оплату → Приват24

Розбір архіву рахунків (pdf / скан / doc / xls / фото) → структуровані реквізити + готове
призначення платежу з ПДВ → перевірка у дашборді → (Фаза 3) створення чернеток у Приват24
через API «Автоклієнт». **Гроші не йдуть без підпису КЕП у Приват24.**

Платник: ТОВ «ПРАЙМ СНЕК», ЄДРПОУ **40271201**.

## Потік даних

```
Архів рахунків (ZIP)
   │  завантаження у дашборді (Фаза 2.5: Worker R2)  /  або inbox/*.zip (v1)
   ▼
GitHub Actions: payments-parse.yml → python parse.py
   │  pdftotext / tesseract(ukr+rus) / python-docx / openpyxl  (+ Claude для складних)
   │  правила: IBAN(mod-97, не платника), сума з ПДВ, ПДВ (явний > обчислений), призначення
   │  POST X-Sync-Key
   ▼
Worker /api/dashboard/ingest  → D1 sneco-bible (pmt_batches, pmt_invoices)
   ▲
   │  GET (JWT block=payments-dashboard)
   ▼
dashboard/payments/payments.html  (OTP-gate → review-таблиця → Фаза 3: «Створити чернетки»)
```

## Призначення платежу (формат)

```
Оплата за <послуги> згідно рахунку №<номер> від <дата>, у т.ч. ПДВ 20% - <сума ПДВ> грн
```
Неплатник ПДВ → `..., без ПДВ`. Якщо постачальник диктує призначення/код (напр. ОККО-ДРАЙВ
`7400002034`) — беремо його текст і дописуємо суму ПДВ.

## Прапорці перевірки (severity)

| Колір | Коли | Дія |
|---|---|---|
| 🟩 ok | реквізити й ПДВ з рахунку, IBAN пройшов контр.суму | готово до оплати |
| 🟨 amber | «ПДВ обчислено 20%», «кілька IBAN», «скан/OCR» | звірити перед оплатою |
| 🟥 red | «кілька рахунків у файлі», «IBAN не знайдено/не пройшов» | ручна обробка |

## Локальний запуск / тест

```bash
cd dashboard/payments
python parse.py --zip рахунки.zip --out out.json --dry-run        # без відправки
python parse.py --dir ./inbox --ingest                            # у D1 (env WORKER_URL+SYNC_API_KEY)
python parse.py --zip рахунки.zip --ingest --claude               # +уточнення складних через Claude
```

## Що треба від vg (deploy)

1. **Schema → D1:** `npx wrangler d1 execute sneco-bible --file=dashboard/payments/schema.sql --remote`
2. **Worker:** застосувати diff з PR body у `sneco-auth/src/index.js` (block `payments-dashboard` + entity `pmt_*`), потім `cd sneco-auth && npx wrangler deploy`
3. **Secret:** `SYNC_API_KEY` вже є. Для Claude-уточнення — repo secret `ANTHROPIC_API_KEY`.
4. **Whitelist:** Maintenance → Розподіл доступу → block `payments-dashboard` → vg + Пилип + бухгалтер.
5. **Launcher-картка** у Brand Bible каталозі `sec-dashboard` (окремим commit).

## Статус

- [x] parse.py — багатоформатний парсер + валідація + призначення з ПДВ (перевірено на 35 реальних рахунках: 30 ok / 3 amber / 2 red)
- [x] schema.sql — pmt_batches / pmt_invoices / pmt_sync_log
- [x] payments-parse.yml — GH Action (workflow_dispatch + inbox push)
- [x] Worker diff — block + DASHBOARD_TABLES (у PR body)
- [ ] payments.html — сторінка з OTP-gate + upload + review-таблиця (наступний крок)
- [ ] Фаза 2.5 — завантаження архіву прямо у дашборді (Worker R2 endpoint)
- [ ] Фаза 3 — «Створити чернетки» → Приват24 Автоклієнт API (token+id від vg)
