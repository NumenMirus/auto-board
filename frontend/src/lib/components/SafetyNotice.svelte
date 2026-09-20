<script lang="ts">
  // No props — this banner is identical on every project page.
</script>

<aside class="safety-notice" role="note">
  <span class="icon" aria-hidden="true">⚠</span>
  <p>
    La breadboard è destinata a prototipi a bassa tensione e bassa energia.
    Verificare limiti di corrente, polarità, tensioni e sicurezza prima di
    alimentare il circuito.
  </p>
</aside>

<style>
  .safety-notice {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: rgba(217, 119, 6, 0.1);
    border-left: 3px solid var(--color-warning);
    border-radius: var(--radius-sm);
    color: var(--color-fg);
    font-size: 12px;
  }

  .icon {
    font-size: 16px;
    color: var(--color-warning);
  }

  p {
    margin: 0;
    line-height: 1.4;
  }
</style>