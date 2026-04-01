# EGD Parser Service

Микросервис для OCR-разбора ЕЖД (единых жилищных документов) из PDF в структурированный JSON.

Сервис работает как:
- синхронный API для разбора одного PDF;
- асинхронный job API для пакетной обработки нескольких файлов;
- FastAPI-приложение с файловым storage, SQLite-метаданными и Docker-сборкой.

## Что внутри

- `FastAPI` API
- OCR на `PaddleOCR` с локальными моделями
- рендер PDF через `Poppler`
- pipeline: `render -> OCR -> layout -> extract -> normalize -> validate`
- page-specific extractors для `page_1` и `page_2`
- поддержка continuation-страниц таблицы зарегистрированных лиц
- low-confidence `row re-OCR fallback` для сложных строк
- SQLite-хранилище job-метаданных
- загрузка и хранение исходных PDF на диске

Основные принципы:
- layout-based parsing таблиц
- template-based parsing документов в ячейках (`паспорт`, `свидетельство о рождении`, `справка`)
- grammar-based normalizers для органов выдачи
- confidence/trace внутри `metadata`

## Структура проекта

- [src/egd_parser/api/app.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/api/app.py) — создание FastAPI приложения
- [src/egd_parser/api/routes/parse.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/api/routes/parse.py) — синхронный разбор одного файла
- [src/egd_parser/api/routes/jobs.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/api/routes/jobs.py) — job API
- [src/egd_parser/application/services/job_service.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/application/services/job_service.py) — фоновая обработка файлов
- [src/egd_parser/pipeline/runner.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/pipeline/runner.py) — основной pipeline
- [src/egd_parser/infrastructure/pdf/poppler_renderer.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/infrastructure/pdf/poppler_renderer.py) — рендер PDF
- [src/egd_parser/infrastructure/ocr/paddleocr_engine.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/infrastructure/ocr/paddleocr_engine.py) — OCR-движок
- [src/egd_parser/infrastructure/storage/sqlite_job_store.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/infrastructure/storage/sqlite_job_store.py) — SQLite storage
- [src/egd_parser/infrastructure/storage/upload_store.py](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/src/egd_parser/infrastructure/storage/upload_store.py) — файловое storage

## API

Базовый healthcheck:

- `GET /health`

Синхронный разбор:

- `POST /api/v1/parse`
- multipart field: `file`

Асинхронные jobs:

- `POST /api/v1/jobs` — создать job из одного или нескольких PDF
- `GET /api/v1/jobs` — список jobs
- `GET /api/v1/jobs/{job_id}` — статус job
- `GET /api/v1/jobs/{job_id}/results` — результаты job
- `GET /api/v1/jobs/{job_id}/files` — список загруженных файлов job
- `GET /api/v1/jobs/{job_id}/files/{file_index}` — скачать исходный загруженный файл
- `DELETE /api/v1/jobs/cleanup` — удалить старые jobs и их файлы

Swagger:

- `/docs`
- `/redoc`

Служебные endpoint'ы:

- `GET /health` — расширенный healthcheck
- `GET /metrics` — JSON-метрики по jobs и runtime

## Локальный запуск

### 1. Создать окружение

```bash
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/pip install -e .[dev]
```

### 2. Установить OCR-зависимости

```bash
.venv/bin/pip install paddlepaddle==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.venv/bin/pip install paddleocr
```

Нужен установленный `pdftoppm` из `poppler-utils`.

### 3. Положить локальные модели PaddleOCR

По умолчанию сервис ожидает модели в:

- `.venv/paddleocr-models/models/PP-OCRv5_mobile_det_infer`
- `.venv/paddleocr-models/models/cyrillic_PP-OCRv5_mobile_rec_infer`
- `.venv/paddleocr-models/models/PP-LCNet_x0_25_textline_ori_infer`

### 4. Запустить приложение

```bash
uvicorn egd_parser.api.app:app --host 0.0.0.0 --port 8000 --reload
```

## Примеры запросов

Разобрать один PDF:

```bash
curl -X POST \
  -F "file=@/path/to/document.pdf" \
  http://localhost:8000/api/v1/parse
```

Создать job из нескольких файлов:

```bash
curl -X POST \
  -F "files=@/path/to/1.pdf" \
  -F "files=@/path/to/2.pdf" \
  http://localhost:8000/api/v1/jobs
```

Проверить статус job:

```bash
curl http://localhost:8000/api/v1/jobs/<job_id>
```

