# 🚀 Настройка Cloudflare Worker для приёма заявок

## Шаг 1: Получить токен Telegram бота

1. Найдите токен в файле `.env` (переменная `BOT_TOKEN`)
2. Или получите новый токен у [@BotFather](https://t.me/BotFather)

## Шаг 2: Создать Cloudflare Worker

### Вариант А: Через Cloudflare Dashboard

1. Зайдите на https://dash.cloudflare.com
2. Перейдите в **Workers & Pages** → **Create application**
3. Выберите **Create Worker**
4. Назовите Worker: `adspay-telegram`
5. Нажмите **Deploy**
6. Нажмите **Edit code**
7. Скопируйте код из `worker.js`
8. Нажмите **Save and deploy**
9. Перейдите в **Settings** → **Variables** и добавьте секрет `BOT_TOKEN` с вашим токеном

### Вариант Б: Через Wrangler CLI

```bash
# Установить Wrangler
npm install -g wrangler

# Логин в Cloudflare
wrangler login

# Добавить секрет с токеном бота
wrangler secret put BOT_TOKEN

# Деплой
wrangler deploy
```

## Шаг 3: Настроить Custom Domain (опционально)

1. В настройках Worker нажмите **Triggers**
2. Добавьте **Custom Domain**: `api.adspay.by` или `adspay-form.workers.dev`
3. Используйте этот URL в `index.html`

## Шаг 4: Обновить URL в index.html (если нужен другой домен)

Если вы хотите использовать другой URL Worker'а, найдите в `index.html` строки:

```javascript
const response = await fetch('https://adspay-telegram.belada-export.workers.dev', {
```

и замените URL на ваш:

```javascript
const response = await fetch('https://ВАШ-WORKER-URL', {
```

## Шаг 5: Протестировать

1. Откройте сайт
2. Заполните форму заявки
3. Отправьте
4. Проверьте, пришло ли сообщение в Telegram менеджеру (ID: 390197983)

## 🔧 Отладка

### Проверить логи Worker'а:

```bash
wrangler tail
```

### Или в Dashboard:
Workers & Pages → Ваш Worker → Logs

### Тестовый запрос через curl:

```bash
curl -X POST https://adspay-telegram.belada-export.workers.dev \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Тест",
    "telegram": "@test_user",
    "platforms": ["Meta Ads", "Google Ads"],
    "budget": "500-1500$",
    "comment": "Тестовая заявка",
    "source": "test"
  }'
```

## 📱 Формат уведомления в Telegram

```
📝 НОВАЯ ЗАЯВКА С САЙТА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 Имя: Иван Иванов
📱 Telegram: @ivan_ivanov
💼 Платформы: Meta Ads, Google Ads
💰 Бюджет: 500-1500$
💬 Комментарий: Нужна карта для рекламы

🌐 Источник: website_form
🕐 Время (Минск): 2026-02-22 15:30:45
```

## ⚠️ Важно

- **Не коммитьте BOT_TOKEN в репозиторий!**
- Используйте environment variables в Cloudflare (через Dashboard или `wrangler secret put BOT_TOKEN`)
- Для production настройте Custom Domain
- Включите rate limiting для защиты от спама

## 🔐 Использование Environment Variables (рекомендуется)

Worker читает токен из переменной окружения `env.BOT_TOKEN`.

Добавить секрет через CLI:

```bash
wrangler secret put BOT_TOKEN
```

Или через Dashboard: Workers & Pages → Ваш Worker → **Settings** → **Variables** → **Add variable** (тип: Secret).

## 🔗 Полезные ссылки

- [Cloudflare Workers Docs](https://developers.cloudflare.com/workers/)
- [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)
- [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/)
