#!/bin/sh
# End-to-end smoke test against a running AutoBreadboard stack.
# Usage: scripts/smoke-test.sh [base_url]
# Default base_url is http://localhost:8000.
#
# This script is intentionally split into two phases:
#   Phase 1 (always runs): operational endpoint checks (healthz, readyz,
#     version). These succeed as soon as the API is up; they are the contract
#     we can verify today.
#   Phase 2 (TODO(wave-4)): full fixture-driven solve + export + download
#     assertions. The fixture JSONs and the full pipeline land in a later
#     milestone — leaving the exact curl/jq commands here as commented
#     starters so the wave-4 task can flip them on.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
BASE_URL="${1:-http://localhost:8000}"

curl_sf() {
    # curl -sf: silent + fail on >=400. Captures body and exits non-zero on error.
    curl -sf "$@"
}

curl_status() {
    # Status code only (no body), no -f so 4xx/5xx return their actual code.
    curl -s -o /dev/null -w '%{http_code}' "$@"
}

echo "smoke-test: targeting $BASE_URL"

# ---------- Phase 1: operational endpoints (live today) ---------------------

echo "smoke-test: GET /healthz"
body="$(curl_sf "$BASE_URL/healthz")"
status_field="$(printf '%s' "$body" | jq -r '.status // empty')"
if [ "$status_field" != "ok" ]; then
    echo "smoke-test: FAIL — /healthz expected status=ok, got '$body'" >&2
    exit 1
fi
echo "smoke-test: /healthz ok"

echo "smoke-test: GET /readyz"
# /readyz returns a JSON object when the stack is healthy. We accept any 2xx.
code="$(curl_status "$BASE_URL/readyz")"
if [ "$code" -lt 200 ] || [ "$code" -ge 300 ]; then
    echo "smoke-test: FAIL — /readyz returned HTTP $code" >&2
    exit 1
fi
echo "smoke-test: /readyz HTTP $code"

echo "smoke-test: GET /version"
version="$(curl_sf "$BASE_URL/version")"
# A bare minimum: must be JSON with an apiVersion field.
if ! printf '%s' "$version" | grep -q '"apiVersion"'; then
    echo "smoke-test: FAIL — /version body lacks apiVersion: $version" >&2
    exit 1
fi
echo "smoke-test: /version -> $version"

# ---------- Phase 2: fixture-driven solve + export ---------------------------

FIXTURE="$ROOT_DIR/backend/tests/fixtures/04-74hc14-flagship.json"
if [ ! -f "$FIXTURE" ]; then
    echo "smoke-test: FAIL — fixture $FIXTURE missing" >&2
    exit 1
fi

echo "smoke-test: creating project from fixture"
project_json="$(curl_sf -X POST "$BASE_URL/api/v1/projects" \
    -H 'content-type: application/json' \
    --data "$(jq -c '{name: "smoke-74hc14", boardModelId: .board.modelId, document: .}' "$FIXTURE")")"
project_id="$(printf '%s' "$project_json" | jq -r '.id')"

echo "smoke-test: freezing revision"
rev_json="$(curl_sf -X POST "$BASE_URL/api/v1/projects/$project_id/revisions")"
revision_id="$(printf '%s' "$rev_json" | jq -r '.id')"

echo "smoke-test: enqueue solve job"
job_json="$(curl_sf -X POST "$BASE_URL/api/v1/projects/$project_id/jobs" \
    -H 'content-type: application/json' \
    -H "Idempotency-Key: smoke-$(date +%s)" \
    --data "$(jq -n --arg rev "$revision_id" '{operation: "solve", revisionId: $rev, seed: 12345}')")"
job_id="$(printf '%s' "$job_json" | jq -r '.id')"

echo "smoke-test: polling job $job_id"
deadline=$(( $(date +%s) + 120 ))
while :; do
    job="$(curl_sf "$BASE_URL/api/v1/jobs/$job_id")"
    status="$(printf '%s' "$job" | jq -r '.status')"
    [ "$status" = "succeeded" ] && break
    if [ "$status" = "failed" ] || [ "$status" = "cancelled" ]; then
        echo "smoke-test: FAIL — job $job_id ended with status=$status" >&2
        printf '%s' "$job" >&2
        exit 1
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "smoke-test: FAIL — job $job_id timed out (status=$status)" >&2
        exit 1
    fi
    sleep 1
done

echo "smoke-test: job $job_id succeeded; fetching result"
result_json="$(curl_sf "$BASE_URL/api/v1/jobs/$job_id/result")"
err_count="$(printf '%s' "$result_json" | jq -r '.score.errorCount // 0')"
nets_total="$(printf '%s' "$result_json" | jq -r '.score.netsTotal // 0')"
nets_completed="$(printf '%s' "$result_json" | jq -r '.score.netsCompleted // 0')"
if [ "$err_count" != "0" ] || [ "$nets_completed" != "$nets_total" ]; then
    echo "smoke-test: FAIL — errorCount=$err_count netsCompleted=$nets_completed/$nets_total" >&2
    exit 1
fi
echo "smoke-test: score OK — errorCount=$err_count netsCompleted=$nets_completed/$nets_total"

layout_id="$(printf '%s' "$job" | jq -r '.resultLayoutId')"

for fmt in svg png; do
    echo "smoke-test: creating $fmt export"
    exp_json="$(curl_sf -X POST "$BASE_URL/api/v1/layouts/$layout_id/exports" \
        -H 'content-type: application/json' \
        --data "$(jq -n --arg fmt "$fmt" '{format: $fmt}')")"
    exp_id="$(printf '%s' "$exp_json" | jq -r '.id')"

    deadline=$(( $(date +%s) + 30 ))
    while :; do
        exp="$(curl_sf "$BASE_URL/api/v1/exports/$exp_id")"
        status="$(printf '%s' "$exp" | jq -r '.status')"
        [ "$status" = "succeeded" ] && break
        [ "$status" = "failed" ] && { echo "smoke-test: FAIL — $fmt export failed" >&2; exit 1; }
        [ "$(date +%s)" -ge "$deadline" ] && { echo "smoke-test: FAIL — $fmt export timeout" >&2; exit 1; }
        sleep 1
    done

    tmp="$(mktemp)"
    curl_sf "$BASE_URL/api/v1/exports/$exp_id/download" -o "$tmp"
    if [ "$fmt" = "svg" ]; then
        grep -q '<svg' "$tmp" || { echo "smoke-test: FAIL — svg lacks <svg" >&2; exit 1; }
    else
        # PNG magic is 0x89 'P' 'N' 'G' (4 bytes). grep against binary stdin
        # can hit locale-dependent "illegal byte sequence" failures; use od
        # to read exactly the first 4 bytes as hex and compare.
        magic="$(head -c 4 "$tmp" | od -An -tx1 | tr -d ' \n')"
        if [ "$magic" != "89504e47" ]; then
            echo "smoke-test: FAIL — png magic missing (got '$magic')" >&2
            exit 1
        fi
    fi
    size="$(wc -c < "$tmp")"
    rm -f "$tmp"
    echo "smoke-test: $fmt export ok ($size bytes)"
done

echo "smoke-test: PASS"