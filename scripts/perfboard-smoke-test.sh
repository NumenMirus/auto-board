#!/bin/sh
# AutoBoard perfboard smoke test.
# Creates a project on strip-20x30-double, manually places a DIP-14 +
# 2 resistors + LED, enqueues a trace-solve job, polls to success, and
# exercises every perfboard export format (Gerber top/bottom/outline,
# Excellon drill, placement CSV, SVG).
# Usage: scripts/perfboard-smoke-test.sh [base_url]
set -eu

BASE="${1:-http://localhost:8000}"

echo "perfboard-smoke: targeting $BASE"
echo "perfboard-smoke: creating project on strip-20x30-double"
PROJ=$(curl -sf -X POST "$BASE/api/v1/projects" -H 'content-type: application/json' \
  --data '{"name":"perfboard-smoke","boardModelId":"strip-20x30-double"}')
PID=$(echo "$PROJ" | jq -r .id)
echo "perfboard-smoke: project=$PID"

DOC=$(curl -sf "$BASE/api/v1/projects/$PID" | jq -r '.document')
NEW_DOC=$(echo "$DOC" | jq '
  .components = [
    {"ref":"U1","value":"74HC14","footprintId":"DIP-14","pins":["1","2","3","4","5","6","7","8","9","10","11","12","13","14"],"locked":false,"tags":[]},
    {"ref":"R1","value":"330","footprintId":"AXIAL-R","pins":["1","2"],"locked":false,"tags":[]},
    {"ref":"R2","value":"10k","footprintId":"AXIAL-R","pins":["1","2"],"locked":false,"tags":[]},
    {"ref":"LED1","value":null,"footprintId":"LED-2P","pins":["1","2"],"locked":false,"tags":[]}
  ] |
  .nets = [
    {"id":"VCC","name":"VCC","pins":[{"componentRef":"U1","pin":"14"},{"componentRef":"R2","pin":"1"}],"netClass":"power","priority":10,"constraints":[]},
    {"id":"GND","name":"GND","pins":[{"componentRef":"U1","pin":"7"},{"componentRef":"LED1","pin":"2"}],"netClass":"ground","priority":10,"constraints":[]},
    {"id":"IN1","name":"IN1","pins":[{"componentRef":"U1","pin":"1"},{"componentRef":"R1","pin":"1"}],"netClass":"digital","priority":5,"constraints":[]},
    {"id":"OUT1","name":"OUT1","pins":[{"componentRef":"U1","pin":"2"},{"componentRef":"LED1","pin":"1"}],"netClass":"digital","priority":5,"constraints":[]}
  ] |
  .layout.placements = [
    {"componentRef":"U1","anchorHoleId":"5-5","orientation":0,"span":null,"pinHoles":{"1":"5-5","2":"5-6","3":"5-7","4":"5-8","5":"5-9","6":"5-10","7":"5-11","8":"6-11","9":"6-10","10":"6-9","11":"6-8","12":"6-7","13":"6-6","14":"6-5"},"occupiedHoleIds":["5-5","5-6","5-7","5-8","5-9","5-10","5-11","6-5","6-6","6-7","6-8","6-9","6-10","6-11"],"locked":false},
    {"componentRef":"R1","anchorHoleId":"2-2","orientation":0,"span":null,"pinHoles":{"1":"2-2","2":"2-5"},"occupiedHoleIds":["2-2","2-3","2-4","2-5"],"locked":false},
    {"componentRef":"R2","anchorHoleId":"2-8","orientation":0,"span":null,"pinHoles":{"1":"2-8","2":"2-11"},"occupiedHoleIds":["2-8","2-9","2-10","2-11"],"locked":false},
    {"componentRef":"LED1","anchorHoleId":"10-5","orientation":0,"span":null,"pinHoles":{"1":"10-5","2":"10-8"},"occupiedHoleIds":["10-5","10-6","10-7","10-8"],"locked":false}
  ]
')
echo "perfboard-smoke: updating document"
DRAFT_V=$(echo "$PROJ" | jq -r .draftVersion)
curl -sf -X PUT "$BASE/api/v1/projects/$PID/document" \
  -H 'content-type: application/json' -H "If-Match: $DRAFT_V" \
  --data "$(jq -n --argjson doc "$NEW_DOC" '{document: $doc}')" > /dev/null

echo "perfboard-smoke: freezing revision"
REV=$(curl -sf -X POST "$BASE/api/v1/projects/$PID/revisions")
RID=$(echo "$REV" | jq -r .id)

echo "perfboard-smoke: enqueue trace-solve job"
JOB=$(curl -sf -X POST "$BASE/api/v1/projects/$PID/jobs" \
  -H 'content-type: application/json' \
  -H "Idempotency-Key: perf-$(date +%s%N)" \
  --data "$(jq -n --arg rev "$RID" '{operation: "trace-solve", revisionId: $rev, seed: 12345}')")
JID=$(echo "$JOB" | jq -r .id)
echo "perfboard-smoke: job=$JID"

deadline=$(( $(date +%s) + 60 ))
while :; do
  job="$(curl -sf "$BASE/api/v1/jobs/$JID")"
  status="$(echo "$job" | jq -r .status)"
  [ "$status" = "succeeded" ] && break
  [ "$status" = "failed" ] && { echo "perfboard-smoke: FAIL — job failed: $(echo "$job" | jq -r .errorMessage)" >&2; exit 1; }
  [ "$(date +%s)" -ge "$deadline" ] && { echo "perfboard-smoke: FAIL — timeout, status=$status" >&2; exit 1; }
  sleep 0.5
done
echo "perfboard-smoke: job succeeded"

result="$(curl -sf "$BASE/api/v1/jobs/$JID/result")"
err_count=$(echo "$result" | jq -r '.score.errorCount // 0')
traces=$(echo "$result" | jq -r '.layout.traces | length')
echo "perfboard-smoke: errorCount=$err_count traces=$traces"
[ "$err_count" = "0" ] || { echo "perfboard-smoke: FAIL — errors present" >&2; exit 1; }
[ "$traces" -ge 1 ] || { echo "perfboard-smoke: FAIL — no traces produced" >&2; exit 1; }

layout_id=$(echo "$job" | jq -r .resultLayoutId)
echo "perfboard-smoke: layout=$layout_id"

for fmt in gerber-top gerber-bottom gerber-outline drill placement-csv svg; do
  echo "perfboard-smoke: creating $fmt export"
  exp=$(curl -sf -X POST "$BASE/api/v1/layouts/$layout_id/exports" \
    -H 'content-type: application/json' --data "$(jq -n --arg fmt "$fmt" '{format: $fmt}')")
  exp_id=$(echo "$exp" | jq -r .id)
  edeadline=$(( $(date +%s) + 30 ))
  while :; do
    e="$(curl -sf "$BASE/api/v1/exports/$exp_id")"
    estatus="$(echo "$e" | jq -r .status)"
    [ "$estatus" = "succeeded" ] && break
    [ "$estatus" = "failed" ] && { echo "perfboard-smoke: FAIL — $fmt export failed: $(echo "$e" | jq -r .errorMessage)" >&2; exit 1; }
    [ "$(date +%s)" -ge "$edeadline" ] && { echo "perfboard-smoke: FAIL — $fmt export timeout" >&2; exit 1; }
    sleep 0.5
  done
  tmp=$(mktemp)
  curl -sf "$BASE/api/v1/exports/$exp_id/download" -o "$tmp"
  size=$(wc -c < "$tmp")
  case "$fmt" in
    gerber-top|gerber-bottom|gerber-outline)
      head -c 13 "$tmp" | grep -q '%FSLAX46Y46' || { echo "perfboard-smoke: FAIL — $fmt missing Gerber header" >&2; exit 1; }
      ;;
    drill)
      head -c 3 "$tmp" | grep -q 'M48' || { echo "perfboard-smoke: FAIL — drill missing M48 header" >&2; exit 1; }
      ;;
    placement-csv)
      head -c 3 "$tmp" | grep -q 'ref' || { echo "perfboard-smoke: FAIL — placement-csv missing header" >&2; exit 1; }
      ;;
    svg)
      grep -q '<svg' "$tmp" || { echo "perfboard-smoke: FAIL — svg lacks <svg" >&2; exit 1; }
      ;;
  esac
  rm -f "$tmp"
  echo "perfboard-smoke: $fmt ok ($size bytes)"
done

echo "perfboard-smoke: PASS"
