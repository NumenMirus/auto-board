<script lang="ts">
  type Props = {
    onAutoPlace?: (() => void) | undefined;
    onAutoRoute?: (() => void) | undefined;
    onSolve?: (() => void) | undefined;
    onValidate?: (() => void) | undefined;
    onOptimize?: (() => void) | undefined;
    disabled?: boolean;
    // Perfboard has no separate placement phase, no synchronous validator,
    // and no routing-feedback optimize pass yet — the editor page hides
    // those buttons entirely for perfboard rather than shipping controls
    // that silently do nothing when clicked.
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
    <button type="button" disabled={disabled} onclick={() => onAutoPlace?.()}>
      Auto-place
    </button>
  {/if}
  <button type="button" disabled={disabled} onclick={() => onAutoRoute?.()}>
    Auto-route
  </button>
  <button type="button" disabled={disabled} onclick={() => onSolve?.()}>
    Solve
  </button>
  {#if showValidate}
    <button type="button" disabled={disabled} onclick={() => onValidate?.()}>
      Validate
    </button>
  {/if}
  {#if showOptimize}
    <button type="button" disabled={disabled} onclick={() => onOptimize?.()}>
      Optimize
    </button>
  {/if}
</nav>

<style>
  .toolbar {
    display: flex;
    gap: var(--space-2);
    padding: var(--space-2);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
  }

  button {
    padding: 6px 12px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    color: var(--color-fg);
  }

  button:hover:not(:disabled) {
    background: var(--color-accent);
    color: white;
    border-color: var(--color-accent);
  }

  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
