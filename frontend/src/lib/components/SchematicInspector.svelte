<script lang="ts">
  import type { SchematicNode } from '$lib/types';

  type Props = {
    node: SchematicNode | null;
    takenRefs: string[];
    netNameConflict?: boolean;
    onRefChange?: ((nodeId: string, ref: string) => void) | undefined;
    onValueChange?: ((nodeId: string, value: string | null) => void) | undefined;
    onNetNameChange?: ((nodeId: string, netName: string) => void) | undefined;
    onRotate?: ((nodeId: string) => void) | undefined;
    onDelete?: ((nodeId: string) => void) | undefined;
  };
  let {
    node,
    takenRefs,
    netNameConflict = false,
    onRefChange = undefined,
    onValueChange = undefined,
    onNetNameChange = undefined,
    onRotate = undefined,
    onDelete = undefined
  }: Props = $props();

  // Local edit buffer — must NOT bind the input directly to the prop, because
  // we validate before committing (empty / duplicate refs, etc.). Re-seed via
  // the effect below whenever the selected node changes.
  let refDraft = $state('');
  let valueDraft = $state('');
  let netNameDraft = $state('');
  let refError = $state<string | null>(null);
  let netNameError = $state<string | null>(null);

  $effect(() => {
    // Re-seed on every node.id transition (including null → id and id → null).
    // Read node.id, node.ref, node.value, node.netName, node.kind so the effect
    // re-runs whenever the selection or any of these fields changes externally
    // (e.g. another handler committed a ref change upstream).
    if (node === null) {
      refDraft = '';
      valueDraft = '';
      netNameDraft = '';
      refError = null;
      netNameError = null;
      return;
    }
    void node.id;
    void node.kind;
    if (node.kind === 'symbol') {
      refDraft = node.ref;
      valueDraft = node.value ?? '';
      refError = null;
      // port fields cleared — defensive, in case the prior selection was a port
      netNameDraft = '';
      netNameError = null;
    } else {
      netNameDraft = node.netName;
      netNameError = null;
      // symbol fields cleared
      refDraft = '';
      valueDraft = '';
      refError = null;
    }
  });

  function commitRef(): void {
    if (node === null || node.kind !== 'symbol') return;
    const candidate = refDraft.trim();
    if (candidate === '') {
      refDraft = node.ref;
      refError = 'Reference cannot be empty';
      return;
    }
    if (candidate !== node.ref && takenRefs.includes(candidate)) {
      refDraft = node.ref;
      refError = `${candidate} is already used`;
      return;
    }
    refError = null;
    onRefChange?.(node.id, candidate);
  }

  function commitValue(): void {
    if (node === null || node.kind !== 'symbol') return;
    const trimmed = valueDraft.trim();
    if (trimmed === '') {
      onValueChange?.(node.id, null);
    } else {
      onValueChange?.(node.id, trimmed);
    }
  }

  function commitNetName(): void {
    if (node === null || node.kind !== 'port') return;
    const candidate = netNameDraft.trim();
    if (candidate === '') {
      netNameDraft = node.netName;
      netNameError = 'Net name cannot be empty';
      return;
    }
    netNameError = null;
    onNetNameChange?.(node.id, candidate);
  }
</script>

<section class="inspector" aria-label="Properties">
  {#if node === null}
    <p class="empty mono">Select a symbol to edit its reference and value.</p>
  {:else if node.kind === 'symbol'}
    <div class="fields">
      <div class="field">
        <span class="field-label">Footprint</span>
        <span class="field-readout mono">{node.footprintId}</span>
      </div>
      <label class="field">
        <span class="field-label">Ref</span>
        <input
          type="text"
          class="mono"
          bind:value={refDraft}
          onchange={commitRef}
          onblur={commitRef}
          aria-label="Reference designator"
        />
      </label>
      {#if refError !== null}
        <p class="field-error" role="alert">{refError}</p>
      {/if}
      <label class="field">
        <span class="field-label">Value</span>
        <input
          type="text"
          class="mono"
          bind:value={valueDraft}
          onchange={commitValue}
          onblur={commitValue}
          aria-label="Component value"
        />
      </label>
      <div class="field">
        <span class="field-label">Pins</span>
        <span class="field-readout mono">{node.pins.length} pins</span>
      </div>
    </div>
    <div class="actions">
      <button type="button" class="tool-btn" onclick={() => onRotate?.(node.id)}>
        Rotate
      </button>
      <button
        type="button"
        class="tool-btn danger"
        onclick={() => onDelete?.(node.id)}
      >
        Delete
      </button>
    </div>
  {:else}
    <div class="fields">
      <div class="field">
        <span class="field-label">Port kind</span>
        <span class="field-readout mono">{node.portKind}</span>
      </div>
      <label class="field">
        <span class="field-label">Net name</span>
        <input
          type="text"
          class="mono"
          bind:value={netNameDraft}
          onchange={commitNetName}
          onblur={commitNetName}
          aria-label="Net name"
        />
      </label>
      {#if netNameError !== null}
        <p class="field-error" role="alert">{netNameError}</p>
      {/if}
      {#if netNameConflict}
        <p class="field-warning" role="status">
          Conflicting net labels on this net — the lowest name wins.
        </p>
      {/if}
    </div>
    <div class="actions">
      <button type="button" class="tool-btn" onclick={() => onRotate?.(node.id)}>
        Rotate
      </button>
      <button
        type="button"
        class="tool-btn danger"
        onclick={() => onDelete?.(node.id)}
      >
        Delete
      </button>
    </div>
  {/if}
</section>

<style>
  .inspector {
    font-size: var(--fs-12);
    padding: var(--sp-3);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }

  .empty {
    color: var(--ink-3);
    font-style: italic;
    margin: 0;
  }

  .fields {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }

  .field {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    font-size: var(--fs-13);
  }

  .field-label {
    flex: 0 0 96px;
    color: var(--ink-3);
    font-weight: 500;
  }

  .field input {
    flex: 1;
    min-width: 0;
  }

  .field-readout {
    flex: 1;
    color: var(--ink-1);
    padding: 4px 8px;
    background: var(--paper-2);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    font-size: var(--fs-12);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .field-error {
    margin: 0;
    font-size: var(--fs-12);
    color: var(--sev-error);
  }

  .field-warning {
    margin: 0;
    font-size: var(--fs-12);
    color: var(--sev-warning);
  }

  .actions {
    display: flex;
    gap: var(--sp-2);
  }

  .tool-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 12px;
    background: var(--paper-0);
    color: var(--ink-1);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    font-size: var(--fs-13);
    font-weight: 500;
    transition:
      background-color 120ms cubic-bezier(0.16, 1, 0.3, 1),
      border-color 120ms cubic-bezier(0.16, 1, 0.3, 1),
      color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .tool-btn:hover:not(:disabled) {
    background: var(--paper-2);
    border-color: var(--ink-3);
  }

  .tool-btn:active:not(:disabled) {
    background: var(--paper-3);
  }

  .tool-btn.danger {
    color: var(--sev-error);
    border-color: var(--sev-error-soft, var(--paper-edge));
  }

  .tool-btn.danger:hover:not(:disabled) {
    background: var(--sev-error-soft, var(--paper-2));
    border-color: var(--sev-error);
  }
</style>