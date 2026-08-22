/// <reference types="vite/client" />

/** Firebase web config, injected at build time.
 *
 *  Declared rather than left to `any` so a typo in a key name fails the
 *  typecheck instead of silently leaving push unconfigured at runtime. Every
 *  one is optional: a desk without Firebase must still build and run.
 */
interface ImportMetaEnv {
  readonly VITE_FIREBASE_API_KEY?: string;
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string;
  readonly VITE_FIREBASE_PROJECT_ID?: string;
  readonly VITE_FIREBASE_STORAGE_BUCKET?: string;
  readonly VITE_FIREBASE_MESSAGING_SENDER_ID?: string;
  readonly VITE_FIREBASE_APP_ID?: string;
  readonly VITE_FIREBASE_VAPID_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
