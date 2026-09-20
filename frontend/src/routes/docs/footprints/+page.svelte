<script lang="ts">
  import { renderMarkdown } from '$lib/markdown/render';
  import md from '$lib/docs/FOOTPRINTS.md?raw';

  const html = renderMarkdown(md);
</script>

<svelte:head>
  <title>Footprints · AutoBoard docs</title>
</svelte:head>

{@html html}