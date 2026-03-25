#!/usr/bin/env python3
"""搜索纪德相关舰娘"""

import requests

api_url = 'https://wiki.biligame.com/blhx/api.php'
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})

params = {
    'action': 'query',
    'list': 'categorymembers',
    'cmtitle': 'Category:舰娘',
    'cmlimit': 500,
    'cmtype': 'page',
    'format': 'json'
}

response = session.get(api_url, params=params)
data = response.json()

ships = [m['title'] for m in data['query']['categorymembers']]

# 搜索纪德相关
print("搜索纪德相关舰娘：")
for ship in ships:
    if '纪德' in ship or '吉德' in ship:
        print(f"  {ship}")

# 搜索德相关的所有舰娘（取前20个）
print("\n德相关的舰娘（前20个）：")
count = 0
for ship in sorted(ships):
    if '德' in ship and count < 20:
        print(f"  {ship}")
        count += 1
