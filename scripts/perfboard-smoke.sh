#!/usr/bin/env bash
# End-to-end perfboard smoke test against a running AutoBreadboard stack.
#   * Creates a new project from perfboard-test-project.json
#   * Enqueues a `trace-place` job, polls until done, reports the placement count
#   * Enqueues a `trace-solve` job, polls until done, reports the trace count
#
# Usage:
#   ./scripts/perfboard-smoke.sh                       # uses default localhost:8080
#   API=http://localhost:9000 ./scripts/perfboard-smoke.sh
set -euo pipefail

API="${API:-http://localhost:8080}/api/v1"
DOC_JSON="${DOC_JSON:-$(dirname "$0")/../perfboard-test-project.json}"

if [[ ! -f "$DOC_JSON" ]]; then
  echo "Document JSON not found: $DOC_JSON" >&2
  exit 1
fi

jq_check() { command -v jq >/dev/null || { echo "jq required" >&2; exit 1; }; }
jq_check

echo "==> Creating project from $DOC_JSON"
NAME=$(jq -r '.name' "$DOC_JSON")
BOARD=$(jq -r '.board.modelId' "$DOC_JSON")

CREATE_BODY=$(jq -nc \
  --arg name "$NAME" \
  --arg board "$BOARD" \
  --slurpfile doc "$DOC_JSON" \
  '{ name: $name, boardModelId: $board, document: $doc[0] }')

PROJECT_JSON=$(curl -sS -X POST "$API/projects" \
  -H 'Content-Type: application/json' \
  -d "$CREATE_BODY")
PID=$(echo "$PROJECT_JSON" | jq -r '.id')
DRAFT=$(echo "$PROJECT_JSON" | jq -r '.draftVersion')
echo "    project id: $PID  draftVersion: $DRAFT"

post_job() {
  local op="$1"
  local resp
  resp=$(curl -sS -X POST "$API/projects/$PID/jobs" \
    -H 'Content-Type: application/json' \
    -d "{\"operation\": \"$op\", \"options\": {\"placementTimeLimitMs\": 15000, \"placementSolutionCount\": 5}}")
  echo "$resp" | jq -r '.id // empty'
}

poll_job() {
  local jid="$1" label="$2"
  local status="queued" result=""
  for _ in $(seq 1 240); do
    status=$(curl -sS "$API/jobs/$jid" | jq -r '.status')
    case "$status" in
      succeeded|failed|cancelled)
        result=$(curl -sS "$API/jobs/$jid")
        echo "    $label -> $status"
        if [[ "$status" == "succeeded" ]]; then
          curl -sS "$API/jobs/$jid/result" | jq '{ diagnostics: (.diagnostics | length), traces: (.layout.traces | length), vias: (.layout.vias | length), placements: (.layout.placements | length) }'
        else
          echo "$result" | jq .
          exit 1
        fi
        return 0
        ;;
    esac
    sleep 0.5
  done
  echo "    $label timed out (last status: $status)" >&2
  exit 1
}

echo "==> Enqueueing trace-place"
JID=$(post_job "trace-place")
[[ -z "$JID" || "$JID" == "null" ]] && { echo "    trace-place create failed" >&2; exit 1; }
echo "    job id: $JID"
poll_job "$JID" "trace-place"

echo "==> Enqueueing trace-solve"
JID=$(post_job "trace-solve")
[[ -z "$JID" || "$JID" == "null" ]] && { echo "    trace-solve create failed" >&2; exit 1; }
echo "    job id: $JID"
poll_job "$JID" "trace-solve"

echo "==> Done. Open the project at http://localhost:8080/projects/$PID"
