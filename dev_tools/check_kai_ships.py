#!/usr/bin/env python3
"""检查舰队科技页面中是否有.改舰娘"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

WIKI_BASE_URL = "https://wiki.biligame.com/blhx"
FLEET_TECH_PAGE = "舰队科技"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
})

url = f"{WIKI_BASE_URL}/{quote(FLEET_TECH_PAGE)}"
response = session.get(url, timeout=10)
response.encoding = 'utf-8'

soup = BeautifulSoup(response.text, 'html.parser')
tables = soup.find_all('table', {'class': 'wikitable'})

print(f"找到 {len(tables)} 个表格\n")

for table_idx, table in enumerate(tables):
    rows = table.find_all('tr')
    kai_ships = []
    
    for row in rows[1:]:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        
        first_cell = cells[0]
        link = first_cell.find('a')
        
        if link:
            title = link.get('title', '').strip()
            if title and '改' in title:
                kai_ships.append(title)
    
    if kai_ships:
        print(f"表格 {table_idx}：找到 {len(kai_ships)} 个.改舰娘")
        for ship in kai_ships[:10]:
            print(f"  - {ship}")
        if len(kai_ships) > 10:
            print(f"  ... 共 {len(kai_ships)} 个")
        print()
