#!/usr/bin/env python3
"""测试过滤逻辑"""

import re

# 测试列表
test_items = [
    "META001",
    "META002",
    "Plan001",
    "Plan002",
    "T0",
    "T1",
    "T2",
    "T3",
    "T4",
    "120级加成",
    "正常舰娘",
    "BLACK★ROCK SHOOTER",
]

def is_valid_ship_name(title: str) -> bool:
    """检查是否是有效的舰娘名称"""
    
    # 排除长度不合理的
    if not (1 <= len(title) <= 80):
        return False
    
    # 排除测试数据/占位符
    if any(re.match(pattern, title) for pattern in [
        r'^META\d+$',      # META001-META999
        r'^Plan\d+$',      # Plan001-Plan999
        r'^T\d+$',         # T0-T999
    ]):
        return False
    
    # 排除系统标签
    if any(keyword in title for keyword in ["级加成"]):
        return False
    
    # 排除只包含数字和特殊符号的短标签
    if not re.search(r'[a-zA-Z\u4e00-\u9fff★●○■□△▲↓]', title):
        return False
    
    return True

for item in test_items:
    result = is_valid_ship_name(item)
    print(f"{item:20} -> {result}")
