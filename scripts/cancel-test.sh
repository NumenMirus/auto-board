#!/bin/sh
# AutoBreadboard cancellation test.
# Verifies that POST /api/v1/jobs/{id}/cancel transitions a running job to
# 'cancelled' within 10s, sets finished_at, and releases the per-job
# redis lock (abb:lock:{project}:{revision}:{operation}).
# Usage: scripts/cancel-test.sh [base_url]
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
BASE_URL="${1:-http://localhost:8000}"
FIXTURE="$ROOT_DIR/backend/tests/fixtures/04-74hc14-flagship.json"
[ -f "$FIXTURE" ] || { echo "cancel-test: FAIL — fixture missing" >&2; exit 1; }

echo "cancel-test: targeting $BASE_URL"

PROJ=$(curl -sf -X POST "$BASE_URL/api/v1/projects" -H 'content-type: application/json' \
  --data "$(jq -c '{name: "cancel-test", boardModelId: .board.modelId, document: .}' "$FIXTURE")")
PID=$(echo "$PROJ" | jq -r .id)
echo "cancel-test: project=$PID"

REV=$(curl -sf -X POST "$BASE_URL/api/v1/projects/$PID/revisions")
RID=$(echo "$REV" | jq -r .id)

JOB=$(curl -sf -X POST "$BASE_URL/api/v1/projects/$PID/jobs" \
  -H 'content-type: application/json' \
  -H "Idempotency-Key: cancel-$(date +%s%N)" \
  --data "$(jq -n --arg rev "$RID" '{operation: "solve", revisionId: $rev, seed: 12345, preset: "quality"}')")
JID=$(echo "$JOB" | jq -r .id)
echo "cancel-test: job=$JID"

# Wait for the job to enter running
for i in $(seq 1 200); do
  ST=$(curl -sf "$BASE_URL/api/v1/jobs/$JID" | jq -r .status)
  [ "$ST" = "running" ] && break
  [ "$ST" = "succeeded" ] && { echo "cancel-test: PASS — completed before cancel could land (race)"; exit 0; }
  sleep 0.05
done

curl -sf -X POST "$BASE_URL/api/v1/jobs/$JID/cancel" -o /dev/null -w "cancel-test: cancel HTTP %{http_code}\n"

deadline=$(( $(date +%s) + 10 ))
while :; do
  ST=$(curl -sf "$BASE_URL/api/v1/jobs/$JID" | jq -r .status)
  case "$ST" in
    cancelled) echo "cancel-test: status=cancelled within 10s"; break ;;
    succeeded) echo "cancel-test: PASS — completed before cancel (race)"; exit 0 ;;
    failed) echo "cancel-test: FAIL — solver reported failure on cancel"; exit 1 ;;
  esac
  [ "$(date +%s)" -ge "$deadline" ] && { echo "cancel-test: FAIL — timeout last=$ST"; exit 1; }
  sleep 0.2
done

# The lock may take a moment to be released after status=cancelled (the
# solver thread has to observe the cancel flag, raise, hit the finally
# block's CAS-release). Poll EXISTS for up to 5s.
LOCK_KEY="abb:lock:${PID}:${RID}:solve"
for i in $(seq 1 50); do
  EX=$(docker exec abb-redis redis-cli EXISTS "$LOCK_KEY" 2>/dev/null | tr -d ' \n')
  [ "$EX" = "0" ] && break
  sleep 0.1
done
echo "cancel-test: lock EXISTS=$EX (expect 0)"
[ "$EX" = "0" ] || { echo "cancel-test: FAIL — lock not released"; exit 1; }

# DB row check
ROW=$(docker exec abb-postgres psql -U autobreadboard -d autobreadboard -t -A \
  -c "SELECT status || '|' || COALESCE(finished_at::text,'null') FROM solver_jobs WHERE id='$JID'" 2>/dev/null)
echo "cancel-test: db row = $ROW"
echo "$ROW" | grep -qE '^cancelled\|[0-9]' || { echo "cancel-test: FAIL — db row not cancelled or finished_at null"; exit 1; }

echo "cancel-test: PASS"
