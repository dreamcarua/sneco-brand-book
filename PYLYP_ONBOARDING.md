# PYLYP_ONBOARDING.md

> **Призначення цього файлу:** Це перший документ, який має прочитати твій Claude Cowork після того, як ти відкрив папку `~/snEco-brand-book/` як workspace. Він дає повний контекст snEco, нашої системи Brand Bible, того **що ти можеш робити** і **що НЕ можна робити без узгодження з Vadym**, плюс готові шаблони для створення нових дашбордів.

> **Кому:** Пилип Гришин (fg@abrisart.com), співзасновник snEco, відповідає за виробництво/фінанси/операційку.
> **Від:** Vadym (через Claude session 14.05.2026, v2.52 Brand Bible).

---

## 0. Hello, Pylyp's Claude 👋

Цей repo — `sneco-brand-book` — це **жива онлайн Brand Bible** snEco, опублікована на https://dreamcarua.github.io/sneco-brand-book/. Vadym і Пилип працюють над нею паралельно через окремі Claude Cowork сесії.

**Твоя місія тут:** допомагати Пилипу будувати **нові дашборди** (production, finance, HR, payroll тощо) у вже готовій інфраструктурі — без поломки існуючого коду.

Перед тим як щось робити, обов'язково прочитай:
1. Цей файл (PYLYP_ONBOARDING.md) — увесь
2. `CLAUDE.md` у корені repo — загальний контекст snEco
3. `CHANGELOG.md` — що вже зроблено і ким
4. `dashboard/_template/README.md` — як стартувати новий дашборд

Потім скажи Пилипу: «Я прочитав onboarding. Контекст ясний. Над чим починаємо — payroll dashboard, production efficiency, чи щось інше?»

---

## 1. Контекст snEco (стисло)

**snEco** (sneco.ua) — бренд хрустких сирних снеків зі 100% натурального сиру, виготовлених за власною патентованою технологією **VacWave Bio Nutrition** (мікрохвильово-вакуумна сушка при 36-38°C).

| Параметр | Значення |
|---|---|
| Виручка | ~$1 млн/рік |
| Заводи | Мукачево (UA) + Гуменне (SK) |
| Юр. особи | ТОВ «Прайм Снек» (UA) + Sneco SK s.r.o. |
| Ринки | UA, SK активні; SE через Arvid Nordquist; PL/DE/US/EE — в процесі |
| Сертифікати | FSSC 22000, ISO 22000, HACCP, IFS Food v8, FDA, Patent UA №139035 |
| Нагороди | SIAL Grand Prix 2024 (Париж), EU Ambassador Award |

**Команда:**
- **Vadym Hryshyn** (vg@abrisart.com) — стратегія, маркетинг, продажі
- **Пилип Hryshyn** (fg@abrisart.com) — **це ти будеш йому допомагати** — виробництво, фінанси, операційка
- **Богдан** — COO
- **Ярослав** — комерційний директор
- **Ірина** — Head of Export
- **Валерія** — виробництво (Мукачево)

