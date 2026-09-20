import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiFetch } from './client';

interface FetchCall {
  url: string;
  init: RequestInit | undefined;
}

const calls: FetchCall[] = [];

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

beforeEach(() => {
  calls.length = 0;
  // Establish a runtime config the test can assert against.
  globalThis.window = {
    __AUTOBREADBOARD_CONFIG__: {
      apiBaseUrl: 'http://api.example.test/v1',
      environment: 'test',
      buildSha: 'test-sha'
    }
  } as unknown as Window & typeof globalThis;

  globalThis.fetch = vi.fn(async (input: unknown, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const headers = new Headers(init?.headers ?? undefined);
    void headers;
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' }
    });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalWindow === undefined) {
    Reflect.deleteProperty(globalThis, 'window');
  } else {
    globalThis.window = originalWindow;
  }
  vi.restoreAllMocks();
});

describe('apiFetch', () => {
  it('prefixes the path with the runtime-config apiBaseUrl', async () => {
    await apiFetch<{ ok: boolean }>('/projects');
    expect(calls[0]?.url).toBe('http://api.example.test/v1/projects');
  });

  it('does not double-prefix when the path already starts with the base', async () => {
    await apiFetch<{ ok: boolean }>('http://other.example.test/x');
    expect(calls[0]?.url).toBe('http://other.example.test/x');
  });

  it('joins with a single slash when the path omits the leading one', async () => {
    await apiFetch<{ ok: boolean }>('projects/123');
    expect(calls[0]?.url).toBe('http://api.example.test/v1/projects/123');
  });

  it('sets an X-Request-Id header on every call', async () => {
    await apiFetch<{ ok: boolean }>('/ping');
    const headers = new Headers(calls[0]?.init?.headers);
    const id = headers.get('X-Request-Id');
    expect(id).not.toBeNull();
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    );
  });

  it('sets Content-Type for non-GET bodies when caller did not', async () => {
    await apiFetch<{ ok: boolean }>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name: 'x' })
    });
    const headers = new Headers(calls[0]?.init?.headers);
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  it('preserves the caller-supplied Content-Type', async () => {
    await apiFetch<{ ok: boolean }>('/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'a=1'
    });
    const headers = new Headers(calls[0]?.init?.headers);
    expect(headers.get('Content-Type')).toBe('application/x-www-form-urlencoded');
  });

  it('returns parsed JSON on 2xx', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ items: [1, 2, 3] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    ) as unknown as typeof fetch;
    const data = await apiFetch<{ items: number[] }>('/items');
    expect(data.items).toEqual([1, 2, 3]);
  });

  it('returns undefined on 204 No Content', async () => {
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch;
    const result = await apiFetch<undefined>('/delete');
    expect(result).toBeUndefined();
  });

  it('throws ApiError with parsed envelope fields on error', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(
        JSON.stringify({
          error: { code: 'NOT_FOUND', message: 'gone', details: { id: 'x' } }
        }),
        { status: 404, headers: { 'Content-Type': 'application/json' } }
      )
    ) as unknown as typeof fetch;

    await expect(apiFetch<unknown>('/missing')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'NOT_FOUND',
      message: 'gone',
      status: 404,
      details: { id: 'x' }
    });
  });

  it('falls back to UNKNOWN when the error body is not the standard envelope', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response('not json', { status: 500 })
    ) as unknown as typeof fetch;

    try {
      await apiFetch<unknown>('/explode');
      throw new Error('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.code).toBe('UNKNOWN');
      expect(apiErr.status).toBe(500);
      expect(apiErr.message).toMatch(/status 500/);
    }
  });

  it('falls back to UNKNOWN when the JSON body has no error key', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ unexpected: true }), { status: 400 })
    ) as unknown as typeof fetch;

    try {
      await apiFetch<unknown>('/bad');
      throw new Error('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).code).toBe('UNKNOWN');
    }
  });
});

describe('ApiError', () => {
  it('is an Error subclass with the expected fields', () => {
    const e = new ApiError('CODE', 'msg', 418, { hint: 'teapot' });
    expect(e).toBeInstanceOf(Error);
    expect(e.code).toBe('CODE');
    expect(e.message).toBe('msg');
    expect(e.status).toBe(418);
    expect(e.details).toEqual({ hint: 'teapot' });
    expect(e.name).toBe('ApiError');
  });
});