#!/usr/bin/env python3
"""Reliz APK tekshiruvi - tarqatishdan (APK API, Telegram bot) OLDIN, build serverda (README 4).

NIMA UCHUN. Barno AI Google Play'dan emas, fayl sifatida (Telegram) tarqatiladi. Bunday
ilovani Google Play Protect qattiq to'sib qo'yishi mumkin ("App blocked to protect your
device"): Telegram/brauzer/fayl menejeridan o'rnatilayotgan ilova SMS, bildirishnomalarni
o'qish yoki Accessibility ruxsatini e'lon qilsa (2026-11-06 jonli holat: 1.3.5 dagi
"Ovoz tugmasi" Accessibility xizmati tufayli "App not installed"). Ochiq debug kalit
(React Native shablonidagi `debug.keystore` - hammada bor) bilan imzolangan APK esa
xavfsizlik teshigi: begona odam shu kalit bilan "yangilanish" yasab, ilova ma'lumotiga
kira oladi. Bu skript shunday APK'ni chiqarishdan oldin TO'XTATADI.

Faqat standart kutubxona (build serverga hech narsa o'rnatilmaydi). Tekshiradi:
  * imzo: v2/v3 bloki bor, fayl imzodan keyin o'zgarmagan (v2 digest), sertifikat debug
    kalit EMAS (`--allow-debug-key` - faqat o'zingiz sinash uchun), `--expect-cert` berilsa
    aynan shu kalit (kalit tasodifan almashsa yangilanish o'rnatilmay qoladi);
  * manifest: paket nomi, debuggable/testOnly yo'q, targetSdk yetarli, Play Protect
    to'sadigan ruxsatlar va Accessibility / bildirishnoma tinglovchi xizmatlari YO'Q;
  * zip: resources.arsc siqilmagan va tekislangan (Android 11+ talabi), native .so
    siqilmagan va 16 KB ga tekislangan (Android 15 16 KB sahifali qurilmalar);
  * hajm: 50 MB dan katta bo'lsa ogohlantirish (Telegram bot yubora olmaydi).

Foydalanish:
    python3 scripts/check_apk.py app-release.apk [--expect-cert SHA256] [--allow-debug-key]
Chiqish kodi: 0 - tarqatsa bo'ladi, 1 - muammo bor (sabablar ro'yxati), 2 - fayl o'qilmadi.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zipfile

PACKAGE = "uz.brbtech.venera.meetings"
#: Play Protect "noto'g'ri target" ogohlantirishi: joriy API dan 2 tadan ko'p past (2026: API 36).
MIN_TARGET_SDK = 34
#: Telegram Bot API fayl chegarasi - bot (`app/bot/mobile_app.py`) bundan kattasini yubora olmaydi.
TELEGRAM_MAX = 50 * 1024 * 1024
#: React Native shablonidagi `android/app/debug.keystore` (hammada bir xil, paroli ochiq) - SHA-256.
PUBLIC_DEBUG_CERT = "FAC61745DC0903786FB9EDE62A962B399F7348F0BB6F899B8332667591033B9C"
#: Play Protect "kuchaytirilgan firibgarlikdan himoya" (sideload) va umuman xavfli deb biladigan ruxsatlar.
#: app.config.ts `blockedPermissions` bilan bir xil ro'yxat - kutubxona qo'shsa ham manifestga tushmasligi kerak.
SENSITIVE_PERMISSIONS = frozenset(f"android.permission.{p}" for p in (
    "RECEIVE_SMS", "READ_SMS", "SEND_SMS", "RECEIVE_MMS", "RECEIVE_WAP_PUSH", "READ_CALL_LOG",
    "WRITE_CALL_LOG", "PROCESS_OUTGOING_CALLS", "REQUEST_INSTALL_PACKAGES", "QUERY_ALL_PACKAGES",
    "SYSTEM_ALERT_WINDOW", "BIND_ACCESSIBILITY_SERVICE", "BIND_NOTIFICATION_LISTENER_SERVICE"))
#: Xizmatni shu ruxsatlar bilan himoyalash = Accessibility / bildirishnoma tinglovchi - sideload'da to'siladi.
SENSITIVE_BINDS = frozenset({"android.permission.BIND_ACCESSIBILITY_SERVICE",
                             "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE"})

_V2, _V3, _V31 = 0x7109871A, 0xF05368C0, 0x1B93AD61
_SHA = {0x0101: hashlib.sha256, 0x0103: hashlib.sha256, 0x0201: hashlib.sha256, 0x0301: hashlib.sha256,
        0x0102: hashlib.sha512, 0x0104: hashlib.sha512, 0x0202: hashlib.sha512}
#: Resurs ID -> atribut nomi (aapt2 nomlarni olib tashlagan bo'lsa).
_RESID = {0x01010003: "name", 0x0101000F: "debuggable", 0x0101020C: "minSdkVersion",
          0x0101021B: "versionCode", 0x0101021C: "versionName", 0x01010270: "targetSdkVersion",
          0x01010271: "maxSdkVersion", 0x01010272: "testOnly", 0x01010006: "permission",
          0x010104EA: "extractNativeLibs"}


class Bad(Exception):
    """APK o'qilmadi (zip/manifest buzuq) - chiqish kodi 2."""


