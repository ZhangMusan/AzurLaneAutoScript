#!/usr/bin/env python3
"""
调试脚本：检查舰船图鉴页面的结构
"""

import requests
import re
from bs4 import BeautifulSoup

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
print(f"[DEBUG] 正在获取: {url}")

# 重试机制
for attempt in range(3):
    try:
        response = session.get(url, timeout=15)
        response.encoding = 'utf-8'
        
        print(f"[DEBUG] 尝试 {attempt + 1}/3 - 状态码: {response.status_code}")
        
        if response.status_code == 200:
            break
    except Exception as e:
        print(f"[DEBUG] 请求失败: {e}")
        continue
else:
    print(f"[ERROR] 所有重试都失败")
    import sys
    sys.exit(1)

html = response.text

print(f"[DEBUG] 页面大小: {len(html)} 字符")
print(f"[DEBUG] 状态码: {response.status_code}")

# 查找表格
table_count = len(re.findall(r'<table', html))
print(f"[DEBUG] 找到 {table_count} 个 <table> 标签")

# 使用 BeautifulSoup 查找表格
soup = BeautifulSoup(html, 'html.parser')
all_tables = soup.find_all('table')
print(f"[DEBUG] BeautifulSoup 找到 {len(all_tables)} 个表格")

# 检查每个表格的行数
for idx, table in enumerate(all_tables[:5]):  # 只检查前 5 个表格
    rows = table.find_all('tr')
    print(f"[DEBUG] 表格 {idx}: {len(rows)} 行")

# 尝试从所有表格中提取舰娘
ship_names = set()

for table_idx, table in enumerate(all_tables):
    rows = table.find_all('tr')
    table_ships = 0
    
    for row in rows[1:]:  # 跳过表头
        cells = row.find_all(['td', 'th'])
        
        if not cells or len(cells) < 1:
            continue
        
        # 第一列是舰娘名称
        first_cell = cells[0]
        
        # 提取舰娘名称
        ship_name = None
        
        # 方式1：链接标签
        link = first_cell.find('a')
        if link:
            ship_name = link.get('title', '').strip()
            if not ship_name:
                ship_name = link.text.strip()
            if not ship_name:
                href = link.get('href', '')
                if '/wiki/' in href:
                    ship_name = href.split('/wiki/')[-1].replace('_', ' ')
        
        # 方式2：直接文本
        if not ship_name:
            ship_name = first_cell.text.strip().split('\n')[0].strip()
        
        if ship_name and len(ship_name) > 0 and not any(
            keyword in ship_name for keyword in ["Category:", "Template:", "File:", "阵营", "分组", "编辑", "讨论"]
        ):
            ship_names.add(ship_name)
            table_ships += 1
    
    if table_ships > 0:
        print(f"[DEBUG] 表格 {table_idx}: {table_ships} 个舰娘")

print(f"\n[INFO] 总共提取了 {len(ship_names)} 个舰娘")

# 输出前 30 个舰娘名称
sorted_ships = sorted(list(ship_names))
print(f"\n[INFO] 提取的舰娘名称（前 30 个）:")
for i, name in enumerate(sorted_ships[:30]):
    print(f"  {i+1}. {name}")

print(f"\n... 还有 {len(sorted_ships) - 30} 个舰娘")
