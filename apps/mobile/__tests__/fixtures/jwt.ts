/** Testlar uchun imzosiz JWT (payload faqat o'qiladi - jwt.ts imzoni tekshirmaydi). */
export const b64url = (s: string) => Buffer.from(s, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

export const jwt = (payload: Record<string, unknown>) => `${b64url('{"alg":"HS256","typ":"JWT"}')}.${b64url(JSON.stringify(payload))}.sig`;
