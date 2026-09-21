/**
 * Project editor state (Svelte 5 runes).
 *
 * Lives at module scope so every component that imports it sees the same
 * reactive store. The store owns one document, one board, the footprint
 * catalog, the latest validator output, the current selection, and
 * bounded undo/redo stacks of layout snapshots.
 *
 * Undo/redo semantics (the standard editor pattern, with no caller-
 * supplied current layout):
 *   - `pushUndo(layout)` is called AFTER each mutation: the new layout
 *     becomes the "current" layout tracked by the store; the previous
 *     current is pushed onto `undoStack`. `redoStack` is cleared.
 *   - `undo()` returns the previous layout (the one just popped off
 *     `undoStack`) and pushes the store's current layout onto
 *     `redoStack`, so a subsequent `redo()` restores it.
 *   - `redo()` is the mirror.
 *
 * This means callers MUST call `pushUndo(newLayout)` after every change
 * that should be undoable. The store does not mutate the document on
 * undo/redo — it returns the layout snapshot for the caller to apply.
 */

import type {
  AnyBoardModel,
  BoardKind,
  BreadboardFootprint,
  Diagnostic,
  Layout,
  LayoutScore,
  ProjectDocument,
  TraceLayout
} from '../types';

const STACK_CAP = 100;

export type Selection =
  | { kind: 'component'; id: string }
  | { kind: 'net'; id: string }
  | { kind: 'jumper'; id: string }
  | { kind: 'trace'; id: string }
  | { kind: null; id: null };

function emptySelection(): Selection {
  return { kind: null, id: null };
}

class ProjectStore {
  document = $state<ProjectDocument | null>(null);
  draftVersion = $state<number>(1);
  board = $state<AnyBoardModel | null>(null);
  boardKind = $state<BoardKind>('breadboard');
  footprints = $state<Record<string, BreadboardFootprint>>({});
  diagnostics = $state<Diagnostic[]>([]);
  score = $state<LayoutScore | null>(null);
  selection = $state<Selection>(emptySelection());

  // Perfboard trace-solve results. Perfboard layouts aren't hand-edited
  // (traces come only from the solver) so they don't participate in the
  // breadboard undo/redo stacks below — applying a new trace-solve result
  // simply replaces this field outright.
  traceLayout = $state<TraceLayout | null>(null);

  undoStack = $state<Layout[]>([]);
  redoStack = $state<Layout[]>([]);
  // The layout most recently installed via `pushUndo`. Not read by
  // templates — kept reactive so the runes compiler treats it the same
  // way as the stacks.
  currentLayout = $state<Layout | null>(null);

  pushUndo(layout: Layout): void {
    if (this.currentLayout !== null) {
      const next = [...this.undoStack, this.currentLayout];
      if (next.length > STACK_CAP) {
        next.shift();
      }
      this.undoStack = next;
    }
    this.currentLayout = layout;
    this.redoStack = [];
  }

  undo(): Layout | undefined {
    if (this.undoStack.length === 0 || this.currentLayout === null) {
      return undefined;
    }
    const next = [...this.undoStack];
    const popped = next.pop();
    this.undoStack = next;
    if (popped !== undefined) {
      const forward: Layout[] = [...this.redoStack, this.currentLayout];
      if (forward.length > STACK_CAP) {
        forward.shift();
      }
      this.redoStack = forward;
      this.currentLayout = popped;
    }
    return popped;
  }

  redo(): Layout | undefined {
    if (this.redoStack.length === 0 || this.currentLayout === null) {
      return undefined;
    }
    const next = [...this.redoStack];
    const popped = next.pop();
    this.redoStack = next;
    if (popped !== undefined) {
      const back: Layout[] = [...this.undoStack, this.currentLayout];
      if (back.length > STACK_CAP) {
        back.shift();
      }
      this.undoStack = back;
      this.currentLayout = popped;
    }
    return popped;
  }

  clearHistory(): void {
    this.undoStack = [];
    this.redoStack = [];
    this.currentLayout = null;
  }

  setSelection(selection: Selection): void {
    this.selection = selection;
  }

  // -- Background job tracking -------------------------------------------
  // Set by the editor page when it kicks off `solve`/`route`/`place`/etc.;
  // cleared by `JobProgress.svelte` when it finishes applying (or discarding)
  // the result. The four fields stay in sync — consumers subscribe to all
  // four so that progress UIs don't miss intermediate updates from polling.
  jobId = $state<string | null>(null);
  jobStatus = $state<string | null>(null);
  jobProgressPercent = $state<number>(0);
  jobProgressPhase = $state<string | null>(null);

  // -- Atomic layout mutation --------------------------------------------
  // Pushes the current layout onto the undo stack and installs `newLayout`
  // into `document.layout`. Callers MUST NOT mutate `document.layout`
  // directly: bypassing this method leaves the undo stack out of sync with
  // what's actually on screen. The method is a no-op when there's no
  // document yet (shouldn't happen in practice — the editor page always
  // loads a document before mounting its mutation handlers).
  applyLayoutMutation(newLayout: Layout): void {
    this.pushUndo(newLayout);
    if (this.document !== null) {
      this.document = { ...this.document, layout: newLayout };
    }
    this.currentLayout = newLayout;
  }

  // Perfboard equivalent of `applyLayoutMutation`: replaces the trace layout outright (no
  // undo history — perfboard traces are re-solved from the placement, never hand-edited
  // trace-by-trace) and mirrors the new placements into `document.layout.placements` so
  // the existing document autosave effect persists them for both board families.
  applyTraceLayout(newLayout: TraceLayout): void {
    this.traceLayout = newLayout;
    if (this.document !== null) {
      this.document = {
        ...this.document,
        layout: { ...this.document.layout, placements: newLayout.placements }
      };
    }
  }

  clearJob(): void {
    this.jobId = null;
    this.jobStatus = null;
    this.jobProgressPercent = 0;
    this.jobProgressPhase = null;
  }

  setJobSnapshot(snapshot: {
    id: string;
    status: string;
    progressPercent: number;
    progressPhase: string | null;
  }): void {
    this.jobId = snapshot.id;
    this.jobStatus = snapshot.status;
    this.jobProgressPercent = snapshot.progressPercent;
    this.jobProgressPhase = snapshot.progressPhase;
  }
}

export const projectStore = new ProjectStore();