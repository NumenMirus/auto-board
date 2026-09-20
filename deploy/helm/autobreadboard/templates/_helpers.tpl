{{/*
Expand the name of the chart.
*/}}
{{- define "autobreadboard.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "autobreadboard.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Chart name and version label value.
*/}}
{{- define "autobreadboard.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels — applied to every resource.
*/}}
{{- define "autobreadboard.labels" -}}
helm.sh/chart: {{ include "autobreadboard.chart" . }}
{{ include "autobreadboard.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: autobreadboard
environment: {{ .Values.global.environment | quote }}
{{- end -}}

{{/*
Selector labels — used in matchLabels; must be stable across revisions.
*/}}
{{- define "autobreadboard.selectorLabels" -}}
app.kubernetes.io/name: {{ include "autobreadboard.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Component selector labels (api / worker / frontend / migrate) used in matchLabels
of Deployments/Services/Jobs and in NetworkPolicies.
*/}}
{{- define "autobreadboard.componentSelectorLabels" -}}
{{ include "autobreadboard.selectorLabels" . }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
Resolve the Secret name used as envFrom for app pods.
Prefers an externally-managed Secret (set via secrets.existingSecret); otherwise
falls back to the dev-only inline Secret this chart renders when
secrets.dev.enabled=true (secrets.dev.secretName).
*/}}
{{- define "autobreadboard.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else if .Values.secrets.dev.enabled -}}
{{- default (printf "%s-dev" (include "autobreadboard.fullname" .)) .Values.secrets.dev.secretName -}}
{{- end -}}
{{- end -}}

{{/*
The ServiceMonitor CRD is optional. When the operator is not installed we skip
the resource entirely (see servicemonitor.yaml). Network policies scope by the
exact `component` label.
*/}}
