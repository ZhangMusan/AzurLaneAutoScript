#!/usr/bin/env python3
"""检查舰船图鉴页面中是否有.改舰娘"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

WIKI_BASE_URL = "https://wiki.biligame.com/blhx"
SHIP_INDEX_PAGE = "舰船图鉴"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
})

url = f"{WIKI_BASE_URL}/{quote(SHIP_INDEX_PAGE)}"
response = session.get(url, timeout=10)
response.encoding = 'utf-8'

soup = BeautifulSoup(response.text, 'html.parser')
all_links = soup.find_all('a', attrs={'title': True})

kai_ships = []
for link in all_links:
    title = link.get('title', '').strip()
    if title and '改' in title:
        kai_ships.append(title)

print(f"舰船图鉴页面：找到 {len(kai_ships)} 个包含'改'的舰娘")
print("\n前 30 个：")
for ship in sorted(set(kai_ships))[:30]:
    print(f"  - {ship}")

if len(set(kai_ships)) > 30:
    print(f"  ... 共 {len(set(kai_ships))} 个")
