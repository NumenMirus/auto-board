// Pure client-side app (SPA, served by Nginx in production, Vite in dev).
// SvelteKit's static adapter renders a fallback index.html; we explicitly
// disable SSR + prerendering so any per-request errors surface in the browser
// rather than failing the build.
export const ssr = false;
export const prerender = false;