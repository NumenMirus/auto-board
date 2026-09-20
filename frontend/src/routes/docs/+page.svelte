<script lang="ts">
  import { renderMarkdown } from '$lib/markdown/render';
  import indexMd from '$lib/docs/README.md?raw';

  const html = renderMarkdown(indexMd);
</script>

<svelte:head>
  <title>Docs · AutoBoard</title>
</svelte:head>

{@html html}