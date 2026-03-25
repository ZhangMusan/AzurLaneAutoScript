#!/usr/bin/env python3
"""检查舰船图鉴页面中是否包含22和33"""

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

titles = []
for link in all_links:
    title = link.get('title', '').strip()
    if title and title in ['22', '33']:
        titles.append(title)
    # 也收集数字范围
    if title and title.isdigit() and len(title) in [1, 2, 3]:
        titles.append(title)

# 去重并排序
unique_titles = sorted(set(titles), key=lambda x: (len(x), x))

print(f"找到的数字舰娘: {unique_titles[:50]}")
print(f"22是否存在: {'22' in unique_titles}")
print(f"33是否存在: {'33' in unique_titles}")
