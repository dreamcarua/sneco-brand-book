# Finance / P&L Dashboard (POC v0.1)

Локальний дашборд для розуміння P&L підприємства за 2026 рік.

**Що показує:** Помісячна розбивка по кожній юр.особі. База = 100% відвантажень за місяць. Категорії витрат як % від виручки. Net margin лінією.

**Джерело даних:** МойСклад API напряму (без Cloudflare Worker, без D1, без OTP — це локальний інструмент).

## Як запустити

```bash
cd ~/snEco-brand-book
source .venv/bin/activate
python3 dashboard/finance/build.py
```

Скрипт:
1. Підтягне organizations, expense items, demand, paymentout за 2026
2. Збереже raw JSON у `dashboard/finance/data/` (для кешування)
3. Створить `dashboard/finance/data.json` (агрегований датасет)
4. Згенерує `dashboard/finance/finance.html` — self-contained, дані вшиті

Відкрий результат:
```bash
open dashboard/finance/finance.html
```

## Прапори

- `--no-cache` — ігнорує кеш, тягне свіжі дані
- `--skip-fetch` — використовує кешовані JSON, тільки регенерує HTML (швидко, для UI iteration)

## Структура

```
dashboard/finance/
├── build.py        ← скрипт-генератор
├── README.md       ← цей файл
├── .gitignore      ← виключає data/ та згенеровані файли
├── data/           ← raw API responses (cache, gitignored)
│   ├── raw_organizations.json
│   ├── raw_expense_items.json
│   ├── raw_demands.json
│   └── raw_payments_out.json
├── data.json       ← агрегований датасет (gitignored)
└── finance.html    ← згенерований дашборд (gitignored)
```

## Як категоризуються витрати

Беремо поле `expenseItem` з кожного `paymentout`. Якщо у документі стаття витрат не проставлена — попадає у "(Без категорії)". Чим більше документів класифіковані у МойСкладі, тим точніший P&L.

## Що НЕ враховано (ліміти POC)

- ⚠️ Тільки `paymentout` як витрати. Не враховуються supply (закупівлі), нараховані але неоплачені рахунки, амортизація, акруали.
- ⚠️ Тільки `demand` як виручка. Не враховуються повернення (salesreturn).
- ⚠️ Без конвертації валют. UA та SK розділені окремо.
- ⚠️ База = "оплачено", не "нараховано" — це cash-basis P&L, не accrual.

Все це — питання другої ітерації після того як побачимо що показує POC.