Получить результаты job:

```bash
curl http://localhost:8000/api/v1/jobs/<job_id>/results
```

## Структура выходного JSON

Синхронный `POST /api/v1/parse` возвращает объект:

```json
{
  "filename": "document.pdf",
  "status": "accepted",
  "pages": 3,
  "warnings": [],
  "extracted_data": {
    "document_type": "egd",
    "page_1": { "...": "..." },
    "page_2": { "...": "..." }
  },
  "metadata": {
    "ocr_engine": "paddleocr",
    "page_images": [],
    "ocr_preview": {},
    "extraction_trace": {}
  }
}
```

В job-режиме `GET /api/v1/jobs/{job_id}/results` возвращает список файлов, и у каждого файла структура `extracted_data` и `metadata` такая же.

### `extracted_data`

Верхний уровень:

- `document_type` — тип документа, всегда `egd`
- `page_1` — данные первой страницы
- `page_2` — данные о зарегистрированных лицах и льготах

### `page_1`

Поля:

- `document_date` — дата ЕЖД в формате `ДД.ММ.ГГГГ`
- `administrative_okrug` — административный округ
- `district` — район
- `passport` — паспорт заявителя или основного субъекта документа
- `property_address` — адрес объекта
- `management_company` — управляющая компания
- `settlement_type` — вид заселения или права
- `owners` — список собственников
- `primary_tenant` — основной наниматель, если документ не по собственности
- `ownership_documents` — список правоустанавливающих документов

Структура `page_1.passport`:

- `document_type` — обычно `паспорт`
- `series` — серия документа
- `number` — номер документа
- `issued_by` — орган выдачи
- `issue_date` — дата выдачи
- `raw` — канонически собранная строка документа

Структура `page_1.property_address`:

- `street` — улица
- `house` — дом
- `building` — корпус
- `structure` — строение
- `apartment` — квартира
- `full` — собранный адрес одной строкой

Структура `page_1.management_company`:

- `name` — название управляющей компании

Элемент `page_1.owners[]`:

- `full_name` — ФИО собственника
- `ownership_share` — доля собственности строкой, например `50.00` или `100.00`

Элемент `page_1.ownership_documents[]`:

- строка с нормализованным названием и реквизитами документа-основания

### `page_2`

Поля:

- `registered_persons_constantly` — постоянно зарегистрированные лица
- `registered_persons_temporary` — временно зарегистрированные лица
- `benefits` — льготы (`нет` или извлеченное значение)

Структура `page_2.registered_persons_constantly`:

- `count` — количество лиц
- `persons` — список зарегистрированных лиц

Структура `page_2.registered_persons_temporary`:

- `count` — количество лиц
- `persons` — список зарегистрированных лиц

Элемент `page_2.registered_persons_constantly.persons[]` и `page_2.registered_persons_temporary.persons[]`:

- `full_name` — ФИО
- `birthday_date` — дата рождения
- `passport` — текущий документ, удостоверяющий личность
- `departure` — сведения о выбытии по правому столбцу таблицы

Важно:

- формат `person` фиксированный и одинаковый для всех документов
- ключи `passport` и `departure` возвращаются всегда
- если данных нет, соответствующие значения будут `null`

Структура `person.passport` фиксированная для всех типов документов.

Поля:

- `document_type`
- `series`
- `number`
- `issued_by`
- `issue_date`
- `raw`

Замечания:

- для `паспорт` обычно заполнены все поля
- для `свидетельство о рождении` поле `series` может быть `null` для нестандартных или иностранных документов
- для `справка` часть полей может быть `null`, если их нет в исходном документе

### `person.departure`

Структура `person.departure` тоже фиксированная и возвращается всегда.

Поля:

- `status` — статус выбытия, сейчас `departed`
- `reason` — тип выбытия:
  - `death`
  - `form_6_stub`
  - `other`
- `raw` — нормализованная строка выбытия
- `death_date` — дата смерти
- `departure_date` — дата выбытия
- `act_record_number` — номер актовой записи
- `act_record_date` — дата актовой записи
- `issued_by` — орган регистрации или ЗАГС
- `destination_address` — адрес выбытия
- `validation` — результат мягкой проверки номера актовой записи

Если выбытия нет:

- все поля `departure`, включая `validation`, возвращаются с `null`

Структура `departure.validation`:

- `scheme` — использованная схема проверки:
  - `egr_zags_2018`
  - `pre_egr_local_record`
  - `unknown`
