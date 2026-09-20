<script lang="ts">
  import { renderMarkdown } from '$lib/markdown/render';
  import md from '$lib/docs/PROJECT_JSON.md?raw';

  const html = renderMarkdown(md);
</script>

<svelte:head>
  <title>Project JSON · AutoBoard docs</title>
</svelte:head>

{@html html}