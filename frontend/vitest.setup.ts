// Vitest setup file. Ensure global stubs exist for components tests.

// crypto.randomUUID is available in jsdom, but stub for safety.
if (typeof globalThis.crypto === 'undefined') {
  // @ts-expect-error - minimal polyfill for older test environments
  globalThis.crypto = {};
}
if (typeof globalThis.crypto.randomUUID !== 'function') {
  globalThis.crypto.randomUUID = () =>
    'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
}

// Silence unhandled rejections for tests that intentionally throw.
process.on('unhandledRejection', () => {
  // no-op
});