- `applicable` — применима ли формальная проверка
- `passed` — прошла ли проверка, если она применима

### `metadata`

Служебный блок для диагностики и отладки:

- `ocr_engine` — использованный OCR-движок
- `page_images` — пути к временным изображениям страниц
- `ocr_preview` — укороченный OCR-текст по страницам
- `extraction_trace` — внутренний trace извлечения и confidence по ключевым полям

## Куда возвращается результат обработки

Есть два режима.

Синхронный:
- `POST /api/v1/parse`
- результат возвращается сразу в HTTP-ответе в поле `extracted_data`

Асинхронный:
- `POST /api/v1/jobs`
- сервис создает `job_id`
- результат потом возвращается через `GET /api/v1/jobs/{job_id}/results`

Что хранится физически:
- исходные загруженные PDF сохраняются в `UPLOADS_DIR`
- метаданные jobs и результаты разбора файлов сохраняются в SQLite по пути `JOBS_DB_PATH`
- временные PNG рендеров страниц сохраняются в `RENDERED_PAGES_DIR`

Важно:
- сейчас итоговый JSON результата хранится не отдельным файлом, а в SQLite в составе job-результата
- для одиночного `POST /parse` результат на диск не сохраняется, а отдается сразу в ответе

## Docker

### Сборка

```bash
docker build -t egd-parser-service:latest .
```

### Запуск

```bash
docker run --rm -p 8000:8000 \
  -e APP_ENV=prod \
  -e LOG_LEVEL=INFO \
  -e OCR_ENGINE=paddleocr \
  -e JOBS_DB_PATH=/data/jobs.sqlite3 \
  -e UPLOADS_DIR=/data/uploads \
  -v $(pwd)/data:/data \
  -v $(pwd)/models:/models \
  egd-parser-service:latest
```

Ожидается, что локальные модели PaddleOCR будут лежать в примонтированном каталоге:

- `./models/models/PP-OCRv5_mobile_det_infer`
- `./models/models/cyrillic_PP-OCRv5_mobile_rec_infer`
- `./models/models/PP-LCNet_x0_25_textline_ori_infer`

## Переменные окружения

Основные:

- `APP_ENV` — окружение (`dev`, `prod`)
- `APP_HOST` — bind host
- `APP_PORT` — bind port
- `API_PREFIX` — префикс API, по умолчанию `/api/v1`
- `LOG_LEVEL` — уровень логирования
- `OCR_ENGINE` — OCR-движок, по умолчанию `paddleocr`
- `PDF_RENDER_DPI` — DPI для рендера PDF

Storage:

- `JOBS_DB_PATH` — путь к SQLite базе jobs
- `UPLOADS_DIR` — директория хранения загруженных PDF
- `JOBS_RETENTION_DAYS` — retention для cleanup jobs
- `JOB_WORKER_THREADS` — число потоков для параллельного разбора файлов внутри одного job
- `RENDERED_PAGES_DIR` — директория временных PNG рендеров страниц
- `RENDERED_PAGES_RETENTION_HOURS` — сколько хранить временные рендеры

PaddleOCR:

- `PADDLEOCR_LANGUAGE`
- `PADDLEOCR_USE_ANGLE_CLS`
- `PADDLEOCR_BASE_DIR`
- `PADDLEOCR_DET_MODEL_NAME`
- `PADDLEOCR_REC_MODEL_NAME`
- `PADDLEOCR_TEXTLINE_ORIENTATION_MODEL_NAME`
- `PADDLEOCR_DET_MODEL_DIR`
- `PADDLEOCR_REC_MODEL_DIR`
- `PADDLEOCR_TEXTLINE_ORIENTATION_MODEL_DIR`

Актуальный пример env лежит в [.env.example](/home/anton/0.%20dev/src/DM/00.%20Code/микросервис%20парсинга%20ЕЖД/.env.example).

## Хранение данных

Во время работы сервис пишет:

- SQLite job-метаданные
- загруженные PDF для jobs
- временные рендеры страниц в `tmp/rendered_pages`

Именно здесь лежит полезная бизнес-информация:

- JSON результата job хранится внутри SQLite по `JOBS_DB_PATH`
- исходники лежат в `UPLOADS_DIR`

## Ограничения

- OCR CPU-bound, поэтому throughput зависит от размера PDF и CPU контейнера
- для высокого качества нужны локальные модели PaddleOCR и `poppler-utils`
