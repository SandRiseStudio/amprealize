#!/bin/bash
# Export module files for migration
cd /Users/nick/amprealize
OUTPUT="module_migration_export.txt"
> "$OUTPUT"

FILES=(
  "amprealize/research/__init__.py"
  "amprealize/research/codebase_analyzer.py"
  "amprealize/research/prompts.py"
  "amprealize/research/report.py"
  "amprealize/research/ingesters/__init__.py"
  "amprealize/research/ingesters/base.py"
  "amprealize/research/ingesters/markdown_ingester.py"
  "amprealize/research/ingesters/pdf_ingester.py"
  "amprealize/research/ingesters/url_ingester.py"
  "amprealize/crypto/__init__.py"
  "amprealize/crypto/signing.py"
  "amprealize/billing/__init__.py"
  "amprealize/billing/service.py"
  "amprealize/billing/api.py"
  "amprealize/billing/webhook_routes.py"
  "amprealize/analytics/__init__.py"
  "amprealize/analytics/telemetry_kpi_projector.py"
  "amprealize/analytics/warehouse.py"
  "amprealize/research_contracts.py"
  "amprealize/research_service.py"
)

for f in "${FILES[@]}"; do
  echo "=== FILE: $f ===" >> "$OUTPUT"
  cat "$f" >> "$OUTPUT"
  echo "" >> "$OUTPUT"
done

echo "Exported ${#FILES[@]} files to $OUTPUT"
wc -l "$OUTPUT"
