"""Xodimlar ro'yxatini ma'lumotnomaga yuklaydi yoki nusxasini oladi.

    cd apps/api
    venv/bin/python -m app.tools.contacts_import royxat.tsv --dry-run   # faqat tekshiruv
    venv/bin/python -m app.tools.contacts_import royxat.tsv             # yuklash
    venv/bin/python -m app.tools.contacts_import --export nusxa.csv     # nusxa

FAYL - jadvaldan nusxalangan matn (TAB bilan) yoki CSV, BIRINCHI QATOR sarlavha:
"F.I.SH | Telegram | Nomer | Email" (tartib va aniq nomi muhim emas).

QAYTA YUKLASH XAVFSIZ. Xodim avval email bo'yicha, bo'lmasa F.I.SH bo'yicha
topiladi: bor bo'lsa - fayldagi TO'LDIRILGAN maydonlar yangilanadi (bo'sh katak
mavjud qiymatni O'CHIRMAYDI), yo'q bo'lsa - qo'shiladi. Faylda yo'q xodim
o'chirilmaydi - o'chirish chat orqali, tasdiq bilan.

Har o'zgarish jurnalga `import:<fayl nomi>` nomidan yoziladi. Ekranga faqat
SONLAR va qator raqamlari chiqadi - shaxsiy ma'lumot emas.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys

from pathlib import Path

from ..services import contacts
from ..services.contacts import CLEANERS, FIELDS, ContactError

#: Sarlavhadagi so'z -> maydon (kichik harf, so'z boshi bo'yicha).
_HEADERS = (
    ("full_name", ("f.i.sh", "fish", "fio", "f.i.o", "ism", "xodim")),
    ("telegram", ("telegram", "tg")),
    ("phone", ("nomer", "telefon", "raqam", "phone", "tel")),
    ("email", ("email", "e-mail", "pochta", "mail", "brb tech email")),
)


def _columns(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, title in enumerate(header):
        low = title.strip().lower()
        for field, names in _HEADERS:
            if field not in found and any(low.startswith(n) or n in low for n in names):
                found[field] = index
                break
    if "full_name" not in found:
        raise SystemExit("Sarlavhada F.I.SH ustuni topilmadi (birinchi qator sarlavha bo'lishi kerak)")
    return found


def read_rows(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = "\t" if "\t" in lines[0] else (";" if lines[0].count(";") > lines[0].count(",") else ",")
    table = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    columns = _columns(table[0])
    rows = []
    for cells in table[1:]:
        rows.append({field: (cells[i] if i < len(cells) else "").strip() for field, i in columns.items()})
    return rows


def _key(name: str) -> str:
    return " ".join(contacts.skeleton(w) for w in contacts.name_parts(name))


def load(rows: list[dict[str, str]], *, actor: str, dry_run: bool = False) -> dict:
    """Natija: {"added", "updated", "same", "problems": [(qator, maydon, sabab)]}."""
    store = contacts.store
    report = {"added": 0, "updated": 0, "same": 0, "problems": []}
    existing = store.all()
    by_email = {e.email: e for e in existing if e.email}
    by_name = {_key(e.full_name): e for e in existing}
    for number, row in enumerate(rows, start=2):
        values: dict[str, str | None] = {}
        for field in FIELDS:
            try:
                values[field] = CLEANERS[field](row.get(field))
            except ContactError as exc:
                if field == "full_name":
                    report["problems"].append((number, field, str(exc)))
                    values = {}
                    break
                report["problems"].append((number, field, str(exc)))
                values[field] = None
        if not values:
            continue
        match = (by_email.get(values["email"]) if values.get("email") else None) or \
            by_name.get(_key(values["full_name"]))
        if match is None:
            if not dry_run:
                try:
                    added = store.add(values, actor=actor)
                except ContactError as exc:
                    report["problems"].append((number, "-", str(exc)))
                    continue
                by_name[_key(added.full_name)] = added
                if added.email:
                    by_email[added.email] = added
            report["added"] += 1
            continue
        changes = {f: v for f, v in values.items() if v and v != match.get(f) and f != "full_name"}
        if not changes:
            report["same"] += 1
            continue
        if not dry_run:
            try:
                store.update(match.id, changes, actor=actor)
            except ContactError as exc:
                report["problems"].append((number, "-", str(exc)))
                continue
        report["updated"] += 1
    return report


def export(path: Path) -> int:
    people = contacts.store.all()
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["F.I.SH", "Telegram", "Telefon", "Email"])
        for e in people:
            writer.writerow([e.full_name, e.telegram or "", e.phone or "", e.email or ""])
    path.chmod(0o600)
    return len(people)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Xodimlar ro'yxatini yuklash / nusxalash")
    parser.add_argument("file", nargs="?", type=Path, help="TSV yoki CSV (birinchi qator sarlavha)")
    parser.add_argument("--dry-run", action="store_true", help="faqat tekshiruv, yozilmaydi")
    parser.add_argument("--export", type=Path, help="ma'lumotnoma nusxasini CSV ga yozish")
    args = parser.parse_args(argv)
    if args.export:
        print(f"Yozildi: {export(args.export)} ta xodim -> {args.export}")
        return 0
    if not args.file:
        parser.error("fayl ko'rsatilmagan")
    rows = read_rows(args.file.read_text(encoding="utf-8-sig"))
    report = load(rows, actor=f"import:{args.file.name}", dry_run=args.dry_run)
    mode = "TEKSHIRUV (yozilmadi)" if args.dry_run else "yuklandi"
    print(f"{mode}: {len(rows)} qator -> qo'shildi {report['added']}, yangilandi {report['updated']}, "
          f"o'zgarmadi {report['same']}, muammo {len(report['problems'])}")
    for number, field, reason in report["problems"]:
        print(f"  {number}-qator, {field}: {reason}")
    print(f"Ma'lumotnomada jami: {contacts.store.count()} ta xodim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
