#!/usr/bin/env bash
# snEco · One-time onboarding script для Пилипа (fg@abrisart.com)
# Запуск: bash setup-pylyp.sh
#
# Що робить:
#   1. Перевіряє наявність git, python3, node — встановлює якщо немає (через brew)
#   2. Клонує/оновлює sneco-brand-book repo
#   3. Створює venv + ставить Python deps
#   4. Перевіряє git config + GitHub auth
#   5. Створює локальний .env (без секретів — заповниш сам)
#   6. Друкує наступні кроки

set -e

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
RESET='\033[0m'

echo -e "${YELLOW}╔═══════════════════════════════════════════════════════════════╗"
echo -e "║  snEco · Pylyp Onboarding (Claude Cowork collaboration)        ║"
echo -e "╚═══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

# 1. Pre-requisites check
echo -e "${YELLOW}[1/6]${RESET} Перевіряю pre-requisites..."
MISSING=()
command -v git    >/dev/null 2>&1 || MISSING+=("git")
command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
command -v node   >/dev/null 2>&1 || MISSING+=("node")
command -v gh     >/dev/null 2>&1 || MISSING+=("gh (GitHub CLI)")

if [ ${#MISSING[@]} -gt 0 ]; then
  echo -e "${RED}❌ Бракує: ${MISSING[@]}${RESET}"
  echo ""
  echo -e "Встанови через Homebrew:"
  echo -e "  ${YELLOW}brew install git python@3.11 node gh${RESET}"
  echo ""
  echo -e "Якщо немає brew → https://brew.sh"
  exit 1
fi
echo -e "${GREEN}✓ git, python3, node, gh — на місці${RESET}"
echo ""

# 2. Clone repo
WORKDIR="$HOME/snEco-brand-book"
echo -e "${YELLOW}[2/6]${RESET} Клоную/оновлюю repo у ${WORKDIR}..."
if [ -d "$WORKDIR/.git" ]; then
  cd "$WORKDIR"
  git pull origin main
  echo -e "${GREEN}✓ Repo оновлений${RESET}"
else
  git clone https://github.com/dreamcarua/sneco-brand-book.git "$WORKDIR"
  cd "$WORKDIR"
  echo -e "${GREEN}✓ Repo склонований у ${WORKDIR}${RESET}"
fi
echo ""

# 3. Python venv + deps
echo -e "${YELLOW}[3/6]${RESET} Створюю Python venv..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install --quiet requests pandas openpyxl python-dotenv
echo -e "${GREEN}✓ Python deps встановлено у .venv${RESET}"
echo ""

# 4. GitHub auth check
echo -e "${YELLOW}[4/6]${RESET} Перевіряю GitHub authentication..."
if gh auth status >/dev/null 2>&1; then
  echo -e "${GREEN}✓ GitHub authenticated:${RESET}"
  gh auth status 2>&1 | grep -E "Logged in|account"
else
  echo -e "${YELLOW}⚠ GitHub не authenticated. Запусти:${RESET}"
  echo -e "  ${YELLOW}gh auth login${RESET}  (вибери GitHub.com → HTTPS → Login with browser)"
fi
echo ""

# 5. Git config check
echo -e "${YELLOW}[5/6]${RESET} Перевіряю git config..."
GIT_NAME=$(git config user.name || echo "")
GIT_EMAIL=$(git config user.email || echo "")
if [ -z "$GIT_NAME" ] || [ -z "$GIT_EMAIL" ]; then
  echo -e "${YELLOW}⚠ Git user.name/email не налаштовано. Запусти:${RESET}"
  echo -e "  ${YELLOW}git config --global user.name \"Pylyp Gryshyn\"${RESET}"
  echo -e "  ${YELLOW}git config --global user.email \"fg@abrisart.com\"${RESET}"
else
  echo -e "${GREEN}✓ Git: ${GIT_NAME} <${GIT_EMAIL}>${RESET}"
fi
echo ""

# 6. .env template (without secrets)
echo -e "${YELLOW}[6/6]${RESET} Створюю .env шаблон..."
if [ ! -f ".env" ]; then
  cat > .env <<'EOF'
# === snEco · Pylyp local env ===
# ⚠ НЕ commit'ити цей файл у git (він у .gitignore)

# Спільний MoySklad токен (попроси у Vadym)
MOYSKLAD_TOKEN=

# Спільний URL Worker (вже встановлено)
WORKER_URL=https://sneco-auth.vg-ab6.workers.dev

# Спільний sync API key (попроси у Vadym після того як він додасть твій dashboard у Worker)
SYNC_API_KEY=

# Твій email
SNECO_EMAIL=fg@abrisart.com
EOF
  echo -e "${GREEN}✓ Створено .env (заповни секрети — попроси у Vadym)${RESET}"
else
  echo -e "${GREEN}✓ .env вже існує${RESET}"
fi
echo ""

# Final
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗"
echo -e "║                    ✓ Setup complete                            ║"
echo -e "╚═══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "${YELLOW}Що далі:${RESET}"
echo -e "  1. Заповни ${YELLOW}~/snEco-brand-book/.env${RESET} секретами від Vadym"
echo -e "  2. Прочитай ${YELLOW}~/snEco-brand-book/PYLYP_ONBOARDING.md${RESET} (повний context для твого Claude)"
echo -e "  3. Прочитай ${YELLOW}~/snEco-brand-book/CLAUDE.md${RESET} (загальний context snEco)"
echo -e "  4. У Cowork: відкрий папку ${YELLOW}~/snEco-brand-book/${RESET} як workspace"
echo -e "  5. Скажи Claude: ${YELLOW}\"Прочитай PYLYP_ONBOARDING.md і скажи що зрозумів\"${RESET}"
echo ""
echo -e "${GREEN}Welcome to snEco · v2.52${RESET}"
