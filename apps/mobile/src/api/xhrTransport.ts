/**
 * `fetch` o'rniga XMLHttpRequest transporti - timeout NATIVE ishlashi uchun.
 *
 * NIMA UCHUN: React Native'ning OkHttp klientida connect/read/write timeout 0
 * (cheksiz, OkHttpClientProvider). Bizning yagona timeout'imiz JS
 * `setTimeout` + AbortController edi, JS taymerlari esa Android'da ilova fonda
 * / ekran o'chiq bo'lsa TO'XTAYDI. Fonda boshlangan yuklash (bildirishnomadagi
 * Stop, background task) mobil internet "osilib" qolsa cheksiz kutardi va
 * single-flight uploader keyingi barcha urinishlarni shu va'daga bog'lab qo'yardi.
 *
 * `xhr.timeout` ni RN NetworkingModule OkHttp `callTimeout` ga aylantiradi -
 * u native, fonda ham ishlaydi. AbortController (JS taymeri) faqat zaxira.
 */
export interface ResponseLike {
  ok: boolean;
  status: number;
  text(): Promise<string>;
  headers: { get(name: string): string | null };
}

export interface TransportInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string | Uint8Array | null;
  signal?: AbortSignal | null;
  /** Butun so'rov uchun native timeout (ms). 0/undefined - yo'q. */
  timeoutMs?: number;
}

/** Native timeout tugadi (client buni `ApiError(0, 'timeout')` ga aylantiradi). */
export class TransportTimeoutError extends Error {
  constructor(ms: number) {
    super(`timeout ${ms} ms`);
    this.name = 'TransportTimeoutError';
  }
}

type XhrCtor = new () => XMLHttpRequest;

export function createXhrTransport(Xhr: XhrCtor = XMLHttpRequest) {
  return function xhrFetch(url: string, init: TransportInit = {}): Promise<ResponseLike> {
    return new Promise<ResponseLike>((resolve, reject) => {
      const xhr = new Xhr();
      let settled = false;
      const signal = init.signal ?? null;
      const onAbort = () => xhr.abort();
      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener('abort', onAbort);
        fn();
      };

      xhr.open(init.method ?? 'GET', url, true);
      for (const [k, v] of Object.entries(init.headers ?? {})) xhr.setRequestHeader(k, v);
      if (init.timeoutMs && init.timeoutMs > 0) xhr.timeout = init.timeoutMs;

      xhr.onload = () =>
        settle(() => {
          const text = typeof xhr.responseText === 'string' ? xhr.responseText : '';
          resolve({
            ok: xhr.status >= 200 && xhr.status < 300,
            status: xhr.status,
            text: async () => text,
            headers: { get: (name: string) => xhr.getResponseHeader(name) },
          });
        });
      xhr.onerror = () => settle(() => reject(new TypeError('Network request failed')));
      xhr.ontimeout = () => settle(() => reject(new TransportTimeoutError(init.timeoutMs ?? 0)));
      xhr.onabort = () => settle(() => reject(new Error('Aborted')));

      if (signal) {
        if (signal.aborted) {
          settle(() => reject(new Error('Aborted')));
          return;
        }
        signal.addEventListener('abort', onAbort);
      }
      // Uint8Array: RN XHR uni base64 qilib native'ga beradi (fetch ham xuddi shunday qilardi).
      xhr.send((init.body ?? null) as XMLHttpRequestBodyInit | null);
    });
  };
}
