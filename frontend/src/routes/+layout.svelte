<script lang="ts">
  import '../app.css';
  import type { Snippet } from 'svelte';

  type Props = { children: Snippet };
  let { children }: Props = $props();
</script>

<div class="app-shell">
  <header class="app-header">
    <a href="/" class="brand">AutoBoard</a>
    <nav class="app-nav">
      <a href="/docs">Docs</a>
    </nav>
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
    display: flex;
    align-items: center;
    gap: var(--space-4);
  }

  .brand {
    font-weight: 700;
    font-size: 16px;
    color: var(--color-fg);
  }

  .app-nav {
    margin-left: auto;
    display: flex;
    gap: var(--space-3);
    font-size: 14px;
  }

  .app-nav a {
    color: var(--color-muted);
  }

  .app-nav a:hover {
    color: var(--color-fg);
  }

  .app-main {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
</style>