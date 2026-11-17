/**
 * Server qabul qiladigan beshta audio turi (aac, mp4, mpeg, wav, ogg): MIME taxalluslari (server
 * `audio.TYPE_ALIASES` nusxasi), kengaytma > MIME tartibi, saqlanadigan kengaytma va fayl boshi
 * (server `sniff`/`mp3_header`) - ayniqsa AAC ADTS va MP3 kadri farqi (ikkalasi ham 0xFFF bilan).
 */
import {
  AUDIO_CONTENT_TYPES,
  AUDIO_EXTENSIONS,
  audioTypeFor,
  canonicalAudioType,
  isAudioContentType,
  isMp3FrameHeader,
  isUnsupportedVideo,
  isVideoContentType,
  matchesAudioType,
  sniffAudioType,
} from '@/lib/audioTypes';

const bytes = (...parts: (string | number[])[]) =>
  Uint8Array.from(parts.flatMap((p) => (typeof p === 'string' ? Array.from(p, (c) => c.charCodeAt(0)) : p)));

const HEADS = {
  mp4: bytes([0, 0, 0, 0x20], 'ftypM4A ', [0, 0, 0, 0]),
  // AAC ADTS: 0xFFF1 - sinx + qatlam 00.
  aac: bytes([0xff, 0xf1, 0x50, 0x80, 0x01, 0x7f, 0xfc, 0, 0, 0, 0, 0]),
  // MPEG-1 Layer III, 128 kbps, 44.1 kHz: 0xFFFB 90 64.
  mp3: bytes([0xff, 0xfb, 0x90, 0x64, 0, 0, 0, 0, 0, 0, 0, 0]),
  mp3Id3: bytes('ID3', [4, 0, 0, 0, 0, 0x21, 0x76, 0, 0, 0]),
  wav: bytes('RIFF', [0x24, 0x08, 0, 0], 'WAVEfmt '),
  ogg: bytes('OggS', [0, 2, 0, 0, 0, 0, 0, 0]),
  pdf: bytes('%PDF-1.7 abcd'),
};

