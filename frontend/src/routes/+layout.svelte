<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import type { Snippet } from 'svelte';

  type Props = { children: Snippet };
  let { children }: Props = $props();

  // Hide the chrome on the editor canvas only when the route is the project
  // editor — the editor owns its own full-bleed layout. (Used in a future
  // iteration; for now the editor co-exists with the chrome via the
  // CSS grid below.)
  const isEditor = $derived($page.url.pathname.startsWith('/projects/'));
</script>

<div class="shell">
  <header class="bench-header">
    <a href="/" class="brand">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none">
          <rect x="2.5" y="6" width="19" height="12" rx="1.5" fill="currentColor" />
          <g fill="var(--paper-1)">
            <circle cx="6" cy="10" r="0.9" />
            <circle cx="6" cy="14" r="0.9" />
            <circle cx="10" cy="10" r="0.9" />
            <circle cx="10" cy="14" r="0.9" />
            <circle cx="14" cy="10" r="0.9" />
            <circle cx="14" cy="14" r="0.9" />
            <circle cx="18" cy="10" r="0.9" />
            <circle cx="18" cy="14" r="0.9" />
          </g>
        </svg>
      </span>
      <span class="brand-word">AutoBoard</span>
      <span class="brand-suffix mono">v1</span>
    </a>

    <nav class="bench-nav" aria-label="Primary">
      <a href="/" class:active={$page.url.pathname === '/'}>Projects</a>
      <a href="/docs" class:active={$page.url.pathname.startsWith('/docs')}>Docs</a>
    </nav>

    <div class="bench-meta mono" aria-hidden="true">
      <span class="meta-cell"><span class="meta-label">scale</span>2.54 mm</span>
      <span class="meta-cell"><span class="meta-label">grid</span>0.1″</span>
      <span class="meta-cell"><span class="meta-label">pitch</span>400 pt</span>
    </div>
  </header>

  <main class="bench-main" class:editor={isEditor}>
    {@render children()}
  </main>
</div>

<style>
  .shell {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  /* The header is a thin instrument-panel strip — single hairline below,
     no card, no shadow. Spacing is tight because it lives at every route. */
  .bench-header {
    position: sticky;
    top: 0;
    z-index: var(--z-sticky);
    display: flex;
    align-items: center;
    gap: var(--sp-6);
    padding: 10px 18px;
    background: var(--paper-2);
    border-bottom: 1px solid var(--paper-edge);
    /* Faint ruled line directly under the strip mimics the edge of a
       notebook page. */
    box-shadow: inset 0 -1px 0 var(--paper-edge);
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--ink-1);
    text-decoration: none;
  }

  .brand:hover {
    text-decoration: none;
  }

  .brand-mark {
    color: var(--accent-1);
    display: inline-flex;
    align-items: center;
  }

  .brand-word {
    font-weight: 700;
    font-size: var(--fs-15);
    letter-spacing: -0.01em;
  }

  .brand-suffix {
    font-size: var(--fs-11);
    color: var(--ink-3);
    padding: 1px 6px;
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-1);
    background: var(--paper-1);
  }

  .bench-nav {
    display: flex;
    gap: 2px;
    margin-left: var(--sp-3);
  }

  .bench-nav a {
    display: inline-flex;
    align-items: center;
    height: 28px;
    padding: 0 12px;
    border-radius: var(--r-2);
    color: var(--ink-2);
    font-size: var(--fs-13);
    font-weight: 500;
    text-decoration: none;
    transition: background-color var(--dur) var(--ease-out), color var(--dur) var(--ease-out);
  }

  .bench-nav a:hover {
    color: var(--ink-1);
    background: var(--paper-3);
    text-decoration: none;
  }

  .bench-nav a.active {
    color: var(--accent-1);
    background: var(--accent-soft);
  }

  .bench-meta {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 0;
    font-size: var(--fs-11);
    color: var(--ink-3);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    background: var(--paper-1);
    overflow: hidden;
  }

  .meta-cell {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
  }

  .meta-cell + .meta-cell {
    border-left: 1px solid var(--paper-edge);
  }

  .meta-label {
    color: var(--ink-4);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 10px;
  }

  .bench-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .bench-main.editor {
    /* The editor owns its own background so it can render the canvas
       edge-to-edge inside the page. */
    background: var(--paper-1);
  }
</style>