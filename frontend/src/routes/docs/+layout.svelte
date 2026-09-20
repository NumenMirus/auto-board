<script lang="ts">
  import '../../app.css';
  import { page } from '$app/stores';
  import type { Snippet } from 'svelte';

  type Props = { children: Snippet };
  let { children }: Props = $props();

  const links = [
    { href: '/docs', label: 'Index' },
    { href: '/docs/footprints', label: 'Footprints' },
    { href: '/docs/project-json', label: 'Project JSON' }
  ];

  function isActive(href: string, current: string): boolean {
    if (href === '/docs') return current === '/docs' || current === '/docs/';
    return current === href || current.startsWith(`${href}/`);
  }
</script>

<div class="docs-shell">
  <aside class="docs-nav">
    <h2>Docs</h2>
    <ul>
      {#each links as link (link.href)}
        <li>
          <a href={link.href} class:active={isActive(link.href, $page.url.pathname)}>
            {link.label}
          </a>
        </li>
      {/each}
    </ul>
    <p class="hint">
      Source: <code>/docs</code> in the repo (mirrored to
      <code>frontend/src/lib/docs/</code> for the bundle). Edit the originals
      there; this page is rebuilt on every <code>npm run build</code>.
    </p>
  </aside>
  <article class="docs-content">
    {@render children()}
  </article>
</div>

<style>
  .docs-shell {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: var(--space-4);
    padding: var(--space-4);
    max-width: 1200px;
    margin: 0 auto;
    width: 100%;
  }

  .docs-nav {
    position: sticky;
    top: var(--space-4);
    align-self: start;
    border-right: 1px solid var(--color-border);
    padding-right: var(--space-4);
  }

  .docs-nav h2 {
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--color-muted);
    margin: 0 0 var(--space-2);
  }

  .docs-nav ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .docs-nav a {
    display: block;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    color: var(--color-fg);
  }

  .docs-nav a:hover {
    background: var(--color-surface);
    text-decoration: none;
  }

  .docs-nav a.active {
    background: var(--color-surface);
    font-weight: 600;
  }

  .hint {
    margin-top: var(--space-4);
    font-size: 12px;
    color: var(--color-muted);
  }

  .docs-content {
    min-width: 0;
  }

  .docs-content :global(h1) {
    margin-top: 0;
    border-bottom: 1px solid var(--color-border);
    padding-bottom: var(--space-2);
  }

  .docs-content :global(h2) {
    margin-top: var(--space-5);
    border-bottom: 1px solid var(--color-border);
    padding-bottom: var(--space-1);
  }

  .docs-content :global(h3) {
    margin-top: var(--space-4);
  }

  .docs-content :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: var(--space-3) 0;
    font-size: 14px;
  }

  .docs-content :global(th),
  .docs-content :global(td) {
    border: 1px solid var(--color-border);
    padding: var(--space-1) var(--space-2);
    text-align: left;
    vertical-align: top;
  }

  .docs-content :global(thead) {
    background: var(--color-surface);
  }

  .docs-content :global(code) {
    background: var(--color-surface);
    padding: 1px 4px;
    border-radius: var(--radius-sm);
    font-size: 0.9em;
  }

  .docs-content :global(pre) {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.5;
  }

  .docs-content :global(pre code) {
    background: transparent;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
  }

  .docs-content :global(blockquote) {
    border-left: 3px solid var(--color-accent);
    margin: var(--space-3) 0;
    padding: var(--space-1) var(--space-3);
    color: var(--color-muted);
  }

  .docs-content :global(ul),
  .docs-content :global(ol) {
    padding-left: var(--space-4);
  }

  .docs-content :global(hr) {
    border: none;
    border-top: 1px solid var(--color-border);
    margin: var(--space-4) 0;
  }
</style>