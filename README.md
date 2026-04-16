# crt-bot

Telegram-бот для **предсказаний «на рабочую неделю»** в **чате обсуждения канала**: пользователь **упоминает бота** в комментарии под постом с заданным **хештег-триггером** (по умолчанию `#predict_week`). Ответ — текст (опционально через локальную LLM) и случайная картинка из `assets/images` (подпись к фото, не текст на изображении).

## Требования

- Python 3.10+
- Токен бота от [@BotFather](https://t.me/BotFather)
- Опционально: [Redis](https://redis.io/) для кэша тредов (иначе кэш только в памяти процесса)

## Установка

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Скопируйте `.env.example` в `.env` и заполните переменные.

### Разработка: тесты и линтер

```bash
pip install -r requirements-dev.txt
# из корня репозитория (где лежит папка bot/):
pytest
# или из tests/: python test_image_moderation.py — подхватит корень и pytest
ruff check bot tests scripts
```

Проверка картинок в `assets/images` теми же правилами, что при отправке (учитывается `.env`: Sightengine, SAFE_IMAGE и т.д.):

```bash
python scripts/validate_assets.py
```

## Docker

Из корня репозитория (нужен заполненный `.env` с `BOT_TOKEN` и `ADMIN_USER_IDS`):

```bash
docker compose up --build -d
```

Поднимаются **Redis** (AOF на диск) и **бот**; в контейнер пробрасывается `REDIS_URL=redis://redis:6379/0`. База SQLite и логи — в volume `bot_data`.

## Настройка (кратко)

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Обязательно. |
| `ADMIN_USER_IDS` | id админов через запятую. |
| `WHITELIST_CHAT_IDS` | Начальный whitelist группы обсуждения (не id канала). |
| `RATE_LIMIT_SECONDS` | Стартовый интервал между предсказаниями одному пользователю (сек.), по умолчанию **3600** (1 час). Меняется в рантайме: `/set_rate_limit`. |
| `REDIS_URL` | Если задан — кэш зеркал постов по тредам в **Redis** (персистентно при настроенном Redis); если пусто — только **in-memory** процесса. В `docker compose` для бота URL задаётся автоматически. |
| `IMAGE_VALIDATION_ENABLED` | Проверка размера/разрешения и опционально HTTP-модерация. |
| `SAFE_IMAGE_URL` | POST `multipart/form-data` с полем `image`; ответ JSON `{"safe": true}` или `{"ok": true}`. Пусто — только проверки через Pillow. |
| `LOCAL_LLM_MAX_OUTPUT_CHARS` | Начальный лимит символов ответа LLM (при первом создании БД); дальше **`/set_llm_max_chars`**. |

Полный список — в `.env.example`.

### Whitelist и чат комментариев

У канала и у **группы обсуждения** разные `chat_id`. Надёжно: **`/add_whitelist`** в нужной группе (админ) или **`/chat_id`** там же для проверки.

## Запуск без Docker

```bash
python run_bot.py
```

## Поведение

1. Обсуждение канала включено, бот в группе с правами читать сообщения и отвечать.
2. В посте есть триггер-хештег (**целое слово**: `#predict_week` не сработает внутри `#predict_weekly`).
3. В комментарии пользователь **упоминает** бота.

В группах с **темами** комментарий в теме поста или ответ на копию поста; кэш зеркала канала обновляется при сообщениях от имени канала (`sender_chat`).

## Команды админа

В **личке с ботом** после `/start` или `/help_admin` показывается **нижняя клавиатура** с частыми командами; у поля ввода — расширенное **меню «/»** (список команд задаётся для каждого id из `ADMIN_USER_IDS`). Скрыть кнопки: **`/hide_keyboard`**.

| Команда | Действие |
|---------|----------|
| `/set_rate_limit <сек>` | Интервал между предсказаниями для одного пользователя (границы как в коде / `.env`). Без аргумента — текущее значение. |
| `/set_llm_max_chars <n>` | Лимит символов в ответе локальной LLM. Без аргумента — текущее. Хранится в SQLite. |
| `/status` | В т.ч. `rate_limit_sec`, `llm_max_output_chars`, hashtag, whitelist. |
| `/add_whitelist`, `/remove_whitelist`, `/list_whitelist`, `/chat_id` | Whitelist. |
| `/set_hashtag`, `/get_hashtag` | Триггер в тексте поста. |
| `/bot_on`, `/bot_off` | Включение ответов. |
| `/hide_keyboard` | Убрать нижнюю клавиатуру в личке (снова: `/start` или `/help_admin`). |

## Модерация текста предсказания

При **`TEXT_MODERATION_ENABLED=1`** перед отправкой проверяется итоговый текст:

- По умолчанию включена эвристика **`TEXT_MODERATION_RU_MAT`** (типичные корни и формы русского мата, в т.ч. «схуяли»); отключение: **`TEXT_MODERATION_RU_MAT=0`**.
- **`TEXT_MODERATION_MODE=regex`** — подстроки из **`TEXT_BLOCKLIST`** (через запятую, без учёта регистра).
- **`llm`** — второй короткий запрос к **той же** локальной LLM (`LOCAL_LLM_*`): модель отвечает только JSON `{"ok":true}` / `{"ok":false}`.
- **`both`** — сначала блоклист, затем LLM.

Если проверка не проходит — пользователю уходит **запасной шаблон** из `prediction.py` (не повторный вызов генерации). При недоступности LLM в режиме только `llm` текст не блокируется из‑за сети (в лог — предупреждение).

## Картинки и модерация

Файлы `.png` / `.jpg` в `assets/images/`. При **`IMAGE_VALIDATION_ENABLED=1`** проверяются декодирование и лимиты размера/разрешения.

**Внешняя модерация** (`IMAGE_MODERATION_PROVIDER`, по умолчанию **`auto`**):

1. **Sightengine** — если заданы **`SIGHTENGINE_API_USER`** и **`SIGHTENGINE_API_SECRET`** (регистрация: [sightengine.com](https://sightengine.com/)). Запрос к `https://api.sightengine.com/1.0/check.json`, модели по умолчанию **`nudity-2.1`**. Пороги обнажённости: **`SIGHTENGINE_MAX_RAW`**, **`SIGHTENGINE_MAX_SEXUAL`**. По умолчанию **`SIGHTENGINE_MODERATE_SEVERE=1`**: в запрос подмешиваются **`gore-2.0`**, **`self-harm`**, **`recreational_drug`** ([кровь и ужасное содержимое](https://sightengine.com/docs/gore-disgusting-horrific-content-detection), [самоповреждение](https://sightengine.com/docs/self-harm-detection-model), [наркотики](https://sightengine.com/docs/drug-detection)); пороги **`SIGHTENGINE_MAX_GORE_PROB`**, **`SIGHTENGINE_MAX_SELF_HARM_PROB`**, **`SIGHTENGINE_MAX_RECREATIONAL_DRUG_PROB`** при включённом флаге по умолчанию **0.5** (выше `prob` в ответе — картинка не отправляется). Отключить блок: **`SIGHTENGINE_MODERATE_SEVERE=0`**. Алкоголь и табак — только если указаны в **`SIGHTENGINE_MODELS`**, пороги **`SIGHTENGINE_MAX_ALCOHOL_PROB`**, **`SIGHTENGINE_MAX_TOBACCO_PROB`**. **Текст и мат на изображении** (в т.ч. подписи на мемах): в **`SIGHTENGINE_MODELS`** добавьте **`text-content-2.0`**, задайте **`SIGHTENGINE_TEXT_CATEGORIES`** (см. [документацию OCR-текста](https://sightengine.com/docs/ocr-text-moderation-in-images-2.0)). Если **`SIGHTENGINE_OPT_LANG`** не задан, при включённой текстовой модерации подставляется **`ru`**. К запросу по умолчанию добавляется **`ocr`**, чтобы в ответе был сырой **`text.content`** и поверх него сработала та же русская эвристика, даже если категории Sightengine не пометили фразу (отключить: **`SIGHTENGINE_APPEND_OCR=0`**). При непустом **`text.detected_categories`** картинка по-прежнему отклоняется по правилам API. Опционально **`SIGHTENGINE_IMAGE_TEXT_REJECT_ONLY`**. Подробности в `.env.example`.
2. **Свой URL** — если Sightengine не настроен, но задан **`SAFE_IMAGE_URL`**: POST с полем `image`, в ответе JSON `{"safe": true}` или `{"ok": true}`.

Явно отключить внешнюю проверку: **`IMAGE_MODERATION_PROVIDER=none`**. При отказе модерации бот отправляет только текст предсказания.

## Локальная LLM

См. `.env.example`: `LOCAL_LLM_*`, бэкенды `openai` (OpenAI-compatible) и `ollama`.

## Структура проекта

```
crt-bot/
  run_bot.py
  bot/
    main.py                 # polling, post_init/post_shutdown (Redis)
    handlers.py             # админ-команды
    group_mention_flow.py   # упоминание бота, проверки, ответ
    text_moderation.py      # блоклист + LLM + эвристика русского мата
    russian_mat_filter.py   # подстроки для рус. мата (текст и OCR Sightengine)
    discussion_cache.py     # протокол + in-memory store
    redis_discussion_cache.py
    hashtag.py              # сопоставление триггера с текстом
    image_moderation.py     # проверка байтов картинки + опциональный HTTP
    storage.py              # SQLite
    config.py
    prediction.py
    local_llm.py
  tests/
  assets/images/
  data/
```

## Лицензия

Проект без указанной лицензии — используйте на свой страх и риск.
