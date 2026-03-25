#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

# 读取文件
with open('wiki_ship_names_auto.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 分离注释和数据
comment_lines = []
data_lines = []
for line in lines:
    if line.strip().startswith('#'):
        comment_lines.append(line)
    else:
        data_lines.append(line)

print(f"找到注释行: {len(comment_lines)}")
print(f"找到数据行: {len(data_lines)}")
print()

# 清理规则
def should_remove(name):
    name = name.strip()
    # 移除不应该在库中的变种名称
    if '·META' in name:  # 例: U-556·META
        return True
    if 'μ兵装' in name or '(μ兵装)' in name:  # 例: 大青花鱼(μ兵装)
        return True
    return False

# 清理数据
cleaned = [line for line in data_lines if not should_remove(line)]

print(f"删除前: {len(data_lines)} 行")
print(f"删除后: {len(cleaned)} 行")
print(f"删除数: {len(data_lines) - len(cleaned)} 行")
print()

# 显示删除的条目示例
removed = [line.strip() for line in data_lines if should_remove(line)]
print(f"删除的条目示例 (前35个):")
for item in removed[:35]:
    print(f"  - {item}")

# 写回文件
with open('wiki_ship_names_auto.txt', 'w', encoding='utf-8') as f:
    # 更新注释中的总数
    new_total = len(cleaned)
    for i, line in enumerate(comment_lines):
        if '总计:' in line:
            comment_lines[i] = f'# 总计: {new_total} 个舰娘\n'
    
    f.writelines(comment_lines)
    f.writelines(cleaned)

print()
print(f"✓ 文件已更新，新的总计: {new_total} 个舰娘")
