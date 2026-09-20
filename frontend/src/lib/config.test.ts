import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import {
  FALLBACK_RUNTIME_CONFIG,
  getRuntimeConfig,
  type RuntimeConfig
} from './config';

describe('getRuntimeConfig', () => {
  const originalWindow = globalThis.window;

  beforeEach(() => {
    Reflect.deleteProperty(globalThis, 'window');
  });

  afterEach(() => {
    if (originalWindow === undefined) {
      Reflect.deleteProperty(globalThis, 'window');
    } else {
      globalThis.window = originalWindow;
    }
  });

  it('returns the fallback when window is undefined', () => {
    expect(getRuntimeConfig()).toEqual(FALLBACK_RUNTIME_CONFIG);
  });

  it('returns the fallback when the global is missing', () => {
    globalThis.window = {} as unknown as Window & typeof globalThis;
    expect(getRuntimeConfig()).toEqual(FALLBACK_RUNTIME_CONFIG);
  });

  it('reads the values set on window.__AUTOBREADBOARD_CONFIG__', () => {
    const cfg: RuntimeConfig = {
      apiBaseUrl: 'https://api.example.com/v1',
      environment: 'production',
      buildSha: 'abcdef0'
    };
    globalThis.window = {
      __AUTOBREADBOARD_CONFIG__: cfg
    } as unknown as Window & typeof globalThis;
    expect(getRuntimeConfig()).toEqual(cfg);
  });

  it('falls back field-by-field when individual values are missing or wrong type', () => {
    globalThis.window = {
      __AUTOBREADBOARD_CONFIG__: {
        apiBaseUrl: '',
        environment: 42
      }
    } as unknown as Window & typeof globalThis;
    const result = getRuntimeConfig();
    expect(result.apiBaseUrl).toBe(FALLBACK_RUNTIME_CONFIG.apiBaseUrl);
    expect(result.environment).toBe(FALLBACK_RUNTIME_CONFIG.environment);
    expect(result.buildSha).toBe(FALLBACK_RUNTIME_CONFIG.buildSha);
  });
});