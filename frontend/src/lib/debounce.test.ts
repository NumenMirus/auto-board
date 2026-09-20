import { describe, expect, it, vi } from 'vitest';
import { debounce } from './debounce';

describe('debounce', () => {
  it('invokes the wrapped function once after the trailing delay', () => {
    vi.useFakeTimers();
    try {
      const spy = vi.fn();
      const wrapped = debounce(spy, 100);

      wrapped('a');
      wrapped('b');
      wrapped('c');
      expect(spy).not.toHaveBeenCalled();

      vi.advanceTimersByTime(99);
      expect(spy).not.toHaveBeenCalled();

      vi.advanceTimersByTime(1);
      expect(spy).toHaveBeenCalledTimes(1);
      // Last call's args win — that's the whole point of trailing-edge.
      expect(spy).toHaveBeenCalledWith('c');
    } finally {
      vi.useRealTimers();
    }
  });

  it('cancels the pending invocation on each rapid call', () => {
    vi.useFakeTimers();
    try {
      const spy = vi.fn();
      const wrapped = debounce(spy, 100);

      wrapped();
      vi.advanceTimersByTime(50);
      wrapped();
      vi.advanceTimersByTime(50);
      wrapped();
      // Total elapsed is 100ms but the timer reset three times, so the
      // spy must still not have fired.
      expect(spy).not.toHaveBeenCalled();

      vi.advanceTimersByTime(100);
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('propagates multiple positional arguments to the wrapped function', () => {
    vi.useFakeTimers();
    try {
      const spy = vi.fn();
      const wrapped = debounce(spy, 10);

      wrapped(1, 'two', { three: 3 });
      vi.advanceTimersByTime(10);

      expect(spy).toHaveBeenCalledTimes(1);
      expect(spy).toHaveBeenCalledWith(1, 'two', { three: 3 });
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps firing for distinct, non-overlapping calls', () => {
    vi.useFakeTimers();
    try {
      const spy = vi.fn();
      const wrapped = debounce(spy, 50);

      wrapped('first');
      vi.advanceTimersByTime(50);
      expect(spy).toHaveBeenCalledTimes(1);
      expect(spy).toHaveBeenLastCalledWith('first');

      wrapped('second');
      vi.advanceTimersByTime(50);
      expect(spy).toHaveBeenCalledTimes(2);
      expect(spy).toHaveBeenLastCalledWith('second');
    } finally {
      vi.useRealTimers();
    }
  });
});