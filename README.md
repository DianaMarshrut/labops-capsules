# Капсулы labopsai

Бесплатные готовые навыки для ИИ, которые руководитель малого и среднего бизнеса ставит себе
сам — в Claude, ChatGPT или DeepSeek.

| Капсула | Что делает | Статус |
|---|---|---|
| «Пульс» (`puls`) | Дашборд руководителя: главные цифры компании на одной странице | Готова |
| «След» (`sled`) | Встреча → протокол → задачи | Скоро |
| «Радар» (`radar`) | Утренняя сводка руководителю | Скоро |

Все капсулы бесплатные. Лицензия — MIT (см. `LICENSE`).

# Пульс — дашборд руководителя по ссылке

Собирает главные цифры компании на одной странице: продажи, закупки, склад,
производство, финансы. Страницу можно открыть в браузере и переслать ссылкой или файлом.

## Что делает

1. Спрашивает, где лежат твои цифры: Битрикс24, amoCRM, МойСклад, таблицы, 1С.
2. Ведёт по подключению — по шагам, только с правами на чтение. Если в твоём чате есть встроенный
   коннектор (готовое подключение, например к Google Таблицам) — предлагает его первым.
   Для 1С и систем без подключения — через выгрузку отчёта в Excel.
3. Помогает выбрать 3–7 главных цифр или предлагает готовый набор.
4. Собирает дашборд — HTML-страницу, которая открывается и на компьютере, и на телефоне.
5. Отдаёт ссылкой (Claude, ChatGPT) или файлом.
6. Обновляет по фразе «обнови пульс».

## Что в репозитории

| Путь | Для чего |
|---|---|
| `plugins/puls/skills/puls/` | Сам навык: `SKILL.md`, справочники `references/`, шаблон `templates/dashboard.html` |
| `dist/puls.zip` | Тот же навык в архиве — для загрузки в Claude (claude.ai и приложение) |
| `chat-instruction.md` | Весь навык одним текстом — для ChatGPT, DeepSeek и других чатов |
| `.claude-plugin/marketplace.json` | Каталог плагинов для Claude Code |
| `scripts/build.py` | Пересобирает `dist/puls.zip` и `chat-instruction.md` после правок навыка |
| `tests/` | Проверка шаблона на тестовой Excel-выгрузке и скриншоты |

## Как поставить

### Claude Code

Claude Code — программа для работы с Claude в терминале компьютера. В Claude Code набери:

```
/plugin marketplace add DianaMarshrut/labops-capsules
/plugin install puls@labopsai-capsules
```

В Claude Code 2.1.275 и новее можно одной командой:

```
/plugin install puls --marketplace DianaMarshrut/labops-capsules
```

Если репозиторий скачан на компьютер, вместо `DianaMarshrut/labops-capsules` укажи путь
к папке, например `/plugin marketplace add ~/labops-capsules`.

То же из обычного терминала:

```
claude plugin marketplace add DianaMarshrut/labops-capsules
claude plugin install puls@labopsai-capsules
```

### Claude (claude.ai и приложение)

Навыки есть на всех тарифах: Free, Pro, Max, Team, Enterprise.

1. Включи запуск кода: «Settings» → «Capabilities» → «Code execution and file creation».
   На тарифах Team и Enterprise это и сами навыки сначала включает владелец организации:
   «Organization settings» → «Plugins & skills» → вкладка «Policy».
2. Скачай `dist/puls.zip` из этого репозитория. Распаковывать не нужно.
3. «Customize» → «Skills» → «+» → «+ Create skill» → «Upload a skill» → выбери `puls.zip`.
4. Проверь, что навык «puls» включён в списке «Customize» → «Skills».
5. В новом чате напиши: «Хочу дашборд по продажам».

### ChatGPT, DeepSeek и другие чаты

1. Открой `chat-instruction.md` и скопируй весь текст.
2. Вставь его первым сообщением в новый чат (или приложи файл `chat-instruction.md` и напиши
   «Работай по этой инструкции»). В ChatGPT можно создать проект и положить инструкцию
   в его файлы — тогда не придётся вставлять каждый раз.
3. Загрузи Excel-выгрузку и напиши: «Собери пульс».

Источники по установке (проверено 27.10.2026): плагины Claude Code —
https://code.claude.com/docs/en/plugins ; навыки в Claude —
https://support.claude.com/en/articles/12512180-use-skills-in-claude и
https://support.claude.com/en/articles/12512198-how-to-create-custom-skills .

## Безопасность

- Для ИИ — отдельный пользователь или ключ, права только на чтение и только к нужным разделам.
- Если система не умеет давать ключ только на чтение (например, amoCRM) — работаем через
  Excel-выгрузку.
- Публичную ссылку на дашборд видит любой, у кого она есть. Не пересылай её за пределы компании.

## Что дальше

Гайды с примерами — в базе знаний «Лаборатория ИИ»: https://guides.labopsai.pro
Не хочешь настраивать сам — «Свой ИИ-сотрудник» живёт в Telegram и подключается к твоим
таблицам, почте и CRM: labopsai.pro.

## Для разработчика

После правок в `plugins/puls/skills/puls/` пересобери архив и инструкцию для чатов:

Нужен Python 3.10 или новее.

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python3 scripts/build.py
python3 -m pytest tests -q
python3 tests/make_sample_xlsx.py && python3 tests/build_sample_dashboard.py
python3 tests/build_edge_dashboard.py
```

`scripts/build.py` пишет `dist/puls.zip` и рядом `dist/puls.zip.txt` — список файлов архива
и контрольную сумму SHA-256.
