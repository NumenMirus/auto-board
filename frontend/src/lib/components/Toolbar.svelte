<script lang="ts">
  type Props = {
    onAutoPlace?: (() => void) | undefined;
    onAutoRoute?: (() => void) | undefined;
    onSolve?: (() => void) | undefined;
    onValidate?: (() => void) | undefined;
    onOptimize?: (() => void) | undefined;
    disabled?: boolean;
    showAutoPlace?: boolean;
    showValidate?: boolean;
    showOptimize?: boolean;
  };
  let {
    onAutoPlace = undefined,
    onAutoRoute = undefined,
    onSolve = undefined,
    onValidate = undefined,
    onOptimize = undefined,
    disabled = false,
    showAutoPlace = true,
    showValidate = true,
    showOptimize = true
  }: Props = $props();
</script>

<nav class="toolbar" aria-label="Solver actions">
  {#if showAutoPlace}
    <button
      type="button"
      class="tool-btn"
      disabled={disabled}
      onclick={() => onAutoPlace?.()}
      title="Place only — no jumpers"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <rect x="3" y="3" width="3" height="3" fill="currentColor" />
        <rect x="8" y="3" width="3" height="3" fill="currentColor" />
        <rect x="3" y="8" width="3" height="3" fill="currentColor" />
        <rect x="8" y="8" width="3" height="3" fill="currentColor" />
      </svg>
      <span>Place</span>
    </button>
  {/if}
  <button
    type="button"
    class="tool-btn"
    disabled={disabled}
    onclick={() => onAutoRoute?.()}
    title="Route only — keeps current placements"
  >
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M2 11 L2 4 L12 4 L12 11" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" />
    </svg>
    <span>Route</span>
  </button>
  <button
    type="button"
    class="tool-btn primary-action"
    disabled={disabled}
    onclick={() => onSolve?.()}
    title="Place + route end to end"
  >
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M2 7 L6 3 L8 5 L12 1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
      <path d="M2 7 L6 11 L8 9 L12 13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
    </svg>
    <span>Solve</span>
  </button>
  {#if showValidate}
    <button
      type="button"
      class="tool-btn"
      disabled={disabled}
      onclick={() => onValidate?.()}
      title="Run the topological verifier only"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <path d="M3 7.5 L6 10.5 L11.5 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
      </svg>
      <span>Validate</span>
    </button>
  {/if}
  {#if showOptimize}
    <button
      type="button"
      class="tool-btn"
      disabled={disabled}
      onclick={() => onOptimize?.()}
      title="Local search with routing feedback"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <path d="M7 2 L9 6 L13 7 L9 8 L7 12 L5 8 L1 7 L5 6 Z" fill="currentColor" />
      </svg>
      <span>Optimize</span>
    </button>
  {/if}

  <span class="toolbar-spacer" aria-hidden="true"></span>

  <span class="toolbar-hint mono" aria-hidden="true">
    <kbd>R</kbd> rotate · <kbd>L</kbd> lock · <kbd>Del</kbd> remove · <kbd>⌘Z</kbd> undo
  </span>
</nav>

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 18px;
    background: var(--paper-1);
    border-bottom: 1px solid var(--paper-edge);
  }

  .tool-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
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

  .tool-btn svg {
    color: var(--ink-3);
    transition: color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .tool-btn:hover:not(:disabled) {
    background: var(--paper-2);
    border-color: var(--ink-3);
  }

  .tool-btn:hover:not(:disabled) svg {
    color: var(--accent-1);
  }

  .tool-btn.primary-action {
    background: var(--accent-1);
    border-color: var(--accent-1);
    color: #fff;
  }

  .tool-btn.primary-action svg {
    color: #fff;
  }

  .tool-btn.primary-action:hover:not(:disabled) {
    background: var(--accent-3);
    border-color: var(--accent-3);
  }

  .tool-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .toolbar-spacer {
    flex: 1;
  }

  .toolbar-hint {
    font-size: var(--fs-11);
    color: var(--ink-3);
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  kbd {
    display: inline-block;
    padding: 1px 5px;
    margin: 0 1px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--ink-2);
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: 3px;
    box-shadow: 0 1px 0 var(--paper-edge);
  }
</style>