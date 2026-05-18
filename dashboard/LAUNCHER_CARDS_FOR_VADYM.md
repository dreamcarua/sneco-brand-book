# Launcher cards для sec-dashboard (Finance + Procurement)

> **Для Vadym:** Скопіюй блоки нижче у `!snEco_Brand_Guide.html` → секція `<section id="sec-dashboard">`. Потім запусти `publish-sneco "feat: add finance + procurement launcher cards"`.
>
> Pylyp Brand Bible HTML НЕ редагую напряму (CLAUDE.md правило). Передаю змінами як snippets.

---

## 1. Оновити KPI strip (3 → 5 active)

**Знайди** у sec-dashboard:

```html
<div class="card card-sm" style="background:var(--black);color:#fff;text-align:center">
  <div style="font-size:32px;font-weight:900;color:var(--yellow);line-height:1">3</div>
  <div style="font-size:11px;color:rgba(255,255,255,0.6);margin-top:6px;letter-spacing:0.04em;text-transform:uppercase">
    <span data-lang="uk">live дашборди</span><span data-lang="en">live dashboards</span><span data-lang="sk">live dashboardy</span>
  </div>
</div>
<div class="card card-sm" style="background:var(--yellow);color:var(--black);text-align:center">
  <div style="font-size:32px;font-weight:900;line-height:1">4+</div>
```

**Заміни** `3` → `5` і `4+` → `2+`.

---

## 2. Додати 2 нові launcher cards у Live секції

**Знайди** після Inventory + Production grid-2 блоку (`<div class="grid-2" style="margin-top:18px">…</div>`) і додай новий grid-2 нижче:

