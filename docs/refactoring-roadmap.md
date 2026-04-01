# Refactoring Roadmap

## Goal
Move the EGD parser from a growing set of document-specific patches to a layered,
layout-driven architecture that stays stable on larger unseen corpora.

## Target layers
1. OCR and geometry
2. Layout variant detection
3. Table grid inference
4. Cell extraction
5. Semantic normalization
6. Validation and confidence scoring

## Introduced in this step
- rule registries in `src/egd_parser/domain/reference/rules/`
- registry loader in `src/egd_parser/pipeline/normalize/rule_registry.py`
- page-2 variant detector in `src/egd_parser/pipeline/layout/variant_detector.py`
- residents table grid inference in `src/egd_parser/pipeline/layout/table_grid.py`
- confidence helpers in `src/egd_parser/pipeline/validate/confidence.py`

## Migration plan
1. Keep the current parser as the baseline.
2. Move exact replacements and overrides from code into rule registries.
3. Route page-2 resident parsing through `variant_detector + table_grid`.
4. Split current passport and previous identity document into separate extracted cells.
5. Add field-level confidence and regression checks for the full corpus.

## Immediate next code moves
- migrate remaining hardcoded passport/name/document replacements into registries
- split `page2.py` into `page2_residents.py` and `page2_benefits.py`
- move adaptive column logic out of `page2.py` into `table_grid.py`
- add golden regression fixtures for all parsed corpus files
