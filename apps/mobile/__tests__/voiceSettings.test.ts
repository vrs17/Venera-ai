/**
 * Ovoz sozlamalari: noma'lum qiymat default'ga qaytadi; o'zgarish KV ga saqlanadi;
 * tezlik qiymatlari server chegarasida (0.7..1.3).
 */
import { __setVoiceSettingsStorage, DEFAULT_VOICE_SETTINGS, parseVoiceSettings, SPEED_VALUE, useVoiceSettings, VOICE_IDS } from '@/features/voice/voiceSettings';

describe('voice settings', () => {
  it('parses stored values and falls back to defaults for unknown ones', () => {
    expect(parseVoiceSettings(null)).toEqual(DEFAULT_VOICE_SETTINGS);
    expect(parseVoiceSettings('not json')).toEqual(DEFAULT_VOICE_SETTINGS);
    expect(parseVoiceSettings('{"voice":"uz_male_news","speed":"fast","showText":false,"earpiece":true}')).toEqual({
      voice: 'uz_male_news',
      speed: 'fast',
      showText: false,
      earpiece: true,
    });
    expect(parseVoiceSettings('{"voice":"robot","speed":"warp","showText":"yes","earpiece":1}')).toEqual(DEFAULT_VOICE_SETTINGS);
  });

  it('persists every change', () => {
    const kv = new Map<string, string>();
    __setVoiceSettingsStorage({ getItemSync: (k) => kv.get(k) ?? null, setItemSync: (k, v) => void kv.set(k, v) });
    useVoiceSettings.getState().set({ voice: 'uz_male_news', speed: 'slow' });
    expect(JSON.parse(kv.get('venera.voice.v1') as string)).toEqual({ ...DEFAULT_VOICE_SETTINGS, voice: 'uz_male_news', speed: 'slow' });
    expect(useVoiceSettings.getState().voice).toBe('uz_male_news');
    __setVoiceSettingsStorage(null);
  });

  it('speeds stay inside the server range; both voices are offered', () => {
    for (const v of Object.values(SPEED_VALUE)) {
      expect(v).toBeGreaterThanOrEqual(0.7);
      expect(v).toBeLessThanOrEqual(1.3);
    }
    expect(SPEED_VALUE.normal).toBe(0.95);
    expect(VOICE_IDS).toEqual(['uz_female_calm', 'uz_male_news']);
  });
});
