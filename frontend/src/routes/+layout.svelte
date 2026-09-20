<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';

  type Props = { children: Snippet };
  let { children }: Props = $props();
</script>

<div class="app-shell">
  <header class="app-header">
    <a href="/" class="brand">AutoBreadboard</a>
  </header>
  <main class="app-main">
    {@render children()}
  </main>
</div>

<style>
  .app-shell {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .app-header {
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--color-border);
    background: var(--color-surface);
  }

  .brand {
    font-weight: 700;
    font-size: 16px;
    color: var(--color-fg);
  }

  .app-main {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
</style>