# --- imzo bloki ------------------------------------------------------------------------------------


def _lp(buf: bytes, pos: int) -> tuple[bytes, int]:
    n = struct.unpack_from("<I", buf, pos)[0]
    return buf[pos + 4:pos + 4 + n], pos + 4 + n


def _seq(buf: bytes) -> list[bytes]:
    items, pos = [], 0
    while pos < len(buf):
        item, pos = _lp(buf, pos)
        items.append(item)
    return items


def _signing_block(data: bytes) -> tuple[dict[int, bytes], int, int, int, int]:
    """-> (bloklar, blok boshi, markaziy katalog boshi, uning hajmi, EOCD)."""
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise Bad("zip oxiri (EOCD) topilmadi")
    cd_size, cd_off = struct.unpack_from("<II", data, eocd + 12)
    blocks: dict[int, bytes] = {}
    start = cd_off
    if data[cd_off - 16:cd_off] == b"APK Sig Block 42":
        size = struct.unpack_from("<Q", data, cd_off - 24)[0]
        start = cd_off - size - 8
        pos, end = start + 8, cd_off - 24
        while pos < end:
            ln, bid = struct.unpack_from("<QI", data, pos)
            blocks[bid] = data[pos + 12:pos + 8 + ln]
            pos += 8 + ln
    return blocks, start, cd_off, cd_size, eocd


def _chunked(data: bytes, hfn, start: int, cd_off: int, cd_size: int, eocd: int) -> bytes:
    """APK Signature Scheme v2 digest: 1 MB bo'laklar (zip yozuvlari, markaziy katalog, EOCD)."""
    tail = bytearray(data[eocd:])
    tail[16:20] = struct.pack("<I", start)
    digests, count = [], 0
    for sec in (data[0:start], data[cd_off:cd_off + cd_size], bytes(tail)):
        for i in range(0, len(sec), 1 << 20):
            chunk = sec[i:i + (1 << 20)]
            digests.append(hfn(b"\xa5" + struct.pack("<I", len(chunk)) + chunk).digest())
            count += 1
    return hfn(b"\x5a" + struct.pack("<I", count) + b"".join(digests)).digest()


def check_signature(data: bytes, problems: list[str], notes: list[str]) -> tuple[str | None, bool]:
    """v2 imzo va sertifikat -> (sertifikat SHA-256 hex katta harf yoki `None`, debug kalitmi)."""
    blocks, start, cd_off, cd_size, eocd = _signing_block(data)
    if _V2 not in blocks and _V3 not in blocks:
        problems.append("APK v2/v3 imzosiz - Android 11+ uni o'rnatmaydi (apksigner bilan imzolang)")
        return None, False
    schemes = [name for bid, name in ((_V2, "v2"), (_V3, "v3"), (_V31, "v3.1")) if bid in blocks]
    notes.append("imzo sxemalari: " + ", ".join(schemes))
    if _V2 not in blocks:
        notes.append("v2 bloki yo'q - digest tekshirilmadi (v3 bor)")
        return None, False
    signers, _ = _lp(blocks[_V2], 0)
    cert_fp, is_debug = None, False
    for signer in _seq(signers):
        signed, _ = _lp(signer, 0)
        digests, pos = _lp(signed, 0)
        certs, _ = _lp(signed, pos)
        for item in _seq(digests):
            alg = struct.unpack_from("<I", item, 0)[0]
            digest, _ = _lp(item, 4)
            if alg in _SHA and _chunked(data, _SHA[alg], start, cd_off, cd_size, eocd) != digest:
                problems.append("fayl imzodan keyin o'zgartirilgan (v2 digest mos emas) - qayta imzolang")
        chain = _seq(certs)
        if chain and cert_fp is None:
            der = chain[0]
            cert_fp = hashlib.sha256(der).hexdigest().upper()
            if cert_fp == PUBLIC_DEBUG_CERT:
                is_debug = True
                notes.append("sertifikat: React Native shablonidagi OCHIQ debug kalit")
            elif b"Android Debug" in der:
                # Har kompyuterning o'z ~/.android/debug.keystore i: ochiq emas, lekin build server
                # almashsa imzo ham almashadi - pilot ilovasi yangilanmay qoladi.
                is_debug = True
                notes.append("sertifikat: debug kalit (CN=Android Debug)")
    return cert_fp, is_debug


