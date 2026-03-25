#!/usr/bin/env python3
"""
调试脚本：检查舰队科技页面的实际结构
"""

import requests
import re
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

url = "https://wiki.biligame.com/blhx/%E8%88%B0%E9%98%9F%E7%A7%91%E6%8A%80"
print(f"[DEBUG] 正在获取: {url}")

response = session.get(url, timeout=10)
response.encoding = 'utf-8'

html = response.text

print(f"[DEBUG] 页面大小: {len(html)} 字符")
print(f"[DEBUG] 状态码: {response.status_code}")

# 查找表格
table_count = len(re.findall(r'<table', html))
print(f"[DEBUG] 找到 {table_count} 个 <table> 标签")

# 查找所有链接
link_count = len(re.findall(r'<a\s+href="[^"]*"[^>]*>', html))
print(f"[DEBUG] 找到 {link_count} 个 <a> 标签")

# 使用 BeautifulSoup 查找表格
soup = BeautifulSoup(html, 'html.parser')
all_tables = soup.find_all('table')
print(f"[DEBUG] BeautifulSoup 找到 {len(all_tables)} 个表格")

# 检查第一个表格的结构
if all_tables:
    first_table = all_tables[0]
    rows = first_table.find_all('tr')
    print(f"[DEBUG] 第一个表格有 {len(rows)} 行")
    
    # 获取前 3 行的链接数量
    for i, row in enumerate(rows[:3]):
        cells = row.find_all(['td', 'th'])
        links_in_row = row.find_all('a')
        print(f"[DEBUG]   行 {i}: {len(cells)} 个单元格，{len(links_in_row)} 个链接")
        
        # 打印第一个链接
        if links_in_row:
            first_link = links_in_row[0]
            print(f"[DEBUG]     链接： {first_link.get('title', 'NO TITLE')} - {first_link.text}")

# 统计所有表格中的链接
total_links = 0
for table in all_tables:
    links = table.find_all('a')
    total_links += len(links)

print(f"[DEBUG] 所有表格中的链接总数: {total_links}")

# 尝试单独提取每个表格的舰娘
ship_names = set()
non_empty_tables = 0

for table_idx, table in enumerate(all_tables):
    rows = table.find_all('tr')
    table_ships = 0
    
    for row in rows[1:]:  # 跳过表头
        cells = row.find_all(['td', 'th'])
        
        if cells:
            # 尝试多种方式提取舰娘名称
            first_cell = cells[0]
            
            # 方式1：检查链接标签
            link = first_cell.find('a')
            ship_name = None
            
            if link:
                # 优先使用 title 属性
                ship_name = link.get('title', '').strip()
                
                # 如果没有 title，使用链接文本
                if not ship_name:
                    ship_name = link.text.strip()
                
                # 如果还是没有，检查其他属性
                if not ship_name:
                    href = link.get('href', '')
                    if '/wiki/' in href:
                        ship_name = href.split('/wiki/')[-1].replace('_', ' ')
            
            # 方式2：直接使用单元格文本
            if not ship_name:
                # 获取单元格中的所有文本
                cell_text = first_cell.text.strip()
                # 只取第一行或第一个单词
                lines = cell_text.split('\n')
                ship_name = lines[0].strip() if lines else ''
            
            ship_name = ship_name.strip()
            
            if ship_name and not ship_name.startswith('Category:') and len(ship_name) > 0:
                ship_names.add(ship_name)
                table_ships += 1
    
    if table_ships > 0:
        non_empty_tables += 1
        print(f"[DEBUG] 表格 {table_idx}: {table_ships} 个舰娘")

print(f"\n[INFO] 非空表格数: {non_empty_tables}")
print(f"[INFO] 总共提取了 {len(ship_names)} 个舰娘")

# 输出所有舰娘名称
print(f"\n[INFO] 提取的舰娘名称（共 {len(ship_names)} 个）:")
sorted_ships = sorted(list(ship_names))
for i, name in enumerate(sorted_ships):
    if i < 20 or i % 33 == 0:  # 打印样本
        print(f"  {i+1}. {name}")
    if i == 19:
        print(f"  ... ({len(sorted_ships) - 40} 更多) ...")

