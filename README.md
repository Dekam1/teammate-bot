# TeammateFind Bot 🎮

Telegram-бот для поиска тиммейтов с мини-приложением внутри Telegram.

## Стек
- **Bot**: Python + aiogram 3
- **Backend API**: FastAPI
- **Database**: PostgreSQL
- **Frontend**: HTML/JS (Telegram Mini App)
- **Хостинг**: Railway / Render (бесплатно на старте)

## Функции
- Регистрация с выбором игр, ролей, рангов
- Загрузка фото анкеты
- Свайп-интерфейс (как Tinder) внутри Telegram
- Матчинг при взаимном лайке
- Уведомление о матче в бот
- Фильтры по игре и полу
- Система Premium подписки

## Запуск

### 1. Создай бота
1. Напиши @BotFather в Telegram
2. `/newbot` → дай имя → получи токен
3. `/setmenubutton` → укажи URL твоего webapp

### 2. База данных
```bash
# Локально (PostgreSQL должен быть установлен)
createdb teammate_bot
psql teammate_bot < database/schema.sql
```

### 3. Настрой переменные
```bash
cp .env.example .env
# Отредактируй .env — вставь токен бота и URL базы
```

### 4. Установи зависимости
```bash
pip install -r requirements.txt
```

### 5. Запуск
```bash
# В одном терминале — бот
cd bot && python main.py

# В другом — веб-сервер
uvicorn server:app --reload
```

## Деплой на Railway (бесплатно)

1. Зарегистрируйся на railway.app
2. Создай новый проект → Deploy from GitHub
3. Добавь PostgreSQL плагин
4. В Environment Variables добавь BOT_TOKEN и DATABASE_URL
5. Railway автоматически даст тебе URL — вставь его в WEBAPP_URL

## Монетизация
- 10 лайков/день бесплатно
- Premium 99₽/мес: безлимит лайков, кто лайкнул, буст, фильтры
- Подключи ЮKassa или Telegram Stars для оплаты

## Структура проекта
```
teammate_bot/
├── bot/
│   ├── main.py          # Telegram бот (aiogram)
│   └── db.py            # Работа с базой данных
├── webapp/
│   └── index.html       # Telegram Mini App (свайп-интерфейс)
├── database/
│   └── schema.sql       # SQL схема
├── server.py            # FastAPI сервер
├── requirements.txt
└── .env.example
```
