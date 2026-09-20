#!/bin/sh
# Helm lint + template render for the AutoBreadboard chart.
# Uses the local `helm` binary when present (developer convenience); falls
# back to a one-shot `alpine/helm:3.19.0` container so this script works in
# any environment where Docker is available (CI runners, dev sandboxes without
# a global helm install).
#
# The chart path is `deploy/helm/autobreadboard` per addendum §3. A later
# wave creates the chart; this script targets that path so it becomes a no-op
# failure with `no such file or directory` until then.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHART_DIR="$ROOT_DIR/deploy/helm/autobreadboard"

run_helm() {
    if command -v helm >/dev/null 2>&1; then
        helm "$@"
    else
        docker run --rm \
            -v "$ROOT_DIR":/work \
            -w /work \
            alpine/helm:3.19.0 \
            helm "$@"
    fi
}

if [ ! -d "$CHART_DIR" ]; then
    echo "helm-lint: chart not found at $CHART_DIR (created in a later wave)" >&2
    echo "helm-lint: nothing to lint yet — exiting 0 so CI doesn't block." >&2
    exit 0
fi

cd "$ROOT_DIR"

echo "helm-lint: linting chart at $CHART_DIR"
run_helm lint "$CHART_DIR"

for values in \
    "$CHART_DIR/values.yaml" \
    "$CHART_DIR/values-dev.yaml" \
    "$CHART_DIR/values-staging.yaml" \
    "$CHART_DIR/values-production.yaml"
do
    if [ -f "$values" ]; then
        echo "helm-lint: rendering with $(basename "$values")"
        run_helm template "$(basename "$values" .yaml)" "$CHART_DIR" --values "$values" >/dev/null
    fi
done