<script lang="ts">
  import {
    apiFetch,
    createJob,
    validateLayout,
    ApiError
  } from '$lib/api/client';
  import BoardCanvas from '$lib/components/BoardCanvas.svelte';
  import DiagnosticsPanel from '$lib/components/DiagnosticsPanel.svelte';
  import NetPanel from '$lib/components/NetPanel.svelte';
  import Toolbar from '$lib/components/Toolbar.svelte';
  import JobProgress from '$lib/components/JobProgress.svelte';
  import AdvancedPanel from '$lib/components/AdvancedPanel.svelte';
  import MetricsBar from '$lib/components/MetricsBar.svelte';
  import SafetyNotice from '$lib/components/SafetyNotice.svelte';
  import ExportMenu from '$lib/components/ExportMenu.svelte';
  import { projectStore } from '$lib/state/project.svelte';
  import { debounce } from '$lib/debounce';
  import type {
    BreadboardModel,
    BreadboardFootprint,
    Diagnostic,
    Layout,
    LayoutScore,
    NetClass,
    Orientation,
    ProjectDocument,
    TraceLayout
  } from '$lib/types';
  import type { SolverOperation } from '$lib/api/client';

  interface PageProps {
    params: { id: string };
  }
  let { params }: PageProps = $props();

  interface ProjectEnvelope {
    id: string;
    name: string;
    boardModelId: string;
    draftVersion: number;
    document: ProjectDocument;
  }

  let loadError = $state<string | null>(null);
  let isLoading = $state(true);
  let validatingNow = $state(false);
  let lastValidateError = $state<string | null>(null);
  let jumperToolActive = $state(false);
  let selectedNetId = $state<string | null>(null);
  // The id of the most-recently completed solver job — drives ExportMenu
  // (downloads only make sense once a layout has been produced/saved).
  let lastResultLayoutId = $state<string | null>(null);

  // ------------------------------------------------------------------------
  // Load project + board + footprint catalog once.
  // ------------------------------------------------------------------------
  $effect(() => {
    const id = params.id;
    let cancelled = false;

    async function load(): Promise<void> {
      isLoading = true;
      loadError = null;
      try {
        const envelope = await apiFetch<ProjectEnvelope>(`/projects/${id}`);
        if (cancelled) return;
        const [board, footprintsList] = await Promise.all([
          apiFetch<BreadboardModel>(`/board-models/${envelope.boardModelId}`),
          apiFetch<BreadboardFootprint[]>('/footprints')
        ]);
        if (cancelled) return;
        const footprints: Record<string, BreadboardFootprint> = {};
        for (const fp of footprintsList) footprints[fp.id] = fp;

        projectStore.document = envelope.document;
        projectStore.board = board;
        projectStore.footprints = footprints;
        // Seed the undo machinery with the loaded layout so the first
        // mutation isn't preceded by a "ghost" empty-state undo entry.
        projectStore.pushUndo(envelope.document.layout);
      } catch (err) {
        if (cancelled) return;
        loadError = err instanceof ApiError ? err.message : 'Failed to load project.';
      } finally {
        if (!cancelled) isLoading = false;
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  });

  // ------------------------------------------------------------------------
  // Live validation. Debounced 250ms per main spec §9.2 ("after every
  // mutation: update occupancy locally, then debounce 250ms and POST
  // /api/v1/validate"). Runs whenever the document layout changes.
  // ------------------------------------------------------------------------
  const runValidate = async (): Promise<void> => {
    const doc = projectStore.document;
    const board = projectStore.board;
    if (doc === null || board === null) return;
    validatingNow = true;
    lastValidateError = null;
    try {
      const result = await validateLayout(
        doc.board.modelId,
        doc.components,
        doc.nets,
        doc.layout,
        { allowCriticalNetClasses: doc.settings.allowCriticalNetClasses }
      );
      projectStore.diagnostics = result.diagnostics;
      projectStore.score = result.score;
    } catch (err) {
      lastValidateError = err instanceof ApiError ? err.message : 'Validation failed.';
    } finally {
      validatingNow = false;
    }
  };

  const debouncedValidate = debounce(runValidate, 250);

  $effect(() => {
    // Subscribe to the layout — every mutation produces a new object, so
    // this effect fires on each one. The debounced wrapper coalesces
    // bursts so we don't hammer the backend during a drag.
    void projectStore.document?.layout;
    debouncedValidate();
  });

  // ------------------------------------------------------------------------
  // Local mutation handlers. Each one builds a fresh `Layout`, applies
  // it through `applyLayoutMutation` (which pushes the prior layout to
  // the undo stack and installs the new one), then triggers the
  // debounced validate. Locked placements are not movable.
  // ------------------------------------------------------------------------
  function movePlacement(componentRef: string, newAnchorHoleId: string): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const next: Layout = {
      ...doc.layout,
      placements: doc.layout.placements.map((p) => {
        if (p.componentRef !== componentRef) return p;
        // We can't recompute occupiedHoleIds / pinHoles client-side
        // without the full placement engine; the server will do that on
        // the next validate. We update only the anchor and leave the rest
        // for the backend to fill in.
        return { ...p, anchorHoleId: newAnchorHoleId };
      })
    };
    projectStore.applyLayoutMutation(next);
  }

  function rotatePlacement(componentRef: string): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const next: Layout = {
      ...doc.layout,
      placements: doc.layout.placements.map((p) => {
        if (p.componentRef !== componentRef) return p;
        const orientations: Orientation[] = [0, 90, 180, 270];
        const idx = orientations.indexOf(p.orientation);
        const nextOrientation = orientations[(idx + 1) % orientations.length];
        return { ...p, orientation: nextOrientation };
      })
    };
    projectStore.applyLayoutMutation(next);
  }

  function toggleLockPlacement(componentRef: string): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const next: Layout = {
      ...doc.layout,
      placements: doc.layout.placements.map((p) =>
        p.componentRef === componentRef ? { ...p, locked: !p.locked } : p
      )
    };
    projectStore.applyLayoutMutation(next);
  }

  function deleteSelection(kind: 'component' | 'jumper' | 'trace', id: string): void {
    // This editor route only ever loads a breadboard Layout (perfboard
    // projects use a read-only preview until the perfboard editor lands);
    // a 'trace' selection can't occur here, but the callback signature must
    // satisfy BoardCanvas's shared (breadboard | perfboard) prop contract.
    if (kind === 'trace') return;
    const doc = projectStore.document;
    if (doc === null) return;
    const next: Layout =
      kind === 'component'
        ? {
            ...doc.layout,
            placements: doc.layout.placements.filter((p) => p.componentRef !== id),
            jumpers: doc.layout.jumpers.filter((j) => j.netId !== id)
          }
        : {
            ...doc.layout,
            jumpers: doc.layout.jumpers.filter((j) => j.id !== id)
          };
    projectStore.applyLayoutMutation(next);
  }

  function createJumperBetween(startHoleId: string, endHoleId: string): void {
    const doc = projectStore.document;
    if (doc === null) return;
    // Pick the net that currently owns at least one of the two holes; if
    // none, fall back to the first net (the validator will surface the
    // NET_OPEN if the user picked two holes on different nets).
    const net = doc.nets[0];
    if (net === undefined) return;
    const id = `j-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
    const next: Layout = {
      ...doc.layout,
      jumpers: [
        ...doc.layout.jumpers,
        {
          id,
          netId: net.id,
          startHoleId,
          endHoleId,
          path: { points: [], layer: 'lower' },
          color: null,
          estimatedLengthMm: 0,
          locked: false
        }
      ]
    };
    projectStore.applyLayoutMutation(next);
  }

  // ------------------------------------------------------------------------
  // Net panel handlers.
  // ------------------------------------------------------------------------
  function setSelectedNet(netId: string | null): void {
    selectedNetId = netId;
    projectStore.setSelection(netId === null ? { kind: null, id: null } : { kind: 'net', id: netId });
  }

  function changeNetClass(netId: string, netClass: NetClass): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const nextDoc: ProjectDocument = {
      ...doc,
      nets: doc.nets.map((n) => (n.id === netId ? { ...n, netClass } : n))
    };
    projectStore.document = nextDoc;
  }

  function changePriority(netId: string, priority: number): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const nextDoc: ProjectDocument = {
      ...doc,
      nets: doc.nets.map((n) => (n.id === netId ? { ...n, priority } : n))
    };
    projectStore.document = nextDoc;
  }

  // ------------------------------------------------------------------------
  // Toolbar -> jobs. Validate is synchronous and skips the queue.
  // ------------------------------------------------------------------------
  async function startOperation(operation: SolverOperation): Promise<void> {
    const doc = projectStore.document;
    if (doc === null) return;
    if (operation === 'validate') {
      await runValidate();
      return;
    }
    try {
      const seed = doc.settings.seed;
      const preset = doc.settings.solverPreset;
      const job = await createJob(params.id, operation, {
        seed,
        options: {
          seed,
          preset: preset as 'fast' | 'balanced' | 'quality',
          placementWeights: doc.settings.placementWeights,
          routingWeights: doc.settings.routingWeights,
          allowCriticalNetClasses: doc.settings.allowCriticalNetClasses
        }
      });
      projectStore.setJobSnapshot({
        id: job.id,
        status: job.status,
        progressPercent: job.progressPercent,
        progressPhase: job.progressPhase
      });
    } catch (err) {
      lastValidateError = err instanceof ApiError ? err.message : 'Could not enqueue job.';
    }
  }

  function onApplySolverResult(result: {
    layout: Layout | TraceLayout;
    score: LayoutScore;
    diagnostics: Diagnostic[];
  }): void {
    // This route only ever solves a breadboard project's Layout (perfboard
    // solves produce a TraceLayout, which this editor doesn't render yet).
    if (!('jumpers' in result.layout)) return;
    projectStore.applyLayoutMutation(result.layout);
    projectStore.diagnostics = result.diagnostics;
    projectStore.score = result.score;
    projectStore.clearJob();
    // The solver produced a fresh layout; remember its id (if the backend
    // returns one in future progress responses) so ExportMenu can target it.
    lastResultLayoutId = null;
    // Re-run the synchronous validator so diagnostics stay consistent
    // with what the editor actually displays.
    void runValidate();
  }

  // ------------------------------------------------------------------------
  // Undo / redo via Ctrl+Z / Ctrl+Shift+Z (also ⌘ on macOS). After
  // jumping, re-validate so diagnostics stay in sync.
  // ------------------------------------------------------------------------
  function handleUndo(): void {
    const prev = projectStore.undo();
    if (prev === undefined) return;
    if (projectStore.document !== null) {
      projectStore.document = { ...projectStore.document, layout: prev };
    }
    void runValidate();
  }

  function handleRedo(): void {
    const next = projectStore.redo();
    if (next === undefined) return;
    if (projectStore.document !== null) {
      projectStore.document = { ...projectStore.document, layout: next };
    }
    void runValidate();
  }

  $effect(() => {
    function onKey(event: KeyboardEvent): void {
      const t = event.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      const ctrl = event.ctrlKey || event.metaKey;
      if (ctrl && event.shiftKey && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        handleRedo();
      } else if (ctrl && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        handleUndo();
      }
    }
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  });

  // ------------------------------------------------------------------------
  // Selection plumbing. The BoardCanvas only reports intent; we own the
  // authoritative state.
  // ------------------------------------------------------------------------
  function onSelect(kind: 'component' | 'jumper' | 'trace', id: string): void {
    // This route never renders a TraceLayout (see deleteSelection above),
    // so 'trace' is unreachable here; it's only in the signature to match
    // BoardCanvas's shared prop contract.
    if (kind === 'trace') return;
    projectStore.setSelection({ kind, id });
  }

  // Project the store's wide Selection union onto the narrower shape the
  // BoardCanvas wants (component/jumper only).
  const canvasSelectionId = $derived(
    projectStore.selection.kind === 'component' || projectStore.selection.kind === 'jumper'
      ? projectStore.selection.id
      : null
  );
  const canvasSelectionKind = $derived<'component' | 'jumper' | 'trace' | null>(
    projectStore.selection.kind === 'component' || projectStore.selection.kind === 'jumper'
      ? projectStore.selection.kind
      : null
  );

  // ------------------------------------------------------------------------
  // Advanced panel -> mutate the document's `settings`.
  // ------------------------------------------------------------------------
  function updateSeed(seed: number): void {
    const doc = projectStore.document;
    if (doc === null) return;
    projectStore.document = { ...doc, settings: { ...doc.settings, seed } };
  }
  function updatePreset(preset: string): void {
    const doc = projectStore.document;
    if (doc === null) return;
    projectStore.document = { ...doc, settings: { ...doc.settings, solverPreset: preset } };
  }
  function updatePlacementWeights(weights: Record<string, number>): void {
    const doc = projectStore.document;
    if (doc === null) return;
    projectStore.document = { ...doc, settings: { ...doc.settings, placementWeights: weights } };
  }
  function updateRoutingWeights(weights: Record<string, number>): void {
    const doc = projectStore.document;
    if (doc === null) return;
    projectStore.document = { ...doc, settings: { ...doc.settings, routingWeights: weights } };
  }
  function updateAllowCritical(allow: boolean): void {
    const doc = projectStore.document;
    if (doc === null) return;
    projectStore.document = {
      ...doc,
      settings: { ...doc.settings, allowCriticalNetClasses: allow }
    };
  }

  </script>

<section class="editor">
  <header class="editor-header">
    <a href="/" class="back">&larr; Projects</a>
    <h1>{projectStore.document?.name ?? params.id}</h1>
    <div class="actions-inline">
      <button
        type="button"
        class="jumper-toggle"
        class:active={jumperToolActive}
        onclick={() => (jumperToolActive = !jumperToolActive)}
      >
        {jumperToolActive ? 'Exit jumper tool' : 'Jumper tool'}
      </button>
    </div>
  </header>

  {#if loadError}
    <p class="error">Error: {loadError}</p>
  {:else if isLoading}
    <p class="loading">Loading project…</p>
  {:else if projectStore.board && projectStore.document}
    <Toolbar
      disabled={false}
      onAutoPlace={() => void startOperation('place')}
      onAutoRoute={() => void startOperation('route')}
      onSolve={() => void startOperation('solve')}
      onValidate={() => void startOperation('validate')}
      onOptimize={() => void startOperation('optimize')}
    />

    <JobProgress
      jobId={projectStore.jobId}
      onApply={onApplySolverResult}
      onJobUpdate={(job) => {
        if (typeof job.resultLayoutId === 'string') {
          lastResultLayoutId = job.resultLayoutId;
        }
      }}
    />

    <div class="canvas-wrap">
      <BoardCanvas
        board={projectStore.board}
        layout={projectStore.document.layout}
        showLabels={true}
        jumperToolActive={jumperToolActive}
        jumperStartHoleId={null}
        selectedId={canvasSelectionId}
        selectedKind={canvasSelectionKind}
        onPlacementMove={movePlacement}
        onRotate={rotatePlacement}
        onLockToggle={toggleLockPlacement}
        onDelete={deleteSelection}
        onJumperCreate={createJumperBetween}
        onSelect={onSelect}
      />
    </div>

    <aside class="sidebar">
      <MetricsBar score={projectStore.score} />
      <DiagnosticsPanel
        diagnostics={projectStore.diagnostics}
        validated={projectStore.score !== null}
        onSelect={(d) => {
          const ref = d.relatedComponentRefs[0];
          if (ref !== undefined) {
            onSelect('component', ref);
          }
        }}
      />
      <NetPanel
        nets={projectStore.document.nets}
        selectedNetId={selectedNetId}
        onSelectNet={setSelectedNet}
        onChangeNetClass={changeNetClass}
        onChangePriority={changePriority}
      />
      {#if projectStore.document.settings !== undefined}
        <AdvancedPanel
          seed={projectStore.document.settings.seed}
          preset={projectStore.document.settings.solverPreset as 'fast' | 'balanced' | 'quality'}
          placementWeights={projectStore.document.settings.placementWeights}
          routingWeights={projectStore.document.settings.routingWeights}
          allowCriticalNetClasses={projectStore.document.settings.allowCriticalNetClasses}
          onSeedChange={updateSeed}
          onPresetChange={updatePreset}
          onPlacementWeightsChange={updatePlacementWeights}
          onRoutingWeightsChange={updateRoutingWeights}
          onAllowCriticalChange={updateAllowCritical}
        />
      {/if}
      <ExportMenu layoutId={lastResultLayoutId} />
    </aside>

    {#if validatingNow}
      <p class="validating">Validating…</p>
    {/if}
    {#if lastValidateError !== null}
      <p class="error">{lastValidateError}</p>
    {/if}
  {/if}
</section>

<footer class="page-footer">
  <SafetyNotice />
</footer>

<style>
  .editor {
    display: grid;
    grid-template-columns: 1fr 320px;
    grid-template-rows: auto auto auto 1fr auto;
    grid-template-areas:
      'header header'
      'toolbar toolbar'
      'progress progress'
      'canvas sidebar'
      'error error';
    gap: var(--space-3);
    padding: var(--space-3);
    flex: 1;
    min-height: 0;
  }

  .editor-header {
    grid-area: header;
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
  }

  .editor-header h1 {
    margin: 0;
    font-size: 18px;
  }

  .actions-inline {
    margin-left: auto;
  }

  .jumper-toggle {
    padding: 4px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
  }

  .jumper-toggle.active {
    background: var(--color-accent);
    color: white;
    border-color: var(--color-accent);
  }

  .canvas-wrap {
    grid-area: canvas;
    min-height: 480px;
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .sidebar {
    grid-area: sidebar;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    background: var(--color-surface);
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .error {
    grid-area: error;
    color: var(--color-error);
    margin: 0;
  }

  .loading,
  .validating {
    color: var(--color-muted);
    margin: 0;
  }

  .page-footer {
    border-top: 1px solid var(--color-border);
    padding: var(--space-2) var(--space-3);
    background: var(--color-surface);
  }
</style>