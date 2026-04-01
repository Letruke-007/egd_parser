# Architecture

Сервис разделен на уровни:

- `api`: HTTP-контракт и сериализация.
- `application`: use-case сценарии.
- `domain`: модели, value objects, интерфейсы портов.
- `infrastructure`: конкретные реализации OCR/PDF/settings/logging.
- `pipeline`: пошаговая обработка документа.

Цель такого разделения: развивать распознавание независимо от web-слоя.
