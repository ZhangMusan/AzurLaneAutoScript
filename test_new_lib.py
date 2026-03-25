#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import re
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent))

from module.retire.dock_scan_scanner import NameScanner

# 初始化扫描器（加载新库）
print("=== 测试新的库文件 ===")
scanner = NameScanner()
lib_size = len(scanner.wiki_lib)
print(f"✓ 库已加载: {lib_size} 条记录\n")

# 测试之前失败的舰娘名称
test_names = [
    ("大青花鱼(μ兵装)", "应该识别为 '大青花鱼'"),
    ("能代(μ兵装)", "应该识别为 '能代'"),
    ("龙骑兵·META", "应该识别为 '龙骑兵'"),
    ("大凤(μ兵装)", "应该识别为 '大凤'"),
    ("光辉(μ兵装)", "应该识别为 '光辉'"),
]

print("测试 match_known_name() 匹配效果:")
success_count = 0
for raw_name, desc in test_names:
    result = scanner.match_known_name(raw_name, level=0)
    status = "✓" if result and result != "" else "✗"
    if result and result != "":
        success_count += 1
    print(f"{status} '{raw_name}' → '{result}' ({desc})")
    
print(f"\n识别成功率: {success_count}/{len(test_names)}")
    
print("\n直接查询库中是否包含基础舰娘名:")
for raw_name, _ in test_names:
    # 手动剥离后缀
    normalized = re.sub(r'[（(]?[μuU][·\.\s]*兵装[）)]?$', '', raw_name)
    normalized = re.sub(r'[\.-]?改$', '', normalized)
    normalized = re.sub(r'·META$', '', normalized)
    
    # 查询
    if normalized in scanner.wiki_lib:
        print(f"✓ '{normalized}' 在库中 → '{scanner.wiki_lib[normalized]}'")
    else:
        print(f"✗ '{normalized}' 不在库中")
