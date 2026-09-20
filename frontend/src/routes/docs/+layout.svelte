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
    <span class="eyebrow mono">Reference</span>
    <h2>Documentation</h2>
    <ul>
      {#each links as link (link.href)}
        <li>
          <a href={link.href} class:active={isActive(link.href, $page.url.pathname)}>
            <span class="dot" aria-hidden="true"></span>
            <span>{link.label}</span>
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
    grid-template-columns: 240px 1fr;
    gap: var(--sp-8);
    padding: var(--sp-8) var(--sp-6);
    max-width: 1100px;
    margin: 0 auto;
    width: 100%;
  }

  @media (max-width: 800px) {
    .docs-shell {
      grid-template-columns: 1fr;
      gap: var(--sp-4);
    }
  }

  .docs-nav {
    position: sticky;
    top: var(--sp-6);
    align-self: start;
  }

  .eyebrow {
    display: block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-3);
    margin-bottom: 4px;
  }

  .docs-nav h2 {
    font-size: var(--fs-13);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-2);
    margin: 0 0 var(--sp-3);
    font-weight: 600;
  }

  .docs-nav ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .docs-nav a {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border-radius: var(--r-2);
    color: var(--ink-2);
    font-size: var(--fs-13);
    font-weight: 500;
    transition: background-color 120ms cubic-bezier(0.16, 1, 0.3, 1),
      color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .docs-nav a:hover {
    background: var(--paper-2);
    color: var(--ink-1);
    text-decoration: none;
  }

  .docs-nav a.active {
    background: var(--accent-soft);
    color: var(--accent-1);
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--paper-edge);
    transition: background-color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .docs-nav a.active .dot {
    background: var(--accent-1);
  }

  .hint {
    margin-top: var(--sp-4);
    font-size: var(--fs-11);
    color: var(--ink-3);
    line-height: 1.5;
  }

  .hint code {
    background: var(--paper-2);
    padding: 1px 4px;
    border-radius: var(--r-1);
    font-size: 0.92em;
  }

  .docs-content {
    min-width: 0;
    max-width: 70ch;
  }

  .docs-content :global(h1) {
    margin: 0 0 var(--sp-3);
    padding-bottom: var(--sp-3);
    font-size: var(--fs-32);
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--ink-1);
    border-bottom: 1px solid var(--paper-edge);
  }

  .docs-content :global(h2) {
    margin-top: var(--sp-8);
    padding-bottom: var(--sp-2);
    font-size: var(--fs-17);
    font-weight: 600;
    color: var(--ink-1);
    border-bottom: 1px solid var(--paper-edge);
  }

  .docs-content :global(h3) {
    margin-top: var(--sp-5);
    font-size: var(--fs-15);
    font-weight: 600;
    color: var(--ink-1);
  }

  .docs-content :global(h4) {
    margin-top: var(--sp-4);
    font-size: var(--fs-13);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--ink-2);
  }

  .docs-content :global(p) {
    margin: var(--sp-3) 0;
    line-height: 1.65;
    color: var(--ink-1);
  }

  .docs-content :global(table) {
    border-collapse: collapse;
    width: 100%;
    margin: var(--sp-3) 0;
    font-size: var(--fs-13);
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    overflow: hidden;
  }

  .docs-content :global(th),
  .docs-content :global(td) {
    border-bottom: 1px solid var(--paper-edge);
    padding: 8px 12px;
    text-align: left;
    vertical-align: top;
  }

  .docs-content :global(tr:last-child td) {
    border-bottom: none;
  }

  .docs-content :global(thead) {
    background: var(--paper-2);
  }

  .docs-content :global(th) {
    font-weight: 600;
    color: var(--ink-2);
    font-size: var(--fs-11);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .docs-content :global(code) {
    background: var(--paper-2);
    padding: 1px 5px;
    border-radius: var(--r-1);
    font-size: 0.92em;
    color: var(--ink-1);
    border: 1px solid var(--paper-edge);
  }

  .docs-content :global(pre) {
    background: var(--paper-2);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    padding: var(--sp-3) var(--sp-4);
    overflow-x: auto;
    font-size: var(--fs-12);
    line-height: 1.55;
    color: var(--ink-1);
  }

  .docs-content :global(pre code) {
    background: transparent;
    padding: 0;
    border: none;
    border-radius: 0;
    font-size: inherit;
    color: inherit;
  }

  .docs-content :global(blockquote) {
    border-left: 3px solid var(--accent-1);
    margin: var(--sp-3) 0;
    padding: var(--sp-2) var(--sp-4);
    background: var(--accent-soft);
    border-radius: 0 var(--r-2) var(--r-2) 0;
    color: var(--ink-1);
  }

  .docs-content :global(ul),
  .docs-content :global(ol) {
    padding-left: var(--sp-4);
    margin: var(--sp-3) 0;
  }

  .docs-content :global(li) {
    margin: 4px 0;
    line-height: 1.55;
  }

  .docs-content :global(hr) {
    border: none;
    border-top: 1px solid var(--paper-edge);
    margin: var(--sp-6) 0;
  }

  .docs-content :global(a) {
    color: var(--accent-1);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .docs-content :global(strong) {
    color: var(--ink-1);
    font-weight: 600;
  }
</style>