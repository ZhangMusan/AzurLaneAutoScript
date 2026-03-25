#!/usr/bin/env python3
"""
从碧蓝航线 Wiki 自动抓取舰娘名称词库
优先使用"舰队科技"列表页（覆盖 722 条科技点舰船），生成 wiki_ship_names_auto.txt

Usage:
    python wiki_ship_names_fetch.py  # 生成 wiki_ship_names_auto.txt
    python wiki_ship_names_fetch.py --archive  # 同时生成按日期归档的文件
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Set
from urllib.parse import quote, unquote

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("Error: Required package 'requests' is not installed.")
    print("Install it with: pip install requests")
    sys.exit(1)


class WikiShipNamesFetcher:
    """从碧蓝航线 Wiki 抓取舰娘名称"""

    # Wiki 主要链接（中文 Wiki）
    WIKI_BASE_URL = "https://wiki.biligame.com/blhx"
    
    # 舰队科技页面 - 包含所有可用的可建造舰船（722+ 条）
    FLEET_TECH_PAGE = "舰队科技"
    
    # 备用方案：全部舰娘分类页
    ALL_SHIPS_CATEGORY = "Category:舰娘"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = self._create_session()
        self.ship_names: Set[str] = set()

    def _create_session(self) -> requests.Session:
        """创建带重试机制的 requests Session"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        return session

    def fetch_from_fleet_tech_page(self) -> int:
        """
        从"舰队科技"页面抓取舰娘名称
        
        Returns:
            int: 新增的舰娘数量
        """
        print(f"[INFO] 正在从舰队科技页面获取舰娘名称...")
        try:
            # 构建 Wiki 页面 URL
            page_title = self.FLEET_TECH_PAGE
            url = f"{self.WIKI_BASE_URL}/{quote(page_title)}"
            
            response = self.session.get(url, timeout=self.timeout)
            response.encoding = 'utf-8'
            
            if response.status_code != 200:
                print(f"[WARN] 舰队科技页面请求失败 (status={response.status_code})")
                return 0
            
            html = response.text
            
            # 提取所有 Wiki链接（[[舰娘名称]] 格式）
            ship_links = self._extract_ship_links_from_html(html)
            
            before_count = len(self.ship_names)
            self.ship_names.update(ship_links)
            added = len(self.ship_names) - before_count
            
            print(f"[OK] 舰队科技页面：新增 {added} 个舰娘")
            return added

        except Exception as e:
            print(f"[ERROR] 获取舰队科技页面失败: {e}")
            return 0

    def fetch_from_category(self) -> int:
        """
        从"舰娘"分类页面抓取舰娘名称（使用 MediaWiki API）
        
        Returns:
            int: 新增的舰娘数量
        """
        print(f"[INFO] 正在从分类页面获取舰娘名称...")
        
        try:
            api_url = f"{self.WIKI_BASE_URL}/api.php"
            all_members = []
            continue_token = None
            
            # 分页获取所有分类成员
            while True:
                params = {
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": f"Category:舰娘",
                    "cmlimit": 500,
                    "cmtype": "page",
                    "format": "json",
                }
                
                if continue_token:
                    params["cmcontinue"] = continue_token
                
                response = self.session.get(api_url, params=params, timeout=self.timeout)
                response.encoding = 'utf-8'
                
                if response.status_code != 200:
                    print(f"[WARN] API 请求失败 (status={response.status_code})")
                    break
                
                data = response.json()
                
                if "query" not in data or "categorymembers" not in data["query"]:
                    print("[WARN] API 返回格式异常")
                    break
                
                members = data["query"]["categorymembers"]
                all_members.extend(members)
                
                # 检查是否有下一页
                if "continue" not in data:
                    break
                
                continue_token = data["continue"].get("cmcontinue")
            
            before_count = len(self.ship_names)
            
            # 提取舰娘名称（过滤掉重定向等）
            for member in all_members:
                title = member.get("title", "").strip()
                if title and not title.startswith("Category:"):
                    self.ship_names.add(title)
            
            added = len(self.ship_names) - before_count
            print(f"[OK] 分类页面：新增 {added} 个舰娘（总计 {len(self.ship_names)} 个）")
            return added

        except Exception as e:
            print(f"[ERROR] 获取分类页面失败: {e}")
            return 0

    def _extract_ship_links_from_html(self, html: str) -> Set[str]:
        """
        从 HTML 中提取 Wiki 链接中的舰娘名称
        
        匹配格式: [[舰娘名称]] 或 [[舰娘名称|显示名]]
        """
        ships = set()
        
        # 匹配 [[...]] 中的链接
        pattern = r'\[\[([^\[\]|]+)(?:\|[^\[\]]+)?\]\]'
        matches = re.findall(pattern, html)
        
        for match in matches:
            # 过滤掉非舰娘相关的链接
            title = match.strip()
            
            # 排除分类、模板、文件等
            if any(title.startswith(prefix) for prefix in ["Category:", "Template:", "File:", "Module:"]):
                continue
            
            # 排除无关链接
            if any(keyword in title for keyword in ["编辑", "讨论", "链接", "历史", "更多"]):
                continue
            
            # 只保留合理长度的标题
            if 1 <= len(title) <= 50:
                ships.add(title)
        
        return ships

    def save_to_file(self, output_path: Path, archive: bool = False) -> bool:
        """
        保存舰娘名称到文件
        
        Args:
            output_path: 输出文件路径
            archive: 是否同时生成按日期归档的文件
            
        Returns:
            bool: 是否成功保存
        """
        if not self.ship_names:
            print("[ERROR] 没有获取到任何舰娘名称")
            return False
        
        try:
            # 准备内容
            sorted_names = sorted(self.ship_names)
            content = "# 碧蓝航线舰娘名称词库\n"
            content += f"# 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            content += f"# 总计: {len(sorted_names)} 个舰娘\n\n"
            content += "\n".join(sorted_names)
            
            # 保存主文件
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding='utf-8')
            print(f"[OK] 已保存到: {output_path}")
            
            # 保存归档文件（可选）
            if archive:
                archive_filename = f"wiki_ship_names_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                archive_path = output_path.parent / archive_filename
                archive_path.write_text(content, encoding='utf-8')
                print(f"[OK] 已保存归档到: {archive_path}")
            
            return True

        except Exception as e:
            print(f"[ERROR] 保存文件失败: {e}")
            return False

    def run(self, archive: bool = False) -> bool:
        """
        执行完整的抓取流程
        
        Args:
            archive: 是否生成按日期归档的文件
            
        Returns:
            bool: 是否成功完成
        """
        print("[INFO] 开始抓取舰娘名称...")
        print(f"[INFO] Wiki 地址: {self.WIKI_BASE_URL}")
        
        # 优先使用舰队科技页面
        self.fetch_from_fleet_tech_page()
        
        # 备用方案：使用分类页面补充
        if len(self.ship_names) < 500:
            print("[INFO] 舰队科技页面获取结果不足，改用分类页面补充...")
            self.fetch_from_category()
        
        if len(self.ship_names) < 100:
            print(f"[WARN] 获取的舰娘数量过少 ({len(self.ship_names)}), 可能存在网络或页面问题")
        
        print(f"\n[INFO] 总计获取 {len(self.ship_names)} 个舰娘")
        
        # 确定输出路径
        script_dir = Path(__file__).parent
        output_path = script_dir / "wiki_ship_names_auto.txt"
        
        # 保存文件
        success = self.save_to_file(output_path, archive=archive)
        
        if success:
            print("\n[SUCCESS] 舰娘名称库更新完成！")
        
        return success


def main():
    parser = argparse.ArgumentParser(
        description="从碧蓝航线 Wiki 抓取舰娘名称词库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python wiki_ship_names_fetch.py              # 生成 wiki_ship_names_auto.txt
  python wiki_ship_names_fetch.py --archive    # 同时保存带日期戳的归档文件
        """,
    )
    
    parser.add_argument(
        "--archive",
        action="store_true",
        help="生成按日期戳归档的文件",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="网络请求超时时间（秒，默认 10）",
    )
    
    args = parser.parse_args()
    
    fetcher = WikiShipNamesFetcher(timeout=args.timeout)
    success = fetcher.run(archive=args.archive)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