```html
  <!-- v2.53+: Finance + Procurement launcher cards (Pylyp) -->
  <div class="grid-2" style="margin-top:18px">
    <a href="dashboard/finance/" target="_blank" rel="noopener" style="display:block;background:linear-gradient(135deg, #1E1E1E 0%, #2A2A2A 100%);color:#fff;padding:24px 22px;border-radius:var(--radius);text-decoration:none;position:relative;overflow:hidden;border:1px solid rgba(254,191,39,0.2)">
      <div style="position:absolute;top:-40px;right:-40px;width:160px;height:160px;border-radius:50%;background:radial-gradient(circle, rgba(254,191,39,0.12) 0%, transparent 70%);pointer-events:none"></div>
      <div style="position:relative">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:var(--yellow);margin-bottom:8px">💰 Finance / P&amp;L</div>
        <div style="font-size:20px;font-weight:800;letter-spacing:-0.3px;line-height:1.2;margin-bottom:10px">
          <span data-lang="uk">Виручка vs витрати по місяцях</span><span data-lang="en">Revenue vs expenses monthly</span><span data-lang="sk">Tržby vs náklady mesačne</span>
        </div>
        <div style="font-size:13px;line-height:1.55;color:rgba(255,255,255,0.78);margin-bottom:14px">
          <span data-lang="uk">Консолідований P&amp;L: 5 юр.осіб (ТОВ Прайм-Снек + 4 ФОП), категорії витрат як % від виручки, помісячна динаміка, net margin. Дані з МойСклад. Whitelist: vg, fg.</span>
          <span data-lang="en">Consolidated P&amp;L: 5 legal entities, expense categories as % of revenue, monthly dynamics, net margin. Data from MoySklad. Whitelist: vg, fg.</span>
          <span data-lang="sk">Konsolidovaný P&amp;L: 5 právnických osôb, kategórie nákladov ako % z tržieb, mesačná dynamika. Whitelist: vg, fg.</span>
        </div>
        <div style="display:inline-flex;align-items:center;gap:8px;padding:9px 16px;background:var(--yellow);color:var(--black);font-weight:800;border-radius:6px;font-size:13px;letter-spacing:0.02em">
          <span data-lang="uk">Відкрити Finance</span><span data-lang="en">Open Finance</span><span data-lang="sk">Otvoriť Finance</span>
          <span style="font-size:16px">↗</span>
        </div>
        <div style="font-size:10px;color:rgba(255,255,255,0.4);font-style:italic;margin-top:10px">block: <code style="background:rgba(255,255,255,0.08);padding:1px 5px;border-radius:3px;color:var(--yellow)">finance-dashboard</code></div>
      </div>
    </a>
    <a href="dashboard/procurement/" target="_blank" rel="noopener" style="display:block;background:linear-gradient(135deg, #1E1E1E 0%, #2A2A2A 100%);color:#fff;padding:24px 22px;border-radius:var(--radius);text-decoration:none;position:relative;overflow:hidden;border:1px solid rgba(150,193,31,0.2)">
      <div style="position:absolute;top:-40px;right:-40px;width:160px;height:160px;border-radius:50%;background:radial-gradient(circle, rgba(150,193,31,0.13) 0%, transparent 70%);pointer-events:none"></div>
      <div style="position:relative">
        <div style="font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:var(--green);margin-bottom:8px">📦 Procurement / Planning</div>
        <div style="font-size:20px;font-weight:800;letter-spacing:-0.3px;line-height:1.2;margin-bottom:10px">
          <span data-lang="uk">Закупки сировини та прогноз залишків</span><span data-lang="en">Raw materials &amp; stock forecast</span><span data-lang="sk">Suroviny &amp; predpoveď zostatkov</span>
        </div>
        <div style="font-size:13px;line-height:1.55;color:rgba(255,255,255,0.78);margin-bottom:14px">
          <span data-lang="uk">Свіжий сир (кг) → сушений (вихід %), упаковка/гофра помісячно, готові пачки по смаках, прогноз днів до закінчення сировини. Whitelist: vg, fg.</span>
          <span data-lang="en">Fresh cheese (kg) → dried (yield %), packaging/cardboard monthly, finished packs by flavor, days-to-stockout forecast. Whitelist: vg, fg.</span>
          <span data-lang="sk">Čerstvý syr (kg) → sušený (výťažok %), obaly mesačne, hotové balenia podľa príchutí, predpoveď dní do vyčerpania. Whitelist: vg, fg.</span>
        </div>
        <div style="display:inline-flex;align-items:center;gap:8px;padding:9px 16px;background:var(--green);color:#fff;font-weight:800;border-radius:6px;font-size:13px;letter-spacing:0.02em">
          <span data-lang="uk">Відкрити Procurement</span><span data-lang="en">Open Procurement</span><span data-lang="sk">Otvoriť Procurement</span>
          <span style="font-size:16px">↗</span>
        </div>
        <div style="font-size:10px;color:rgba(255,255,255,0.4);font-style:italic;margin-top:10px">block: <code style="background:rgba(255,255,255,0.08);padding:1px 5px;border-radius:3px;color:var(--green)">procurement-dashboard</code></div>
      </div>
    </a>
  </div>
```

---

## 3. Видалити Finance з "Planned" секції

**Знайди** і **видали** цей блок (у "🟡 У плані"):

```html
<div class="card card-sm" style="opacity:0.85">
  <div style="font-size:24px;margin-bottom:6px">💰</div>
  <div style="font-size:14px;font-weight:800;margin-bottom:4px"><span data-lang="uk">Finance Dashboard</span>...
  …
  <div style="font-size:10px;color:var(--text-muted);font-style:italic">block: <code>finance-dashboard</code></div>
</div>
```

(Він тепер у Live секції.)

---

## Перевірка перед публікацією

- [ ] Card Finance посилається на `dashboard/finance/` (не `dashboard/finance/finance.html`)
- [ ] Card Procurement посилається на `dashboard/procurement/`
- [ ] KPI strip показує 5 live + 2 planned (були 3 live + 4+ planned)
- [ ] Finance видалено з "У плані"
- [ ] Procurement НЕ дублюється в "У плані" (його там не було — це новий)
- [ ] Inventory і Production картки не зачеплені
