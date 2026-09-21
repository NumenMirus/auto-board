<script lang="ts">
  import {
    apiFetch,
    createJob,
    validateLayout,
    updateProjectDocument,
    ApiError
  } from '$lib/api/client';
  import BoardCanvas from '$lib/components/BoardCanvas.svelte';
  import SchematicCanvas from '$lib/components/SchematicCanvas.svelte';
  import SymbolPalette from '$lib/components/SymbolPalette.svelte';
  import SchematicInspector from '$lib/components/SchematicInspector.svelte';
  import DiagnosticsPanel from '$lib/components/DiagnosticsPanel.svelte';
  import NetPanel from '$lib/components/NetPanel.svelte';
  import Toolbar from '$lib/components/Toolbar.svelte';
  import JobProgress from '$lib/components/JobProgress.svelte';
  import AdvancedPanel from '$lib/components/AdvancedPanel.svelte';
  import MetricsBar from '$lib/components/MetricsBar.svelte';
  import SafetyNotice from '$lib/components/SafetyNotice.svelte';
  import ExportMenu from '$lib/components/ExportMenu.svelte';
  import Panel from '$lib/components/Panel.svelte';
  import { projectStore } from '$lib/state/project.svelte';
  import { debounce } from '$lib/debounce';
  import { deriveNetlist, pruneLayout } from '$lib/schematic/netlist';
  import { PORT_PALETTE, nextRef, nextNodeId, paletteEntryFor } from '$lib/schematic/catalog';
  import type {
    AnyBoardModel,
    BoardKind,
    BreadboardFootprint,
    BreadboardModel,
    Diagnostic,
    Layout,
    LayoutScore,
    NetClass,
    Orientation,
    ProjectDocument,
    Schematic,
    SchematicEndpoint,
    SchematicNode,
    SchematicPortKind,
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
    createdAt: string;
    updatedAt: string;
  }

  let loadError = $state<string | null>(null);
  let isLoading = $state(true);
  let validatingNow = $state(false);
  let lastValidateError = $state<string | null>(null);
  let jumperToolActive = $state(false);
  let selectedNetId = $state<string | null>(null);
  let lastResultLayoutId = $state<string | null>(null);
  let openPanel = $state<'layout' | 'nets' | 'diagnostics' | 'advanced' | 'export' | null>(null);
  let openSchematicPanel = $state<'components' | 'properties' | null>('components');
  let panelInitialised = false;
  let viewMode = $state<'board' | 'schematic'>('board');
  let armedFootprintId = $state<string | null>(null);
  let armedPortKind = $state<SchematicPortKind | null>(null);
  let schematicSelection = $state<{ kind: 'node' | 'connection'; id: string } | null>(null);
  let reloadToken = $state(0);
  let lastSavedJson = $state<string | null>(null);
  let saveState = $state<'idle' | 'saving' | 'saved' | 'error'>('idle');
  let saveError = $state<string | null>(null);

  $effect(() => {
    const id = params.id;
    void reloadToken;
    let cancelled = false;

    async function load(): Promise<void> {
      isLoading = true;
      loadError = null;
      try {
        const envelope = await apiFetch<ProjectEnvelope>(`/projects/${id}`);
        if (cancelled) return;
        const [board, footprintsList] = await Promise.all([
          apiFetch<AnyBoardModel & { kind: BoardKind }>(`/board-models/${envelope.boardModelId}`),
          apiFetch<BreadboardFootprint[]>('/footprints')
        ]);
        if (cancelled) return;
        const footprints: Record<string, BreadboardFootprint> = {};
        for (const fp of footprintsList) footprints[fp.id] = fp;

        projectStore.document = envelope.document;
        projectStore.draftVersion = envelope.draftVersion;
        projectStore.board = board;
        projectStore.boardKind = board.kind;
        projectStore.footprints = footprints;
        projectStore.traceLayout = null;
        lastSavedJson = JSON.stringify(envelope.document);
        saveState = 'idle';
        saveError = null;
        const hasDrawing = (envelope.document.schematic?.nodes.length ?? 0) > 0;
        viewMode = hasDrawing || envelope.document.components.length > 0 ? 'board' : 'schematic';
        schematicSelection = null;
        if (board.kind === 'breadboard') {
          projectStore.pushUndo(envelope.document.layout);
        }
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

  const runValidate = async (): Promise<void> => {
    const doc = projectStore.document;
    const board = projectStore.board;
    if (doc === null || board === null || projectStore.boardKind === 'perfboard') return;
    validatingNow = true;
    lastValidateError = null;
    try {
      const result = await validateLayout(
        board as BreadboardModel,
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
    void projectStore.document?.layout;
    void projectStore.document?.nets;
    debouncedValidate();
  });

  async function saveDocument(): Promise<void> {
    const doc = projectStore.document;
    if (doc === null) return;
    const json = JSON.stringify(doc);
    saveState = 'saving';
    try {
      const envelope = await updateProjectDocument(params.id, doc, projectStore.draftVersion);
      projectStore.draftVersion = envelope.draftVersion;
      lastSavedJson = json;
      saveState = 'saved';
      saveError = null;
    } catch (err) {
      saveState = 'error';
      if (err instanceof ApiError && err.status === 409) {
        saveError = 'Project changed elsewhere — reloading.';
        reloadToken += 1;
      } else {
        saveError = err instanceof ApiError ? err.message : 'Save failed.';
      }
    }
  }

  const scheduleSave = debounce(() => {
    void saveDocument();
  }, 800);

  $effect(() => {
    const doc = projectStore.document;
    if (doc === null || isLoading) return;
    if (JSON.stringify(doc) === lastSavedJson) return;
    scheduleSave();
  });

  function movePlacement(componentRef: string, newAnchorHoleId: string): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const next: Layout = {
      ...doc.layout,
      placements: doc.layout.placements.map((p) => {
        if (p.componentRef !== componentRef) return p;
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

  const EMPTY_SCHEMATIC: Schematic = { version: 1, nodes: [], connections: [], netOverrides: [] };
  const currentSchematic = $derived(projectStore.document?.schematic ?? EMPTY_SCHEMATIC);

  const selectedSchematicNode = $derived(
    schematicSelection?.kind === 'node'
      ? (currentSchematic.nodes.find((n) => n.id === schematicSelection?.id) ?? null)
      : null
  );

  function applySchematic(next: Schematic): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const derived = deriveNetlist(next);
    projectStore.document = {
      ...doc,
      schematic: next,
      components: derived.components,
      nets: derived.nets,
      layout: pruneLayout(doc.layout, derived)
    };
  }

  function placeSymbol(footprintId: string, x: number, y: number): void {
    const entry = paletteEntryFor(footprintId);
    const pinOffsets = projectStore.footprints[footprintId]?.pinOffsets;
    if (entry === undefined || pinOffsets === undefined) {
      saveError = `Unknown footprint ${footprintId}`;
      return;
    }
    const pins = Object.keys(pinOffsets).sort((a, b) => Number(a) - Number(b));
    const existingIds = currentSchematic.nodes.map((n) => n.id);
    const existingRefs = currentSchematic.nodes
      .filter((n): n is Extract<SchematicNode, { kind: 'symbol' }> => n.kind === 'symbol')
      .map((n) => n.ref);
    const node: SchematicNode = {
      kind: 'symbol',
      id: nextNodeId('sym', existingIds),
      ref: nextRef(entry.refPrefix, existingRefs),
      value: entry.defaultValue,
      footprintId,
      pins,
      x,
      y,
      rotation: 0
    };
    applySchematic({ ...currentSchematic, nodes: [...currentSchematic.nodes, node] });
    armedFootprintId = null;
  }

  function placePort(portKind: SchematicPortKind, x: number, y: number): void {
    const entry = PORT_PALETTE.find((p) => p.portKind === portKind);
    if (entry === undefined) return;
    const existingIds = currentSchematic.nodes.map((n) => n.id);
    const node: SchematicNode = {
      kind: 'port',
      id: nextNodeId('port', existingIds),
      portKind,
      netName: entry.defaultNetName,
      x,
      y,
      rotation: 0
    };
    applySchematic({ ...currentSchematic, nodes: [...currentSchematic.nodes, node] });
    armedPortKind = null;
  }

  function moveNode(nodeId: string, x: number, y: number): void {
    applySchematic({
      ...currentSchematic,
      nodes: currentSchematic.nodes.map((n) => (n.id === nodeId ? { ...n, x, y } : n))
    });
  }

  function rotateNode(nodeId: string): void {
    const orientations: Orientation[] = [0, 90, 180, 270];
    applySchematic({
      ...currentSchematic,
      nodes: currentSchematic.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const idx = orientations.indexOf(n.rotation);
        return { ...n, rotation: orientations[(idx + 1) % orientations.length] };
      })
    });
  }

  function setNodeRef(nodeId: string, ref: string): void {
    applySchematic({
      ...currentSchematic,
      nodes: currentSchematic.nodes.map((n) => (n.id === nodeId && n.kind === 'symbol' ? { ...n, ref } : n))
    });
  }

  function setNodeValue(nodeId: string, value: string | null): void {
    applySchematic({
      ...currentSchematic,
      nodes: currentSchematic.nodes.map((n) => (n.id === nodeId && n.kind === 'symbol' ? { ...n, value } : n))
    });
  }

  function setPortNetName(nodeId: string, netName: string): void {
    applySchematic({
      ...currentSchematic,
      nodes: currentSchematic.nodes.map((n) => (n.id === nodeId && n.kind === 'port' ? { ...n, netName } : n))
    });
  }

  function deleteSchematicNode(nodeId: string): void {
    applySchematic({
      ...currentSchematic,
      nodes: currentSchematic.nodes.filter((n) => n.id !== nodeId),
      connections: currentSchematic.connections.filter(
        (c) => c.a.nodeId !== nodeId && c.b.nodeId !== nodeId
      )
    });
    schematicSelection = null;
  }

  function connectEndpoints(a: SchematicEndpoint, b: SchematicEndpoint): void {
    if (a.nodeId === b.nodeId && a.pin === b.pin) return;
    const exists = currentSchematic.connections.some(
      (c) =>
        (c.a.nodeId === a.nodeId && c.a.pin === a.pin && c.b.nodeId === b.nodeId && c.b.pin === b.pin) ||
        (c.a.nodeId === b.nodeId && c.a.pin === b.pin && c.b.nodeId === a.nodeId && c.b.pin === a.pin)
    );
    if (exists) return;
    const id = nextNodeId('w', currentSchematic.connections.map((c) => c.id));
    applySchematic({ ...currentSchematic, connections: [...currentSchematic.connections, { id, a, b }] });
  }

  function deleteSchematicConnection(connectionId: string): void {
    applySchematic({
      ...currentSchematic,
      connections: currentSchematic.connections.filter((c) => c.id !== connectionId)
    });
    schematicSelection = null;
  }

  function onSchematicSelect(kind: 'node' | 'connection' | null, id: string | null): void {
    schematicSelection = kind !== null && id !== null ? { kind, id } : null;
  }

  function onSchematicDelete(kind: 'node' | 'connection', id: string): void {
    if (kind === 'node') deleteSchematicNode(id);
    else deleteSchematicConnection(id);
  }

  function setSelectedNet(netId: string | null): void {
    selectedNetId = netId;
    projectStore.setSelection(netId === null ? { kind: null, id: null } : { kind: 'net', id: netId });
  }

  function upsertNetOverride(netId: string, patch: { netClass?: NetClass; priority?: number }): void {
    const doc = projectStore.document;
    if (doc === null) return;
    const net = doc.nets.find((n) => n.id === netId);
    if (net === undefined) return;
    const existing = currentSchematic.netOverrides.find((o) => o.netName === net.name);
    const nextOverride = {
      netName: net.name,
      netClass: patch.netClass ?? existing?.netClass ?? net.netClass,
      priority: patch.priority ?? existing?.priority ?? net.priority
    };
    const netOverrides = existing
      ? currentSchematic.netOverrides.map((o) => (o.netName === net.name ? nextOverride : o))
      : [...currentSchematic.netOverrides, nextOverride];
    applySchematic({ ...currentSchematic, netOverrides });
  }

  function changeNetClass(netId: string, netClass: NetClass): void {
    const doc = projectStore.document;
    if (doc === null) return;
    if (doc.schematic !== null) {
      upsertNetOverride(netId, { netClass });
      return;
    }
    const nextDoc: ProjectDocument = {
      ...doc,
      nets: doc.nets.map((n) => (n.id === netId ? { ...n, netClass } : n))
    };
    projectStore.document = nextDoc;
  }

  function changePriority(netId: string, priority: number): void {
    const doc = projectStore.document;
    if (doc === null) return;
    if (doc.schematic !== null) {
      upsertNetOverride(netId, { priority });
      return;
    }
    const nextDoc: ProjectDocument = {
      ...doc,
      nets: doc.nets.map((n) => (n.id === netId ? { ...n, priority } : n))
    };
    projectStore.document = nextDoc;
  }


  async function startOperation(operation: SolverOperation): Promise<void> {
    const doc = projectStore.document;
    if (doc === null) return;
    if (operation === 'validate') {
      await runValidate();
      return;
    }
    const resolvedOperation: SolverOperation =
      projectStore.boardKind === 'perfboard'
        ? operation === 'route'
          ? 'trace-route'
          : operation === 'solve'
            ? 'trace-solve'
            : operation === 'place'
              ? 'trace-place'
              : operation
        : operation;
    try {
      const seed = doc.settings.seed;
      const preset = doc.settings.solverPreset;
      const job = await createJob(params.id, resolvedOperation, {
        seed,
        options: {
          seed,
          preset: preset as 'fast' | 'balanced' | 'quality',
          placementWeights: doc.settings.placementWeights,
          routingWeights: doc.settings.routingWeights,
          allowCriticalNetClasses: doc.settings.allowCriticalNetClasses,
          placementTimeLimitMs: doc.settings.placementTimeLimitMs,
          placementSolutionCount: doc.settings.placementSolutionCount
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
    if ('jumpers' in result.layout) {
      projectStore.applyLayoutMutation(result.layout);
    } else {
      projectStore.applyTraceLayout(result.layout);
    }
    projectStore.diagnostics = result.diagnostics;
    projectStore.score = result.score;
    projectStore.clearJob();
    void runValidate();
  }

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

  function onSelect(kind: 'component' | 'jumper' | 'trace', id: string): void {
    projectStore.setSelection({ kind, id });
  }

  const canvasSelectionId = $derived(
    projectStore.selection.kind === 'component' ||
      projectStore.selection.kind === 'jumper' ||
      projectStore.selection.kind === 'trace'
      ? projectStore.selection.id
      : null
  );
  const canvasSelectionKind = $derived<'component' | 'jumper' | 'trace' | null>(
    projectStore.selection.kind === 'component' ||
      projectStore.selection.kind === 'jumper' ||
      projectStore.selection.kind === 'trace'
      ? projectStore.selection.kind
      : null
  );

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

  // Derived status for the bottom status bar.
  const boardKindLabel = $derived(projectStore.boardKind === 'perfboard' ? 'Perfboard' : 'Breadboard');
  const placedCount = $derived(projectStore.document?.layout.placements.length ?? 0);
  // Placements always come from the document (both board families, persisted by
  // autosave); a perfboard's traces/vias come from the last applied trace job, which is
  // store-only until the next trace-solve/trace-route job overwrites it.
  const boardLayout = $derived.by((): Layout | TraceLayout | undefined => {
    const doc = projectStore.document;
    if (doc === null) return undefined;
    if (projectStore.boardKind !== 'perfboard') return doc.layout;
    const solved = projectStore.traceLayout;
    return {
      version: 1,
      boardId: doc.board.modelId,
      placements: doc.layout.placements,
      traces: solved?.traces ?? [],
      vias: solved?.vias ?? []
    };
  });
  const totalCount = $derived(projectStore.document?.components.length ?? 0);
  const jumperCount = $derived(
    projectStore.boardKind === 'perfboard'
      ? (projectStore.traceLayout?.traces.length ?? 0)
      : (projectStore.document?.layout.jumpers.length ?? 0)
  );
  const errorCount = $derived(projectStore.diagnostics.filter((d) => d.severity === 'error').length);
  const warningCount = $derived(projectStore.diagnostics.filter((d) => d.severity === 'warning').length);

  const diagnosticsBanner = $derived.by(() => {
    if (validatingNow) return { tone: 'pending', text: 'Verifying topology…' };
    if (lastValidateError !== null) return { tone: 'error', text: lastValidateError };
    if (errorCount > 0) return { tone: 'error', text: `${errorCount} open circuit error${errorCount === 1 ? '' : 's'}` };
    if (warningCount > 0) return { tone: 'warning', text: `${warningCount} warning${warningCount === 1 ? '' : 's'}` };
    if (projectStore.score !== null) return { tone: 'ok', text: 'Topology valid' };
    return { tone: 'idle', text: 'Idle — make a change to verify' };
  });

  // Accordion: open whichever panel has the most actionable state on first
  // load. After that the user drives it. We deliberately only seed once —
  // re-opening diagnostics after a transient warning clears shouldn't yank
  // the user back out of whatever they were reading.
  $effect(() => {
    if (panelInitialised) return;
    if (errorCount > 0 || warningCount > 0) {
      openPanel = 'diagnostics';
    } else if (projectStore.score !== null) {
      openPanel = 'layout';
    } else {
      openPanel = 'nets';
    }
    panelInitialised = true;
  });
</script>

<section class="editor">
  <!-- ====================== Header strip =========================== -->
  <header class="ed-header">
    <div class="ed-header-left">
      <a href="/" class="back-link">
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M7.5 2L3.5 6l4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        Projects
      </a>
      <div class="ed-title-block">
        <span class="ed-kind mono">{boardKindLabel}</span>
        <h1 class="ed-title">{projectStore.document?.name ?? params.id}</h1>
      </div>
    </div>

    <div class="ed-header-right">
      <div class="view-tabs" role="tablist" aria-label="Editor view">
        <button
          type="button"
          role="tab"
          aria-selected={viewMode === 'schematic'}
          class:active={viewMode === 'schematic'}
          onclick={() => {
            viewMode = 'schematic';
            // Default open Components every time the user enters schematic mode.
            // Properties stays collapsed until the user picks a node — it shows
            // an empty inspector otherwise.
            openSchematicPanel = 'components';
          }}
        >
          Schematic
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={viewMode === 'board'}
          class:active={viewMode === 'board'}
          onclick={() => {
            viewMode = 'board';
            // Don't reset `openPanel` here — the seed effect runs once on first
            // load. Subsequent board visits honour the user's last choice.
          }}
        >
          Board
        </button>
      </div>
      <span
        class="save-status mono"
        data-tone={saveState === 'error' ? 'error' : 'idle'}
      >
        {saveState === 'saving' ? 'Saving…' : saveState === 'error' ? (saveError ?? 'Save failed.') : 'Saved'}
      </span>
      {#if viewMode === 'board'}
        <button
          type="button"
          class="tool-button"
          class:active={jumperToolActive}
          aria-pressed={jumperToolActive}
          onclick={() => (jumperToolActive = !jumperToolActive)}
          title="Click two holes to create a wire (Esc to cancel)"
        >
          <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
            <path d="M2 6.5h9M6.5 2v9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          <span>{jumperToolActive ? 'Exit jumper' : 'Jumper tool'}</span>
        </button>
      {/if}
    </div>
  </header>

  <!-- ====================== Toolbar =========================== -->
  <Toolbar
    disabled={(projectStore.document?.components.length ?? 0) === 0}
    showValidate={projectStore.boardKind !== 'perfboard'}
    showOptimize={projectStore.boardKind !== 'perfboard'}
    onAutoPlace={() => void startOperation('place')}
    onAutoRoute={() => void startOperation('route')}
    onSolve={() => void startOperation('solve')}
    onValidate={() => void startOperation('validate')}
    onOptimize={() => void startOperation('optimize')}
  />

  <!-- ====================== Job progress (compact ribbon) =========================== -->
  <JobProgress
    jobId={projectStore.jobId}
    onApply={onApplySolverResult}
    onJobUpdate={(job) => {
      if (typeof job.resultLayoutId === 'string') {
        lastResultLayoutId = job.resultLayoutId;
      }
    }}
  />

  <!-- ====================== Body grid: canvas | sidebar =========================== -->
  {#if loadError}
    <div class="ed-error">
      <strong>Couldn't load project.</strong>
      <span>{loadError}</span>
    </div>
  {:else if isLoading}
    <div class="ed-loading">Loading project…</div>
  {:else if projectStore.board && projectStore.document}
    <div class="ed-body">
      <div class="canvas-stage">
        <div class="canvas-frame">
          {#if viewMode === 'schematic'}
            <SchematicCanvas
              schematic={currentSchematic}
              selectedKind={schematicSelection?.kind ?? null}
              selectedId={schematicSelection?.id ?? null}
              armedFootprintId={armedFootprintId}
              armedPortKind={armedPortKind}
              onSelect={onSchematicSelect}
              onNodeMove={moveNode}
              onNodeRotate={rotateNode}
              onDelete={onSchematicDelete}
              onConnect={connectEndpoints}
              onPlaceSymbol={placeSymbol}
              onPlacePort={placePort}
            />
          {:else}
            <BoardCanvas
              board={projectStore.board}
              layout={boardLayout}
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
          {/if}
        </div>
      </div>

      <aside class="ed-sidebar" aria-label="Project sidebar">
        {#if viewMode === 'schematic'}
          <Panel
            title="Components"
            open={openSchematicPanel === 'components'}
            onToggle={() => (openSchematicPanel = openSchematicPanel === 'components' ? null : 'components')}
          >
            <SymbolPalette
              armedFootprintId={armedFootprintId}
              armedPortKind={armedPortKind}
              onArmSymbol={(id) => {
                armedFootprintId = armedFootprintId === id ? null : id;
                armedPortKind = null;
              }}
              onArmPort={(kind) => {
                armedPortKind = armedPortKind === kind ? null : kind;
                armedFootprintId = null;
              }}
            />
          </Panel>

          <Panel
            title="Properties"
            open={openSchematicPanel === 'properties'}
            onToggle={() => (openSchematicPanel = openSchematicPanel === 'properties' ? null : 'properties')}
          >
            {#snippet meta()}
              {#if selectedSchematicNode}
                <span class="panel-meta mono">{selectedSchematicNode.kind === 'symbol' ? (selectedSchematicNode as { ref: string }).ref : '—'}</span>
              {/if}
            {/snippet}
            <SchematicInspector
              node={selectedSchematicNode}
              takenRefs={currentSchematic.nodes
                .filter((n) => n.kind === 'symbol' && n.id !== selectedSchematicNode?.id)
                .map((n) => (n as { ref: string }).ref)}
              onRefChange={setNodeRef}
              onValueChange={setNodeValue}
              onNetNameChange={setPortNetName}
              onRotate={rotateNode}
              onDelete={deleteSchematicNode}
            />
          </Panel>
        {:else}
          <Panel
            title="Layout readout"
            open={openPanel === 'layout'}
            onToggle={() => (openPanel = openPanel === 'layout' ? null : 'layout')}
          >
            <MetricsBar score={projectStore.score} />
          </Panel>
        {/if}

        <Panel
          title="Nets"
          open={openPanel === 'nets'}
          onToggle={() => (openPanel = openPanel === 'nets' ? null : 'nets')}
        >
          {#snippet meta()}
            <span class="panel-meta mono">{projectStore.document.nets.length}</span>
          {/snippet}
          <NetPanel
            nets={projectStore.document.nets}
            selectedNetId={selectedNetId}
            onSelectNet={setSelectedNet}
            onChangeNetClass={changeNetClass}
            onChangePriority={changePriority}
          />
        </Panel>

        <Panel
          title="Diagnostics"
          open={openPanel === 'diagnostics'}
          onToggle={() => (openPanel = openPanel === 'diagnostics' ? null : 'diagnostics')}
        >
          {#snippet meta()}
            <span
              class="panel-meta mono"
              class:has-error={errorCount > 0}
              class:has-warning={errorCount === 0 && warningCount > 0}
            >
              {errorCount > 0 ? errorCount : warningCount > 0 ? `!${warningCount}` : '✓'}
            </span>
          {/snippet}
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
        </Panel>

        {#if projectStore.document.settings !== undefined}
          <Panel
            title="Advanced settings"
            open={openPanel === 'advanced'}
            onToggle={() => (openPanel = openPanel === 'advanced' ? null : 'advanced')}
          >
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
          </Panel>
        {/if}

        {#if viewMode === 'board'}
          <Panel
            title="Export"
            open={openPanel === 'export'}
            onToggle={() => (openPanel = openPanel === 'export' ? null : 'export')}
          >
            <ExportMenu layoutId={lastResultLayoutId} boardKind={projectStore.boardKind} />
          </Panel>
        {/if}

        <SafetyNotice />
      </aside>
    </div>

    <!-- ====================== Status bar =========================== -->
    <footer class="status-bar" role="status" aria-live="polite">
      <span class="status-segment mono">
        <span class="status-label">board</span>
        <span class="status-value">{boardKindLabel.toLowerCase()}</span>
      </span>
      <span class="status-segment mono">
        <span class="status-label">placed</span>
        <span class="status-value">{placedCount}/{totalCount}</span>
      </span>
      <span class="status-segment mono">
        <span class="status-label">wires</span>
        <span class="status-value">{jumperCount}</span>
      </span>
      <span class="status-segment" data-tone={diagnosticsBanner.tone}>
        <span class="status-dot" aria-hidden="true"></span>
        <span class="status-text">{diagnosticsBanner.text}</span>
      </span>
    </footer>
  {/if}
</section>

<style>
  .editor {
    display: grid;
    grid-template-rows: auto auto auto minmax(0, 1fr) auto;
    flex: 1;
    min-height: 0;
    background: var(--paper-1);
  }

  /* ----- Header strip ----- */
  .ed-header {
    grid-row: 1;
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: 10px 18px 8px;
    background: var(--paper-2);
    border-bottom: 1px solid var(--paper-edge);
  }

  .editor > :global(.toolbar) {
    grid-row: 2;
  }

  .editor > :global(.job-progress) {
    grid-row: 3;
  }

  .ed-header-left {
    display: flex;
    align-items: center;
    gap: var(--sp-4);
    min-width: 0;
  }

  .ed-header-right {
    margin-left: auto;
    display: flex;
    gap: var(--sp-2);
    align-items: center;
  }

  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border-radius: var(--r-2);
    color: var(--ink-2);
    font-size: var(--fs-13);
    text-decoration: none;
    transition: background-color var(--dur) var(--ease-out), color var(--dur) var(--ease-out);
  }

  .back-link:hover {
    background: var(--paper-3);
    color: var(--ink-1);
    text-decoration: none;
  }

  .ed-title-block {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
  }

  .ed-kind {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-3);
    padding: 2px 6px;
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-1);
    background: var(--paper-1);
  }

  .ed-title {
    font-size: var(--fs-17);
    font-weight: 600;
    color: var(--ink-1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 38ch;
  }

  .tool-button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    font-size: var(--fs-13);
  }

  .tool-button.active {
    background: var(--accent-1);
    border-color: var(--accent-1);
    color: #fff;
  }

  .tool-button.active:hover {
    background: var(--accent-3);
    border-color: var(--accent-3);
  }

  .view-tabs {
    display: inline-flex;
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    overflow: hidden;
  }

  .view-tabs button {
    padding: 6px 12px;
    font-size: var(--fs-13);
    color: var(--ink-2);
    background: var(--paper-1);
    border: none;
    border-right: 1px solid var(--paper-edge);
    cursor: pointer;
  }

  .view-tabs button:last-child {
    border-right: none;
  }

  .view-tabs button:hover {
    background: var(--paper-3);
    color: var(--ink-1);
  }

  .view-tabs button.active {
    background: var(--accent-1);
    color: #fff;
  }

  .save-status {
    font-size: var(--fs-11);
    color: var(--ink-3);
  }

  .save-status[data-tone='error'] {
    color: var(--sev-error);
    font-weight: 600;
  }

  /* ----- Body grid ----- */
  .ed-body {
    grid-row: 4;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: var(--sp-3);
    padding: var(--sp-3);
    min-height: 0;
    overflow: hidden;
  }

  .canvas-stage {
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    border-radius: var(--r-3);
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    box-shadow: var(--sh-1);
    display: flex;
  }

  .canvas-frame {
    flex: 1;
    min-height: 0;
    display: flex;
  }

  .canvas-frame :global(.board-canvas) {
    flex: 1;
    width: 100%;
    height: 100%;
    cursor: grab;
  }

  .canvas-frame :global(.board-canvas:active) {
    cursor: grabbing;
  }

  .canvas-frame :global(.schematic-canvas) {
    flex: 1;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
  }

  .ed-sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    overflow-y: auto;
    padding-right: 4px;
  }

  .panel {
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-3);
    box-shadow: var(--sh-1);
    overflow: hidden;
  }

  .panel-header {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 8px 12px;
    background: var(--paper-2);
    border-bottom: 1px solid var(--paper-edge);
  }

  .panel-header h2 {
    font-size: var(--fs-11);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-2);
    flex: 1;
  }

  .panel-meta {
    font-size: var(--fs-11);
    color: var(--ink-3);
    padding: 1px 6px;
    border-radius: var(--r-1);
    background: var(--paper-1);
    border: 1px solid var(--paper-edge);
  }

  .panel-meta.has-error {
    color: var(--sev-error);
    background: var(--sev-error-soft);
    border-color: var(--sev-error-line);
  }

  .panel-meta.has-warning {
    color: var(--sev-warning);
    background: var(--sev-warning-soft);
    border-color: var(--sev-warning-line);
  }

  .panel :global(section) {
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
  }

  .panel :global(.advanced-panel) {
    border: none;
    border-radius: 0;
    box-shadow: none;
    background: transparent;
    padding: var(--sp-3);
  }

  .panel :global(.export-menu) {
    padding: var(--sp-3);
  }

  .panel :global(.metrics-bar) {
    border: none;
    border-radius: 0;
    box-shadow: none;
    background: transparent;
    padding: var(--sp-3);
  }

  .panel :global(.net-panel) {
    padding: var(--sp-2) 0;
  }

  .panel :global(.diagnostics-panel) {
    padding: var(--sp-2) 0;
  }

  .panel :global(.safety-notice) {
    border-radius: 0;
    border-left: none;
    border-right: none;
    border-bottom: none;
    background: var(--sev-warning-soft);
    padding: var(--sp-3);
    font-size: var(--fs-12);
  }

  /* ----- Status bar ----- */
  .status-bar {
    grid-row: 5;
    display: flex;
    align-items: center;
    gap: 0;
    height: 30px;
    padding: 0 18px;
    background: var(--paper-2);
    border-top: 1px solid var(--paper-edge);
    font-size: var(--fs-11);
    color: var(--ink-2);
  }

  .status-segment {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 12px;
    height: 100%;
    border-right: 1px solid var(--paper-edge);
  }

  .status-segment:last-child {
    border-right: none;
  }

  .status-segment.mono {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
  }

  .status-label {
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-4);
    font-size: 10px;
  }

  .status-value {
    color: var(--ink-1);
    font-weight: 500;
  }

  .status-segment[data-tone='error'] {
    color: var(--sev-error);
  }
  .status-segment[data-tone='error'] .status-text {
    font-weight: 600;
  }
  .status-segment[data-tone='warning'] {
    color: var(--sev-warning);
  }
  .status-segment[data-tone='warning'] .status-text {
    font-weight: 600;
  }
  .status-segment[data-tone='ok'] .status-text {
    color: var(--ok);
    font-weight: 600;
  }
  .status-segment[data-tone='pending'] .status-text {
    color: var(--ink-2);
  }
  .status-segment[data-tone='idle'] .status-text {
    color: var(--ink-3);
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
  }

  .status-segment:last-child {
    margin-left: auto;
    border-right: none;
  }

  /* ----- States ----- */
  .ed-loading,
  .ed-error {
    grid-row: 4;
    padding: var(--sp-6);
    color: var(--ink-3);
    text-align: center;
    font-size: var(--fs-14);
  }

  .ed-error {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: center;
    color: var(--sev-error);
  }

  .ed-error span {
    color: var(--ink-3);
  }

  /* Responsive — collapse the sidebar below 960 px so the canvas stays
     usable on a small laptop or tablet. The status bar segments wrap. */
  @media (max-width: 960px) {
    .ed-body {
      grid-template-columns: 1fr;
    }

    .ed-sidebar {
      max-height: none;
    }
  }
</style>