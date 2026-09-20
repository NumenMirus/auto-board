<script lang="ts">
  // Safety notice — kept tight and unobtrusive. The warning sign is
  // intentionally amber (not red) because breadboard mistakes are
  // recoverable; red would imply the layout is already dangerous.
</script>

<aside class="safety-notice" role="note">
  <span class="icon" aria-hidden="true">
    <svg width="14" height="14" viewBox="0 0 14 14">
      <path
        d="M7 1.5 L12.5 12 L1.5 12 Z"
        fill="none"
        stroke="currentColor"
        stroke-width="1.4"
        stroke-linejoin="round"
      />
      <line x1="7" y1="5.5" x2="7" y2="8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      <circle cx="7" cy="10.4" r="0.7" fill="currentColor" />
    </svg>
  </span>
  <div>
    <p class="title">Low-voltage prototyping only</p>
    <p class="body">
      Breadboards are for low-voltage, low-energy prototypes. Verify current
      limits, polarity, and isolation before powering the circuit.
    </p>
  </div>
</aside>

<style>
  .safety-notice {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: var(--sp-3);
    background: var(--sev-warning-soft);
    border: 1px solid var(--sev-warning-line);
    border-radius: var(--r-2);
    color: var(--ink-1);
    font-size: var(--fs-12);
    line-height: 1.4;
  }

  .icon {
    color: var(--sev-warning);
    flex-shrink: 0;
    margin-top: 2px;
  }

  .title {
    margin: 0;
    font-weight: 600;
    color: var(--sev-warning);
    font-size: var(--fs-12);
  }

  .body {
    margin: 2px 0 0;
    color: var(--ink-2);
    font-size: var(--fs-11);
  }
</style>