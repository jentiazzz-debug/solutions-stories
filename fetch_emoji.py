"""Собрать assets/emoji.json из набора премиум-эмодзи.

    python fetch_emoji.py PR_Gram

Имя набора — то, что стоит в ссылке t.me/addemoji/<имя>. Скрипт спрашивает
у Telegram сам набор и раскладывает его в словарь «обычный эмодзи →
custom_emoji_id»: у каждого премиум-эмодзи есть привязанный к нему
обычный, и именно по нему бот потом подменяет символы в своих текстах.

Руками этот файл не пишется: двести идентификаторов по два десятка цифр
— гарантированная опечатка, которую видно только в проде.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter

import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = config.ASSETS_DIR / "emoji.json"


def fetch(name: str) -> list[dict]:
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getStickerSet?name={name}"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    if not payload.get("ok"):
        raise SystemExit(f"Telegram отказал: {payload.get('description')}")
    return payload["result"]["stickers"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    name = sys.argv[1].strip().rsplit("/", 1)[-1]
    stickers = fetch(name)

    kinds = Counter(s.get("type") for s in stickers)
    print(f"набор {name}: {len(stickers)} шт., типы: {dict(kinds)}")

    mapping: dict[str, str] = {}
    skipped = 0
    for sticker in stickers:
        emoji = sticker.get("emoji")
        custom_id = sticker.get("custom_emoji_id")
        if not emoji or not custom_id:
            skipped += 1
            continue
        #: На один обычный эмодзи в наборе может приходиться несколько
        #: премиальных. Берём первый: выбирать всё равно не из чего, а
        #: случайный каждый запуск дал бы разный вид одного и того же
        #: сообщения.
        mapping.setdefault(emoji, custom_id)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"в {OUT.name}: {len(mapping)} уникальных эмодзи"
          + (f", пропущено без id: {skipped}" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
