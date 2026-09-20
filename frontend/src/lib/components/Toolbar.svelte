<script lang="ts">
  type Props = {
    onAutoPlace?: (() => void) | undefined;
    onAutoRoute?: (() => void) | undefined;
    onSolve?: (() => void) | undefined;
    onValidate?: (() => void) | undefined;
    onOptimize?: (() => void) | undefined;
    disabled?: boolean;
  };
  let {
    onAutoPlace = undefined,
    onAutoRoute = undefined,
    onSolve = undefined,
    onValidate = undefined,
    onOptimize = undefined,
    disabled = false
  }: Props = $props();
</script>

<nav class="toolbar" aria-label="Solver actions">
  <button type="button" disabled={disabled} onclick={() => onAutoPlace?.()}>
    Auto-place
  </button>
  <button type="button" disabled={disabled} onclick={() => onAutoRoute?.()}>
    Auto-route
  </button>
  <button type="button" disabled={disabled} onclick={() => onSolve?.()}>
    Solve
  </button>
  <button type="button" disabled={disabled} onclick={() => onValidate?.()}>
    Validate
  </button>
  <button type="button" disabled={disabled} onclick={() => onOptimize?.()}>
    Optimize
  </button>
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