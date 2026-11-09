#!/bin/sh
# Start the live Factory dashboard on port 4610 (reconstructed 2026-11-06).
H=$HOME/.hermes; S=$H/state/factory
cd "$H/factory-dashboard" || exit 1
exec "$H/hermes-agent/venv/bin/python" scripts/serve_factory_dashboard.py \
  --settings-db "$S/task-settings.db" --policy-db "$S/dashboard-policy.db" --catalog "$S/model-catalog.json" \
  --board-db "$H/kanban.db" --board-id default --hermes-home "$H" --published-state "$S/published.json" --profile-settings-source "$H/hermes-agent" --port 4610
