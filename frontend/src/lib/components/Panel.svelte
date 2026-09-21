<script lang="ts">
  import type { Snippet } from 'svelte';

  type Props = {
    title: string;
    open: boolean;
    /** Chevron label for screen readers. */
    toggleLabel?: string;
    /** Optional small badge shown between title and chevron. */
    meta?: Snippet;
    children?: Snippet;
    onToggle?: () => void;
  };

  let {
    title,
    open,
    toggleLabel,
    meta,
    children,
    onToggle
  }: Props = $props();
</script>

<section class="panel" class:open>
  <button
    type="button"
    class="panel-header"
    aria-expanded={open}
    aria-label={toggleLabel ?? title}
    onclick={() => onToggle?.()}
  >
    <h2>{title}</h2>
    {#if meta}
      <span class="panel-meta-slot">{@render meta()}</span>
    {/if}
    <svg class="chev" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" focusable="false">
      <path
        d="M2 4l3 3 3-3"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  </button>
  {#if open && children}
    <div class="panel-body">{@render children()}</div>
  {/if}
</section>

<style>
  .panel {
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-3);
    box-shadow: var(--sh-1);
    overflow: hidden;
    /* `overflow: hidden` removes the flex item's automatic min-content-height
       floor, so in `.ed-sidebar`'s column flex layout the browser would
       otherwise shrink an open panel to fit rather than letting the sidebar
       scroll. Keep panels at their natural height so `.ed-sidebar`'s
       `overflow-y: auto` is the one thing that scrolls. */
    flex-shrink: 0;
  }

  .panel-header {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    width: 100%;
    padding: 8px 12px;
    background: var(--paper-2);
    border: none;
    border-bottom: 1px solid var(--paper-edge);
    color: var(--ink-2);
    font-family: inherit;
    text-align: left;
    cursor: pointer;
    transition: background-color var(--dur-fast) var(--ease-out);
  }

  .panel-header:hover:not(:disabled) {
    background: var(--paper-3);
  }

  .panel.open .panel-header {
    border-bottom-color: var(--paper-edge);
  }

  .panel:not(.open) .panel-header {
    border-bottom-color: transparent;
  }

  .panel-header h2 {
    margin: 0;
    font-size: var(--fs-11);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-2);
    flex: 1;
    line-height: 1.2;
  }

  .panel-meta-slot {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }

  .chev {
    color: var(--ink-3);
    flex-shrink: 0;
    transition: transform var(--dur-fast) var(--ease-out);
  }

  .panel.open .chev {
    transform: rotate(180deg);
  }

  .panel-body {
    display: block;
  }

  /* Children render flat inside the panel — strip their own card chrome so
     they nest cleanly without nested-card anti-pattern. */
  .panel-body :global(section) {
    border: none !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
  }

  .panel-body :global(.advanced-panel) {
    border: none;
    border-radius: 0;
    box-shadow: none;
    background: transparent;
    padding: var(--sp-3);
  }

  .panel-body :global(.export-menu) {
    padding: var(--sp-3);
  }

  .panel-body :global(.metrics-bar) {
    border: none;
    border-radius: 0;
    box-shadow: none;
    background: transparent;
    padding: var(--sp-3);
  }

  .panel-body :global(.net-panel) {
    padding: var(--sp-2) 0;
  }

  .panel-body :global(.diagnostics-panel) {
    padding: var(--sp-2) 0;
  }

  .panel-body :global(.safety-notice) {
    border-radius: 0;
    border-left: none;
    border-right: none;
    border-bottom: none;
    background: var(--sev-warning-soft);
    padding: var(--sp-3);
    font-size: var(--fs-12);
  }

  @media (prefers-reduced-motion: reduce) {
    .chev,
    .panel-header {
      transition: none;
    }
  }
</style>