describe('audio types: names and aliases (server TYPE_ALIASES / EXTENSIONS)', () => {
  it('exactly the server types (five audio + MP4/MOV video), each stored with its own extension', () => {
    expect([...AUDIO_CONTENT_TYPES]).toEqual(['audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/wav', 'audio/ogg', 'video/mp4']);
    // Video nusxasi `.m4v`: `.mp4` ni native (Kotlin) o'zimniki deb `audio/mp4` qilib o'qirdi.
    expect(AUDIO_EXTENSIONS).toEqual({
      'audio/aac': '.aac', 'audio/mp4': '.m4a', 'audio/mpeg': '.mp3', 'audio/wav': '.wav', 'audio/ogg': '.ogg', 'video/mp4': '.m4v',
    });
    expect(isAudioContentType('audio/ogg')).toBe(true);
    expect(isAudioContentType('audio/flac')).toBe(false);
    expect(isAudioContentType(null)).toBe(false);
  });

  it('MIME aliases map like the server (case, parameters and whitespace ignored)', () => {
    for (const m of ['audio/mp3', 'audio/x-mp3', 'audio/x-mpeg', 'audio/mpeg3', 'audio/x-mpeg-3', 'audio/mpg', 'Audio/MPEG; charset=x']) {
      expect([m, canonicalAudioType(m)]).toEqual([m, 'audio/mpeg']);
    }
    for (const m of ['audio/x-wav', 'audio/wave', 'audio/vnd.wave', 'audio/x-pn-wav', 'audio/wav']) expect([m, canonicalAudioType(m)]).toEqual([m, 'audio/wav']);
    for (const m of ['audio/opus', 'audio/oga', 'audio/x-ogg', 'application/ogg', ' AUDIO/OGG ']) expect([m, canonicalAudioType(m)]).toEqual([m, 'audio/ogg']);
    for (const m of ['audio/x-m4a', 'audio/m4a', 'audio/mp4']) expect([m, canonicalAudioType(m)]).toEqual([m, 'audio/mp4']);
    for (const m of ['audio/x-aac', 'audio/aacp', 'audio/aac-adts', 'audio/aac']) expect([m, canonicalAudioType(m)]).toEqual([m, 'audio/aac']);
    for (const m of ['video/mp4', 'video/quicktime', 'Video/X-M4V']) expect([m, canonicalAudioType(m)]).toEqual([m, 'video/mp4']);
    for (const m of ['audio/flac', 'audio/amr', 'video/webm', 'video/3gpp', 'constructor', '', null, undefined]) expect([m, canonicalAudioType(m)]).toEqual([m, null]);
  });

  it('file extension first, then MIME; known foreign audio extensions never trust the MIME', () => {
    expect(audioTypeFor('Kengash.MP3', 'audio/mp4')).toBe('audio/mpeg');
    expect(audioTypeFor('a.wav')).toBe('audio/wav');
    expect(audioTypeFor('a.ogg')).toBe('audio/ogg');
    expect(audioTypeFor('a.oga')).toBe('audio/ogg');
    expect(audioTypeFor('voice.opus', 'application/octet-stream')).toBe('audio/ogg');
    expect(audioTypeFor('a.m4a')).toBe('audio/mp4');
    // .mp4/.mov/.m4v - video (2026-11-17): server audiosini ajratadi.
    expect(audioTypeFor('a.mp4')).toBe('video/mp4');
    expect(audioTypeFor('IMG_0001.MOV')).toBe('video/mp4');
    expect(audioTypeFor('clip.m4v')).toBe('video/mp4');
    expect(audioTypeFor('clip', 'video/quicktime')).toBe('video/mp4');
    expect(audioTypeFor('a.aac')).toBe('audio/aac');
    // Kengaytma yo'q - MIME taxallusi bilan.
    expect(audioTypeFor('voice', 'audio/x-wav')).toBe('audio/wav');
    expect(audioTypeFor('voice', 'application/ogg')).toBe('audio/ogg');
    expect(audioTypeFor('voice.constructor', 'audio/mp3')).toBe('audio/mpeg');
    // flac/amr/webm - MIME nima desa ham yo'q.
    expect(audioTypeFor('song.flac', 'audio/mpeg')).toBeNull();
    expect(audioTypeFor('note.amr', 'audio/aac')).toBeNull();
    expect(audioTypeFor('x.webm', 'audio/ogg')).toBeNull();
    expect(audioTypeFor(null, null)).toBeNull();
  });

  it('unsupported video (WebM, MKV, AVI ...) is told apart from unsupported audio: "send an MP4"', () => {
    expect(isUnsupportedVideo('rec.webm', 'video/webm')).toBe(true);
    expect(isUnsupportedVideo('rec.mkv', null)).toBe(true);
    expect(isUnsupportedVideo('clip', 'video/x-msvideo')).toBe(true);
    expect(isUnsupportedVideo('a.mp4', 'video/mp4')).toBe(false);          // qabul qilinadi
    expect(isUnsupportedVideo('song.flac', 'audio/flac')).toBe(false);     // audio - oddiy "format mos emas"
    expect(isUnsupportedVideo('call.3gp', 'audio/3gpp')).toBe(false);      // AMR qo'ng'iroq yozuvi - "MP4 yuboring" emas
    expect(isVideoContentType('video/mp4')).toBe(true);
    expect(isVideoContentType('audio/mp4')).toBe(false);
  });
});

