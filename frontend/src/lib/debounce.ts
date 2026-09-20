/**
 * Trailing-edge debounce.
 *
 * Each call to the returned function schedules `fn(...args)` to run after
 * `ms` milliseconds of inactivity. Repeated calls within that window cancel
 * the pending invocation and queue a new one — only the trailing-most call
 * survives. The wrapped function never invokes `fn` synchronously and never
 * propagates a return value (the editor's use cases are fire-and-forget:
 * `validateLayout`, layout mutation handlers, etc.).
 *
 * Cancellation: the previous `setTimeout` is cleared on every call. There
 * is no public `.cancel()` method — the wrapper stays as plain a function
 * as possible while remaining type-safe for arbitrary argument lists.
 *
 * Trailing-edge semantics (vs. leading-edge or throttling) match what the
 * editor needs: after a burst of mutations, the validator runs once with
 * the final layout, not once per intermediate state.
 */

export type Debounced<F extends (...args: never[]) => void> = (
  ...args: Parameters<F>
) => void;

export function debounce<F extends (...args: never[]) => void>(
  fn: F,
  ms: number
): Debounced<F> {
  let handle: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<F>): void => {
    if (handle !== null) {
      clearTimeout(handle);
    }
    handle = setTimeout(() => {
      handle = null;
      fn(...args);
    }, ms);
  };
}