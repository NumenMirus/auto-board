// See https://kit.svelte.dev/docs/types#app for information about these interfaces.
declare global {
  namespace App {
    // interface Error {}
    // interface Locals {}
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }

  interface Window {
    __AUTOBREADBOARD_CONFIG__?: {
      apiBaseUrl: string;
      environment: string;
      buildSha: string;
    };
  }
}

export {};
