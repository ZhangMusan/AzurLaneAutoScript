#!/usr/bin/env python3
"""检查分类 API 中是否有.改舰娘"""

import requests

WIKI_BASE_URL = "https://wiki.biligame.com/blhx"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
})

api_url = f"{WIKI_BASE_URL}/api.php"
continue_token = None
kai_ships = []

while True:
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:舰娘",
        "cmlimit": 500,
        "cmtype": "page",
        "format": "json",
    }
    
    if continue_token:
        params["cmcontinue"] = continue_token
    
    response = session.get(api_url, params=params, timeout=10)
    data = response.json()
    
    if "query" not in data or "categorymembers" not in data["query"]:
        break
    
    members = data["query"]["categorymembers"]
    for member in members:
        title = member.get("title", "").strip()
        if title and '改' in title:
            kai_ships.append(title)
    
    if "continue" not in data:
        break
    
    continue_token = data["continue"].get("cmcontinue")

print(f"分类 API：找到 {len(kai_ships)} 个包含'改'的舰娘")
print("\n前 40 个：")
for ship in sorted(set(kai_ships))[:40]:
    print(f"  - {ship}")

if len(set(kai_ships)) > 40:
    print(f"  ... 共 {len(set(kai_ships))} 个")
