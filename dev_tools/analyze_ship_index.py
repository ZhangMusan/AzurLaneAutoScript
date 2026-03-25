#!/usr/bin/env python3
"""
保存舰船图鉴页面内容以供分析
"""

import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
})

url = "https://wiki.biligame.com/blhx/%E8%88%B0%E8%88%B9%E5%9B%BE%E9%89%B4"

response = session.get(url, timeout=15)
response.encoding = 'utf-8'

html = response.text

# 分析页面中包含的链接
print("[DEBUG] 分析页面结构...")

# 查找所有链接
import re

# 方式1：查找 [[]] 格式的 Wiki 链接
wiki_links = re.findall(r'\[\[([^\[\]|]+)(?:\|[^\[\]]+)?\]\]', html)
print(f"[INFO] 找到 {len(wiki_links)} 个 [[]] 格式的链接")

# 方式2：查找 HTML <a> 标签
href_pattern = r'<a[^>]*?href="([^"]*)"[^>]*?title="([^"]*)"'
links = re.findall(href_pattern, html)
print(f"[INFO] 找到 {len(links)} 个 HTML 链接（带 title）")

# 方式3：直接从 <a> 标签的 title 属性提取舰娘名称
import re
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, 'html.parser')
all_links = soup.find_all('a', attrs={'title': True})

print(f"[INFO] BeautifulSoup 找到 {len(all_links)} 个带 title 的链接")

# 提取所有 title 属性
titles = set()
for link in all_links:
    title = link.get('title', '').strip()
    if title:
        titles.add(title)

print(f"[INFO] 不重复的 title 属性数: {len(titles)}")

# 过滤出可能是舰娘的 title
ship_names = set()
for title in titles:
    # 排除特殊的 title
    if not any(keyword in title for keyword in [
        "Category:", "Template:", "File:", "Help:", "Special:",
        "编辑", "讨论", "链接", "历史", "语言", "更多", "MediaWiki"
    ]):
        # 只保留合理长度的标题
        if 1 <= len(title) <= 80:
            ship_names.add(title)

print(f"[INFO] 过滤后的舰娘名称数: {len(ship_names)}")

# 输出前 50 个
sorted_ships = sorted(list(ship_names))
print(f"\n[INFO] 前 50 个舰娘（按字母序）:")
for i, name in enumerate(sorted_ships[:50]):
    print(f"  {i+1}. {name}")