describe('audio types: file header (server sniff on the first chunk)', () => {
  it('each format is recognised by its own signature', () => {
    expect(sniffAudioType(HEADS.mp4)).toBe('audio/mp4');
    expect(sniffAudioType(HEADS.aac)).toBe('audio/aac');
    expect(sniffAudioType(HEADS.mp3)).toBe('audio/mpeg');
    expect(sniffAudioType(HEADS.mp3Id3)).toBe('audio/mpeg');
    expect(sniffAudioType(HEADS.wav)).toBe('audio/wav');
    expect(sniffAudioType(HEADS.ogg)).toBe('audio/ogg');
    expect(sniffAudioType(HEADS.pdf)).toBeNull();
    expect(sniffAudioType(new Uint8Array())).toBeNull();
  });

  it('AAC ADTS and an MP3 frame both start with 0xFFF - the layer bits tell them apart', () => {
    // ADTS: qatlam 00 -> MP3 emas.
    for (const b1 of [0xf1, 0xf9, 0xf0, 0xf8]) {
      const head = Uint8Array.from([0xff, b1, 0x50, 0x80]);
      expect([b1, matchesAudioType(head, 'audio/aac'), matchesAudioType(head, 'audio/mpeg')]).toEqual([b1, true, false]);
    }
    // MP3: Layer III (01), II (10), I (11) - ADTS emas.
    for (const b1 of [0xfb, 0xfd, 0xff, 0xf3, 0xe3]) {
      const head = Uint8Array.from([0xff, b1, 0x90, 0x64]);
      expect([b1, matchesAudioType(head, 'audio/mpeg'), matchesAudioType(head, 'audio/aac')]).toEqual([b1, true, false]);
    }
  });

  it('an MP3 frame header must be valid like the server mp3_header (version, layer, bitrate, rate)', () => {
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xfb, 0x90, 0x64]))).toBe(true);
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xeb, 0x90, 0x64]))).toBe(false); // versiya 01 - zahira
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xf9, 0x90, 0x64]))).toBe(false); // qatlam 00 - ADTS
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xfb, 0x00, 0x64]))).toBe(false); // bitreyt 0 ("free")
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xfb, 0xf0, 0x64]))).toBe(false); // bitreyt 15 - buzilgan
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xfb, 0x9c, 0x64]))).toBe(false); // chastota 3 - zahira
    expect(isMp3FrameHeader(Uint8Array.from([0xff, 0xfb, 0x90]))).toBe(false); // 4 baytdan kam
    expect(isMp3FrameHeader(Uint8Array.from([0xfe, 0xfb, 0x90, 0x64]))).toBe(false);
  });

  it('a type only matches its own signature (MP4 needs ftyp, WAV needs RIFF..WAVE, Ogg needs OggS)', () => {
    expect(matchesAudioType(HEADS.mp4, 'audio/mp4')).toBe(true);
    // Video - server `is_iso_media`: `ftyp` yoki eski QuickTime MOV ning `moov`/`mdat`/`wide` boshi.
    expect(matchesAudioType(HEADS.mp4, 'video/mp4')).toBe(true);
    expect(matchesAudioType(bytes([0, 0, 0, 8], 'wide', [0, 0, 0, 0]), 'video/mp4')).toBe(true);
    expect(matchesAudioType(bytes([0x1a, 0x45, 0xdf, 0xa3], [0, 0, 0, 0, 0, 0, 0, 0]), 'video/mp4')).toBe(false); // WebM
    expect(matchesAudioType(bytes([0, 0, 0, 8], 'moov'), 'audio/mp4')).toBe(false);
    expect(matchesAudioType(bytes('RIFF', [0, 0, 0, 0], 'AVI '), 'audio/wav')).toBe(false);
    expect(matchesAudioType(bytes('RIFF'), 'audio/wav')).toBe(false);
    expect(matchesAudioType(HEADS.ogg, 'audio/ogg')).toBe(true);
    expect(matchesAudioType(HEADS.mp3Id3, 'audio/aac')).toBe(false); // ID3 + AAC - server rad etadi
    for (const type of AUDIO_CONTENT_TYPES) expect([type, matchesAudioType(HEADS.pdf, type)]).toEqual([type, false]);
  });
});