# --- binar AndroidManifest ---------------------------------------------------------------------------


def _u8len(b: bytes, p: int) -> tuple[int, int]:
    n = b[p]
    return (((n & 0x7F) << 8) | b[p + 1], p + 2) if n & 0x80 else (n, p + 1)


def parse_manifest(b: bytes) -> list[tuple[str, dict]]:
    """Binar XML -> [(teg, {atribut: qiymat})] (faqat boshlanuvchi teglar)."""
    if len(b) < 8 or struct.unpack_from("<H", b, 0)[0] != 0x0003:
        raise Bad("AndroidManifest.xml binar XML emas")
    strings: list[str] = []
    resmap: list[int] = []
    events: list[tuple[str, dict]] = []
    pos = struct.unpack_from("<H", b, 2)[0]
    while pos + 8 <= len(b):
        ctype, chs, csize = struct.unpack_from("<HHI", b, pos)
        if csize < 8:
            raise Bad("manifest bo'lagi buzuq")
        ch = b[pos:pos + csize]
        if ctype == 0x0001:
            count, _, flags, sstart, _ = struct.unpack_from("<IIIII", ch, 8)
            for off in struct.unpack_from("<%dI" % count, ch, chs):
                p = sstart + off
                if flags & 0x100:
                    _, p = _u8len(ch, p)
                    n, p = _u8len(ch, p)
                    strings.append(ch[p:p + n].decode("utf-8", "replace"))
                else:
                    n = struct.unpack_from("<H", ch, p)[0]
                    p += 2
                    if n & 0x8000:
                        n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", ch, p)[0]
                        p += 2
                    strings.append(ch[p:p + 2 * n].decode("utf-16-le", "replace"))
        elif ctype == 0x0180:
            resmap = list(struct.unpack_from("<%dI" % ((csize - chs) // 4), ch, chs))
        elif ctype == 0x0102:
            _, name, astart, asize, acount = struct.unpack_from("<IIHHH", ch, 16)
            attrs, ap = {}, 16 + astart
            for _ in range(acount):
                _, an, raw, _, _, vtype, vdata = struct.unpack_from("<IIIHBBI", ch, ap)
                key = strings[an] if an < len(strings) and strings[an] else None
                if not key and an < len(resmap):
                    key = _RESID.get(resmap[an], hex(resmap[an]))
                if vtype == 0x03:
                    val = strings[raw] if raw != 0xFFFFFFFF else strings[vdata]
                elif vtype == 0x12:
                    val = vdata != 0
                elif vtype in (0x10, 0x11):
                    val = vdata
                else:
                    val = (vtype, vdata)
                attrs[key] = val
                ap += asize
            events.append((strings[name], attrs))
        pos += csize
    return events


def check_manifest(events: list[tuple[str, dict]], package: str, problems: list[str],
                   notes: list[str]) -> None:
    manifest = next((a for t, a in events if t == "manifest"), {})
    sdk = next((a for t, a in events if t == "uses-sdk"), {})
    app = next((a for t, a in events if t == "application"), {})
    notes.append(f"paket {manifest.get('package')}, versiya {manifest.get('versionName')} "
                 f"(versionCode {manifest.get('versionCode')}), minSdk {sdk.get('minSdkVersion')}, "
                 f"targetSdk {sdk.get('targetSdkVersion')}")
    if manifest.get("package") != package:
        problems.append(f"paket nomi {manifest.get('package')!r}, kutilgan {package!r} - "
                        "o'rnatilgan ilova ustidan yangilanmaydi")
    target = sdk.get("targetSdkVersion")
    if not isinstance(target, int) or target < MIN_TARGET_SDK:
        problems.append(f"targetSdk {target} < {MIN_TARGET_SDK} - Play Protect \"eski ilova\" deb ogohlantiradi")
    if app.get("debuggable") is True:
        problems.append("android:debuggable=true - debug build tarqatilmaydi")
    if app.get("testOnly") is True:
        problems.append("android:testOnly=true - oddiy o'rnatishda \"App not installed\"")
    for tag, attrs in events:
        if tag in ("uses-permission", "uses-permission-sdk-23") and attrs.get("name") in SENSITIVE_PERMISSIONS:
            problems.append(f"Play Protect to'sadigan ruxsat: {attrs.get('name')}")
        if tag in ("service", "receiver", "activity") and attrs.get("permission") in SENSITIVE_BINDS:
            problems.append(f"{tag} {attrs.get('name')} {attrs.get('permission')} bilan - Play Protect "
                            "Telegram/brauzerdan o'rnatishni to'sadi")
        if tag == "meta-data" and attrs.get("name") in ("android.accessibilityservice",
                                                        "android.service.notification.NotificationListenerService"):
            problems.append(f"meta-data {attrs.get('name')} - Accessibility/bildirishnoma xizmati qolgan")


# --- zip joylashuvi ------------------------------------------------------------------------------------


def _data_offset(data: bytes, info: zipfile.ZipInfo) -> int:
    h = info.header_offset
    name_len, extra_len = struct.unpack_from("<HH", data, h + 26)
    return h + 30 + name_len + extra_len


def check_zip(data: bytes, zf: zipfile.ZipFile, events: list[tuple[str, dict]], problems: list[str],
              notes: list[str]) -> None:
    try:
        arsc = zf.getinfo("resources.arsc")
    except KeyError:
        problems.append("resources.arsc yo'q")
    else:
        if arsc.compress_type != zipfile.ZIP_STORED or _data_offset(data, arsc) % 4:
            problems.append("resources.arsc siqilgan yoki tekislanmagan - Android 11+ \"App not installed\" "
                            "(zipalign / apksigner tartibini tekshiring)")
    app = next((a for t, a in events if t == "application"), {})
    libs = [i for i in zf.infolist() if i.filename.startswith("lib/") and i.filename.endswith(".so")]
    abis = sorted({i.filename.split("/")[1] for i in libs})
    notes.append("ABI: " + (", ".join(abis) if abis else "native kutubxona yo'q"))
    if app.get("extractNativeLibs") is False:
        packed = [i.filename for i in libs if i.compress_type != zipfile.ZIP_STORED]
        if packed:
            problems.append(f"extractNativeLibs=false, lekin {len(packed)} ta .so siqilgan - o'rnatilmaydi "
                            f"(masalan {packed[0]})")
        unaligned = [i.filename for i in libs if i.compress_type == zipfile.ZIP_STORED and _data_offset(data, i) % 16384]
        if unaligned:
            notes.append(f"OGOHLANTIRISH: {len(unaligned)} ta .so 16 KB ga tekislanmagan (Android 15 16 KB "
                         "sahifali qurilmalarda muammo)")


# --- asosiy -------------------------------------------------------------------------------------------


def check(path: str, *, package: str = PACKAGE, expect_cert: str | None = None,
          allow_debug_key: bool = False) -> tuple[list[str], list[str]]:
    """-> (muammolar, izohlar). `Bad` - fayl o'qilmadi."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        zf = zipfile.ZipFile(path)
        manifest = zf.read("AndroidManifest.xml")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise Bad(f"APK o'qilmadi: {exc}") from exc
    problems: list[str] = []
    notes: list[str] = [f"hajm {len(data) / 1048576:.1f} MB"]
    if len(data) > TELEGRAM_MAX:
        notes.append("OGOHLANTIRISH: 50 MB dan katta - Telegram bot bu faylni yubora olmaydi (arm64 variantini bering)")
    cert, is_debug = check_signature(data, problems, notes)
    if cert is not None:
        notes.append(f"sertifikat SHA-256: {cert}")
        if is_debug and not allow_debug_key:
            problems.append("debug kalit bilan imzolangan - pilotga tarqatilmaydi (README 4: o'z release kalitingiz; "
                            "faqat o'zingiz sinash uchun --allow-debug-key)")
        if expect_cert:
            want = expect_cert.replace(":", "").strip().upper()
            if cert != want:
                problems.append("sertifikat kutilgan kalit emas (--expect-cert) - kalit almashsa o'rnatilgan "
                                "ilova yangilanmaydi")
    events = parse_manifest(manifest)
    check_manifest(events, package, problems, notes)
    check_zip(data, zf, events, problems, notes)
    return problems, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Barno AI reliz APK tekshiruvi (Play Protect va imzo)")
    ap.add_argument("apk")
    ap.add_argument("--expect-cert", help="kutilgan release sertifikati SHA-256 (apksigner verify --print-certs)")
    ap.add_argument("--allow-debug-key", action="store_true", help="debug kalitga ruxsat (faqat o'zingiz sinash uchun)")
    ap.add_argument("--package", default=PACKAGE)
    args = ap.parse_args(argv)
    try:
        problems, notes = check(args.apk, package=args.package, expect_cert=args.expect_cert,
                                allow_debug_key=args.allow_debug_key)
    except Bad as exc:
        print(f"XATO: {exc}", file=sys.stderr)
        return 2
    for note in notes:
        print(f"  - {note}")
    if problems:
        print(f"\nTARQATMANG - {len(problems)} ta muammo:")
        for item in problems:
            print(f"  x {item}")
        return 1
    print("\nOK - tarqatsa bo'ladi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