**Заборонено:**
- ❌ Не казати «NASA-технологія» — є власна запатентована (можна «inspired by NASA», але без надмірного акценту)
- ❌ Не використовувати «лотерея/розіграш/квиток» (це для DreamCar — не snEco, але правило загальне для сім'ї проектів)

---

## 2. Архітектура системи (що вже існує)

```
┌─────────────────────────────────────────────────────────────┐
│ GitHub repo: dreamcarua/sneco-brand-book (public)            │
│  ├── !snEco_Brand_Guide.html  ← головна Brand Bible (1.2MB) │
│  ├── dashboard/                                              │
│  │    ├── dashboard.html      ← Sales (vg/fg/bs)            │
│  │    └── _template/          ← скелет для нових            │
│  ├── .github/workflows/       ← CI/CD + cron sync           │
│  ├── CLAUDE.md                ← context для Claude          │
│  ├── PYLYP_ONBOARDING.md      ← цей файл                    │
│  └── CHANGELOG.md             ← shared activity log         │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ Cloudflare account (ab63a85bdfbf5894c28efe7076acbd82)        │
│  ├── Worker: sneco-auth.vg-ab6.workers.dev                  │
│  │    ├── /api/auth/*       — OTP-gate (email-OTP)          │
│  │    ├── /api/dashboard/*  — sync + read endpoints         │
│  │    └── SUPPORTED_BLOCKS  — реєстр захищених блоків       │
│  ├── D1: sneco-bible        — SQL база, ms_* таблиці        │
│  ├── KV: OTP_KV             — whitelist + sessions          │
│  └── R2: sneco-files        — статичні файли                │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ GitHub Pages: dreamcarua.github.io/sneco-brand-book/         │
│ → опубліковано з main гілки                                  │
└─────────────────────────────────────────────────────────────┘
```

**Як це все взаємодіє:**

1. Користувач відкриває `dashboard/dashboard.html` → бачить OTP-gate → вводить email + код з пошти → Worker перевіряє whitelist у KV → видає JWT → дашборд робить fetch до `/api/dashboard/data` з Bearer JWT → Worker читає з D1 → повертає JSON → дашборд рендерить.

2. Дані у D1 наповнює **GitHub Actions cron** (`.github/workflows/sales-sync.yml`) о 03:00 UTC щодня: Python-скрипт викачує дані з МойСклад → POST на `/api/dashboard/ingest` з SYNC_API_KEY → Worker записує у відповідні `ms_*` таблиці.

3. Brand Bible (`!snEco_Brand_Guide.html`) — це окрема монолітна сторінка, де у каталозі `📊 Dashboards` (sec-dashboard) є картки-launcher'и на кожний дашборд.

---

## 3. Твоя scope: що МОЖЕШ і що НЕ МОЖЕШ

### ✅ Можеш робити (без запитів до vg):

- Створювати **нові папки** у `dashboard/<твоя-назва>/` з власним HTML дашбордом
- Створювати **нові GitHub Actions workflows** у `.github/workflows/<твій-назва>-sync.yml`
- Створювати **нові Python sync-скрипти** у `dashboard/<твоя-назва>/sync.py`
- Писати у **CHANGELOG.md** — записуй кожну свою зміну
- Створювати **нові `.md` файли документації** у корені або в `docs/`
- Робити **PR** у `main` (vg буде ревʼювити та мерджити)
- Читати/запитувати дані з МойСклад через токен (Vadym дасть)

### ⚠️ Можеш робити, але через PR + узгодження:

- Додавати **нову картку дашборду** у `!snEco_Brand_Guide.html` → секція sec-dashboard
- Змінювати **CLAUDE.md** (тільки додавати, не видаляти існуюче)
- Додавати **нові таблиці** у D1 (треба надати CREATE TABLE SQL — vg запустить)

### ❌ НЕ можна без явного дозволу vg:

- Редагувати **`!snEco_Brand_Guide.html`** поза секцією sec-dashboard (вся візуальна ідентичність, контент, тексти — там 1.2MB і 18 розділів)
- Редагувати **`sneco-auth/src/index.js`** (Worker code) — це може зламати auth у всіх інших блоках
- Деплоїти Worker (тільки vg має CF API access)
- Видаляти **існуючі `dashboard/*` папки** або їх вміст
- Змінювати **`SUPPORTED_BLOCKS`** у Worker (треба запит у vg)
- Видаляти **GitHub Secrets** або branch protection
- Працювати з **prod базою sneco** WordPress (`sneco.ua`) — це окрема система
- Ставити **whitelist** у KV (vg має admin UI у Brand Bible → Maintenance → Розподіл доступу)
- Робити **`git push --force`** на main
- Працювати з **PROD WordPress** (`sneco.ua`) — окремий сервер, окремі правила, не наша зона
- Торкатися **`documents/`** (це повна юр. база сертифікатів — read-only)

### 🔁 Workflow для нової фічі:

1. Створи feature branch: `git checkout -b dashboard/<твоя-назва>`
2. Зроби зміни (HTML, sync.py, workflow.yml)
3. Запиши у CHANGELOG.md (секція [Unreleased] → подсекція "Pylyp")
4. `git push origin dashboard/<твоя-назва>`
5. Створи PR у main з описом за PR-шаблоном
6. Скажи vg у Slack / WhatsApp / email: «PR #N готовий до review» з лінком
7. vg зробить review → merge → якщо треба новий block у Worker — vg задеплоїть → tell you it's done
8. Перевір що дашборд працює на production: https://dreamcarua.github.io/sneco-brand-book/dashboard/<твоя-назва>/

---

## 4. Стандарт нових дашбордів (ОБОВ'ЯЗКОВО прочитати)

Це канонічний **pattern v2.51+** — усі нові snEco дашборди будуються однаково. Не імпровізуй.

### Правила:

1. **Standalone HTML page**, не iframe
   - Живе у `dashboard/<your-domain>/<your-domain>.html`
   - Повна ширина, native UX, browser-friendly

2. **Власний OTP-gate inline у файлі**
   - Скопіюй з `dashboard/_template/dashboard-template.html`
   - Worker уже знає auth flow — треба лише виставити свій `block` name
   - Той самий Worker `sneco-auth.vg-ab6.workers.dev`
   - Окремий `SUPPORTED_BLOCKS` запис у Worker (треба запит у vg) — наприклад `'payroll-dashboard'`
   - Окремий KV ключ `wl:<block-name>` зі своїм списком emails (vg додає через Maintenance UI)
   - Сесія у localStorage, ключ `snEco-jwt-<block-name>`, TTL 1 год
   - 🔒 Lock-кнопка top-right для logout

3. **Окремий whitelist per dashboard** (vg налаштовує)
   - Sales — vg/fg/bs
   - Production — Pylyp + Bohdan + Valeriia + vg
   - Finance — vg + Pylyp + CFO
   - HR/Payroll — vg + fg + Pylyp
   - Тощо

4. **Дані у Cloudflare D1** (база `sneco-bible`, таблиці з префіксом домену)
   - Production → `prod_*`
   - Finance → `fin_*`
   - HR/Payroll → `hr_*` (вже зайнято старим HR розділом — обережно, перевір!)
   - Marketing → `mkt_*`
   - Export → `exp_*`

5. **Naming convention:**
   - Block name: `<domain>-dashboard` (production-dashboard, payroll-dashboard)
   - Folder: `dashboard/<domain>/<domain>.html`
   - GitHub Actions workflow: `.github/workflows/<domain>-sync.yml`
   - Worker block в URL token: same as block name

6. **Sync через GitHub Actions cron** (не runtime fetch у Worker)
   - Python-скрипт у `dashboard/<domain>/sync.py`
   - Cron schedule адекватний (для payroll — раз на день; для production — кожні 4 год)
   - POST на `/api/dashboard/ingest` з SYNC_API_KEY (GitHub Secret)
   - Зчитує з МойСклад API через токен (GitHub Secret `MOYSKLAD_TOKEN`)

7. **Картка-launcher у Brand Bible** (через PR на vg)
   - Секція sec-dashboard у `!snEco_Brand_Guide.html`
   - Іконка emoji + назва + опис (~2 речення) + перелік KPI/charts/tables + хто має доступ + кнопка Open ↗

→ Деталі: дивись `dashboard/dashboard.html` як еталон + `dashboard/_template/` як скелет.

---

## 5. Перші кроки — checklist (зроби раз, потім назавжди в'їхав)

- [ ] Прочитав цей файл повністю
- [ ] Прочитав `CLAUDE.md` (загальний context snEco)
- [ ] Прочитав `CHANGELOG.md` (поточний стан)
- [ ] Прочитав `dashboard/_template/README.md` (як стартувати новий дашборд)
- [ ] Подивився як працює існуючий `dashboard/dashboard.html` (Sales) — як еталон
- [ ] У `.env` всі секрети заповнені (`MOYSKLAD_TOKEN`, `SYNC_API_KEY` — попроси у vg)
- [ ] Виконав `gh auth status` — GitHub auth OK
- [ ] Виконав `git config user.name` + `user.email` — git config OK
- [ ] Підтвердив vg готовність почати першу задачу

---

## 6. Перша задача — пропозиції для початку

Vadym залишає вибір на тебе. Ось 3 хороші старти:

### Варіант A: **Payroll/ZP Fund Dashboard** (найкорисніше для тебе)
- Domain: `payroll`
- Block: `payroll-dashboard`
- Whitelist: vg + fg + Богдан (HR доступ)
- Дані: МойСклад employees + manual входи з ZP файлу (`brand/hr/zp-vyrobnytstvo.html`)
- KPI: total ФОП, по підрозділах, динаміка міс/міс, top-5 виплат, сукупний податок

### Варіант B: **Production Efficiency Dashboard**
- Domain: `production`
- Block: `production-dashboard`
- Whitelist: Pylyp + Bohdan + Valeriia + vg
- Дані: МойСклад production cycles + manual quality reports
- KPI: OEE, downtime, batch yield по smaках, відходи %, утиль обладнання

### Варіант C: **Finance Dashboard** (найскладніший — потребує bookkeeping integration)
- Domain: `finance`
- Block: `finance-dashboard`
- Whitelist: vg + Pylyp + CFO (коли буде)
- Дані: МойСклад фінчастина + UAH/EUR/USD currency rates
- KPI: cashflow, AR/AP aging, monthly P&L, currency exposure

**Recommendation:** почни з **A (Payroll)** — найвища додана цінність для тебе особисто, найпростіша інтеграція, дані вже є.

---

## 7. Communication / Coordination

| Інструмент | Як використовуємо |
|---|---|
| **GitHub commits/PRs** | Основний канал — vg бачить через email notifications |
| **`CHANGELOG.md`** | Shared лог, обидві Claude-сесії пишуть свої кроки сюди |
| **WhatsApp / Slack / email** | Тільки для асинхронних запитів («PR готовий», «потрібен новий block у Worker», «треба whitelist додати») |
| **Code review** | vg ревʼюїть кожний PR перед merge |

**Важливо:** не очікуй що vg одразу побачить твій commit. Якщо це блокує тебе — пиши йому напряму.

---

## 8. Useful commands cheatsheet

```bash
# Активувати venv
cd ~/snEco-brand-book && source .venv/bin/activate

# Створити новий дашборд (приклад payroll)
mkdir -p dashboard/payroll
cp dashboard/_template/dashboard-template.html dashboard/payroll/payroll.html
cp dashboard/_template/sync-template.py dashboard/payroll/sync.py
cp dashboard/_template/workflow-template.yml .github/workflows/payroll-sync.yml

# Тестувати sync локально
cd dashboard/payroll
python sync.py  # використовує .env

# Запушити feature branch
git checkout -b dashboard/payroll
git add dashboard/payroll/ .github/workflows/payroll-sync.yml CHANGELOG.md
git commit -m "feat(dashboard/payroll): initial scaffold"
git push origin dashboard/payroll

# Створити PR
gh pr create --base main --head dashboard/payroll \
  --title "Add payroll dashboard" \
  --body "Closes #N. Creates payroll-dashboard with ms_payroll_* tables..."

# Перевірити Worker production endpoints
curl https://sneco-auth.vg-ab6.workers.dev/api/health
```

---

## 9. FAQ (preempt common questions)

**Q: Чи можна тестувати Worker endpoints локально?**
A: Ні, Worker крутиться у Cloudflare. Локально тестуй sync.py — він б'є на production endpoint з SYNC_API_KEY.

**Q: Як отримати MOYSKLAD_TOKEN?**
A: Попроси у vg (vg@abrisart.com). Токен у його `.env` і у GitHub Secrets repo (вже налаштовано).

**Q: Як додати новий `block` у Worker?**
A: Запиши у PR description: «Need new block `<name>` added to SUPPORTED_BLOCKS». vg оновить `sneco-auth/src/index.js` і задеплоїть.

**Q: Чи можна редагувати картки у sec-dashboard каталозі Brand Bible?**
A: Через PR — так. Скопіюй з PR template шаблон картки, додай свою, vg merge'не.

**Q: Що робити, якщо щось зламалось?**
A: НЕ намагайся самостійно фіксити Worker або prod — пиши vg негайно. Можеш лише revert свій commit (`git revert <sha>`).

**Q: Чи бачить vg-ова Claude session мою роботу?**
A: Ні. Вона бачить тільки те що в repo (commits, branches, files). Тому **CHANGELOG.md** + чіткі commit messages — критичні.

**Q: Чи є rate limit на МойСклад API?**
A: Так, ~50 req/sec. Скрипт у `_template/sync-template.py` має retry logic.

---

## 10. Glossary (коротко)

| Термін | Пояснення |
|---|---|
| **Brand Bible** | `!snEco_Brand_Guide.html` — головний документ snEco |
| **OTP-gate** | Email-OTP захист (без паролів — код на пошту, JWT 1h) |
| **Worker** | Cloudflare Workers — serverless API на edge |
| **D1** | Cloudflare SQLite-on-edge (розподілена база) |
| **KV** | Cloudflare key-value store (whitelist, sessions) |
| **block** | Логічна одиниця auth (e.g. 'dashboard', 'hr', 'prices') |
| **whitelist** | Список emails, які можуть запросити OTP для конкретного block'у |
| **SYNC_API_KEY** | Bearer token для cron-jobs (НЕ для users) |
| **МойСклад** | ERP, в якому вся товарна/складська/виробнича облiк snEco |
| **publish-sneco** | Bash alias на Vadym Mac для синку local→GitHub Pages |

---

## 11. Final note

Ця система стабільна. Vadym потратив багато часу на її побудову (Cloudflare Worker + D1 + KV + Actions cron + публічний repo + OTP auth). Її просто розширювати — складно перебудовувати.

**Твоє завдання:** додавати **нові** дашборди як **нові плитки до існуючого фундаменту**. Не переписувати фундамент.

Якщо застряг — створи issue у repo з тегом `question` і тегни Vadym. Або просто напиши у CHANGELOG.md в секції "Pylyp / blocked".

Welcome aboard! 🚀

---

*Last updated: 14.05.2026 by Vadym (через Claude Cowork session, Brand Bible v2.52)*
