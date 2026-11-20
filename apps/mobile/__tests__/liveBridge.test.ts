/**
 * Jonli suhbat ko'prigi (`features/live/bridge.ts`): sayt manzili, token skripti (faqat o'z saytimizga),
 * qo'ng'iroqni tugatish skripti, sahifa xabarlarini o'qish.
 */
import {
  ACTIVE_STATUSES,
  END_SCRIPT,
  liveOrigin,
  liveUrl,
  parseLiveMessage,
  sameOrigin,
  tokenScript,
} from '@/features/live/bridge';

describe('live bridge', () => {
  it('origin and page URL come from the API base URL', () => {
    expect(liveOrigin('https://llm.brb-tech.uz')).toBe('https://llm.brb-tech.uz');
    expect(liveOrigin('https://llm.brb-tech.uz/api/')).toBe('https://llm.brb-tech.uz');
    expect(liveOrigin('http://10.0.2.2:8001')).toBe('http://10.0.2.2:8001');
    expect(liveUrl('https://llm.brb-tech.uz/', { theme: 'dark', lang: 'ru' })).toBe(
      'https://llm.brb-tech.uz/barno?app=1&autostart=1&theme=dark&lang=ru',
    );
  });

  it('sameOrigin does not accept look-alike hosts', () => {
    const o = 'https://llm.brb-tech.uz';
    expect(sameOrigin('https://llm.brb-tech.uz/barno?app=1', o)).toBe(true);
    expect(sameOrigin('https://llm.brb-tech.uz', o)).toBe(true);
    expect(sameOrigin('https://llm.brb-tech.uz.evil.example/barno', o)).toBe(false);
    expect(sameOrigin('https://evil.example/?https://llm.brb-tech.uz', o)).toBe(false);
    expect(sameOrigin(undefined, o)).toBe(false);
  });

  it('the token script checks the origin and escapes the token', () => {
    const js = tokenScript('https://x.uz', 'a.b"c');
    expect(js).toContain('if(location.origin!=="https://x.uz")return;');
    expect(js).toContain('window.__BARNO_APP_TOKEN__="a.b\\"c";');
    expect(js).toContain("new Event('barno:token')");
    expect(js.endsWith('true;')).toBe(true);
    expect(END_SCRIPT).toContain('window.__barnoLive.end()');
  });

  it('parses only known page messages', () => {
    expect(parseLiveMessage('{"type":"ready"}')).toEqual({ type: 'ready' });
    expect(parseLiveMessage('{"type":"status","status":"live"}')).toEqual({ type: 'status', status: 'live' });
    expect(parseLiveMessage('{"type":"close"}')).toEqual({ type: 'close' });
    expect(parseLiveMessage('{"type":"auth"}')).toEqual({ type: 'auth' });
    expect(parseLiveMessage('{"type":"status"}')).toBeNull();
    expect(parseLiveMessage('{"type":"eval","code":"x"}')).toBeNull();
    expect(parseLiveMessage('not json')).toBeNull();
    expect(parseLiveMessage(42)).toBeNull();
    expect(parseLiveMessage(`{"type":"ready","pad":"${'x'.repeat(3000)}"}`)).toBeNull();
    expect([...ACTIVE_STATUSES].sort()).toEqual(['connecting', 'live', 'mic']);
  });
});
