"""
resale-watch scraper
=====================
メルカリ / ラクマ(fril) / 2nd STREET オンライン を新着順で巡回し、
config.json の条件に一致する新着商品を検出して
  - docs/data.json を更新(フロントエンドが表示するデータ)
  - Discord Webhook で通知
します。

★重要な注意★
このスクリプトはネットワークに接続できない開発環境で作成したため、
各サイトの実際のURL・HTML構造を直接確認できていません。
"SELECTOR / URL 要検証" とコメントした箇所は、実際に一度動かして
必ず調整してください(サイト側の仕様変更でも同様の調整が必要になります)。

設計方針として、クラス名のような変わりやすい部分に依存しすぎず、
商品詳細ページへの "URLパターン" を手がかりに商品カードを見つける
方式にしています(完全には壊れにくいですが、それでも検証は必須です)。
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DATA_PATH = BASE_DIR / "docs" / "data.json"
SEEN_PATH = BASE_DIR / "seen_ids.json"

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# ------------------------------------------------------------------
# サイトごとの設定(★ここが要検証ポイント★)
# ------------------------------------------------------------------
SITE_CONFIG = {
    "mercari": {
        "name": "メルカリ",
        # 要検証: 実際の検索URL・パラメータ名(new_search_condition_typeなど)
        "search_url": "https://jp.mercari.com/search?keyword={kw}&sort=created_time&order=desc",
        "item_url_pattern": re.compile(r"/item/m\d+"),
        "wait_selector": "a[href*='/item/m']",
    },
    "rakuma": {
        "name": "ラクマ",
        # 要検証: fril.jp の検索パラメータ(query, order, sort)
        "search_url": "https://fril.jp/s?query={kw}&order=created_at&sort=desc",
        "item_url_pattern": re.compile(r"/items/\d+"),
        "wait_selector": "a[href*='/items/']",
    },
    "2ndstreet": {
        "name": "2nd STREET",
        # 要検証: 2ndstreet.jp オンラインストアの検索パラメータ・並び順キー
        "search_url": "https://www.2ndstreet.jp/search?keyword={kw}&sort=new",
        "item_url_pattern": re.compile(r"/goods/detail/goods_id/\d+"),
        "wait_selector": "a[href*='/goods/detail/']",
    },
}

PRICE_RE = re.compile(r"[¥￥]\s?([\d,]{2,})|([\d,]{3,})\s?円")


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_price(text):
    m = PRICE_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    return int(raw.replace(",", ""))


async def fetch_search_results(page, site_key, keyword):
    """1サイト・1キーワード分の検索結果ページを開き、商品カードを抽出する"""
    site = SITE_CONFIG[site_key]
    url = site["search_url"].format(kw=quote(keyword))

    await page.goto(url, wait_until="networkidle", timeout=30000)
    try:
        await page.wait_for_selector(site["wait_selector"], timeout=15000)
    except Exception:
        # 商品が0件、またはセレクタが実サイトと一致していない可能性
        print(f"[warn] {site_key}: wait_selector が見つかりませんでした ({url})")

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    items = []
    seen_hrefs = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not site["item_url_pattern"].search(href):
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        full_url = href if href.startswith("http") else requests.compat.urljoin(url, href)

        # カード全体のテキスト・画像は、リンクの親要素をたどって探す(要検証)
        container = a_tag
        for _ in range(4):
            if container.parent:
                container = container.parent
            else:
                break

        text = container.get_text(" ", strip=True)
        img_tag = container.find("img")
        thumbnail = ""
        if img_tag:
            thumbnail = img_tag.get("src") or img_tag.get("data-src") or ""

        price = extract_price(text)
        # タイトルは alt テキストか、価格表記を除いた本文の先頭部分を採用
        title = (img_tag.get("alt") if img_tag and img_tag.get("alt") else text[:60]).strip()

        item_id = f"{site_key}:{full_url}"

        items.append(
            {
                "id": item_id,
                "site": site_key,
                "site_label": site["name"],
                "title": title or "(タイトル取得失敗)",
                "price": price,
                "thumbnail": thumbnail,
                "url": full_url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return items


def matches_search_condition(item, search):
    if item["site"] not in search["sites"]:
        return False
    if search.get("min_price") is not None and (item["price"] is None or item["price"] < search["min_price"]):
        return False
    if search.get("max_price") is not None and (item["price"] is None or item["price"] > search["max_price"]):
        return False
    # ブランド・カテゴリはタイトルに含まれるか簡易チェック(要検証: サイト側の構造化データが取れるならそちらを優先すべき)
    if search.get("brand") and search["brand"].lower() not in item["title"].lower():
        return False
    return True


def send_discord_notification(item, search_label):
    if not DISCORD_WEBHOOK_URL:
        print("[info] DISCORD_WEBHOOK_URL が未設定のため通知をスキップします")
        return
    price_text = f"¥{item['price']:,}" if item["price"] else "価格不明"
    payload = {
        "embeds": [
            {
                "title": item["title"][:250],
                "url": item["url"],
                "description": f"条件: {search_label}\n{item['site_label']} / {price_text}",
                "thumbnail": {"url": item["thumbnail"]} if item["thumbnail"] else None,
                "color": 0x5865F2,
            }
        ]
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code >= 300:
            print(f"[warn] Discord通知失敗: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[warn] Discord通知エラー: {e}")


async def run():
    if not CONFIG_PATH.exists():
        print("config.json が見つかりません。config.example.json をコピーして作成してください。")
        sys.exit(1)

    config = load_json(CONFIG_PATH, {})
    seen_ids = set(load_json(SEEN_PATH, []))
    existing_data = load_json(DATA_PATH, {"updated_at": None, "items": []})
    existing_items_by_id = {i["id"]: i for i in existing_data.get("items", [])}

    all_new_items = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )

        for search in config.get("searches", []):
            for site_key in search["sites"]:
                try:
                    print(f"[info] 巡回中: {search['label']} @ {site_key}")
                    results = await fetch_search_results(page, site_key, search["keyword"])
                except Exception as e:
                    print(f"[error] {site_key} / {search['label']} の取得に失敗: {e}")
                    continue

                for item in results:
                    is_new = item["id"] not in seen_ids
                    existing_items_by_id[item["id"]] = item  # 表示用データは常に最新で上書き

                    if is_new:
                        seen_ids.add(item["id"])
                        if matches_search_condition(item, search):
                            all_new_items.append((item, search["label"]))

        await browser.close()

    # 通知(config.notify.discord_enabled が true の場合のみ)
    if config.get("notify", {}).get("discord_enabled", True):
        for item, label in all_new_items:
            send_discord_notification(item, label)

    # docs/data.json 更新(新しい順に並べ、上限件数でトリム)
    merged_items = list(existing_items_by_id.values())
    merged_items.sort(key=lambda x: x["fetched_at"], reverse=True)
    max_items = config.get("max_items_kept", 500)
    merged_items = merged_items[:max_items]

    save_json(
        DATA_PATH,
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": merged_items,
        },
    )
    save_json(SEEN_PATH, list(seen_ids)[-5000:])  # 肥大化防止

    print(f"[done] 新着 {len(all_new_items)} 件を検出。docs/data.json を更新しました。")


if __name__ == "__main__":
    asyncio.run(run())
