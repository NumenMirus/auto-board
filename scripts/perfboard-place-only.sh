#!/usr/bin/env bash
# Quick trace-place-only runner. Args: <doc.json> [<seed>]
set -euo pipefail
API="${API:-http://localhost:8080}/api/v1"
DOC="${1:?usage: $0 doc.json [seed]}"
SEED="${2:-12345}"
DOC_JSON=$(realpath "$DOC")

NAME=$(jq -r '.name' "$DOC_JSON")
BOARD=$(jq -r '.board.modelId' "$DOC_JSON")

# Patch the seed/preset into the doc before sending.
PATCHED=$(mktemp)
jq --argjson seed "$SEED" '.settings.seed = $seed | .settings.solverPreset = "quality" | .settings.placementTimeLimitMs = 30000' "$DOC_JSON" > "$PATCHED"
trap 'rm -f "$PATCHED"' EXIT

CREATE=$(jq -nc --arg name "$NAME" --arg board "$BOARD" --slurpfile doc "$PATCHED" \
  '{ name: $name, boardModelId: $board, document: $doc[0] }')
PJ=$(curl -sS -X POST "$API/projects" -H 'Content-Type: application/json' -d "$CREATE")
PID=$(echo "$PJ" | jq -r '.id')
echo "project $PID"

JID=$(curl -sS -X POST "$API/projects/$PID/jobs" -H 'Content-Type: application/json' \
  -d '{"operation":"trace-place"}' | jq -r '.id')
echo "job $JID"

for _ in $(seq 1 240); do
  s=$(curl -sS "$API/jobs/$JID" | jq -r '.status')
  [[ "$s" == "succeeded" || "$s" == "failed" || "$s" == "cancelled" ]] && break
  sleep 0.5
done
echo "status: $s"
curl -sS "$API/jobs/$JID/result" | jq '.layout.placements[] | {ref:.componentRef, orient:.orientation, anchor:.anchorHoleId, holes:.occupiedHoleIds}'
