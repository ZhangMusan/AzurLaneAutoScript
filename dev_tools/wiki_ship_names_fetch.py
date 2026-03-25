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

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Warning: 'beautifulsoup4' not installed, falling back to regex parsing")
    BeautifulSoup = None


class WikiShipNamesFetcher:
    """从碧蓝航线 Wiki 抓取舰娘名称"""

    # Wiki 主要链接（中文 Wiki）
    WIKI_BASE_URL = "https://wiki.biligame.com/blhx"
        # 舰船图鉴页面 - 包含所有舰娘（含无科技点的）
    SHIP_INDEX_PAGE = "舰船图鉴"
        # 舰队科技页面 - 包含所有可用的可建造舰船（722+ 条）
    FLEET_TECH_PAGE = "舰队科技"
    
    # 备用方案：全部舰娘分类页
    ALL_SHIPS_CATEGORY = "Category:舰娘"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = self._create_session()
        self.ship_names: Set[str] = set()

    def _create_session(self) -> requests.Session:
        """创建带重试机制和完整请求头的 requests Session"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504, 567],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        return session

    def fetch_from_ship_index_page(self) -> int:
        """
        从"舰船图鉴"页面抓取舰娘名称（849+ 条，包含所有舰娘）
        
        Returns:
            int: 新增的舰娘数量
        """
        print(f"[INFO] 正在从舰船图鉴页面获取舰娘名称...")
        try:
            # 构建 Wiki 页面 URL
            page_title = self.SHIP_INDEX_PAGE
            url = f"{self.WIKI_BASE_URL}/{quote(page_title)}"
            
            response = self.session.get(url, timeout=self.timeout)
            response.encoding = 'utf-8'
            
            if response.status_code != 200:
                print(f"[WARN] 舰船图鉴页面请求失败 (status={response.status_code})")
                return 0
            
            html = response.text
            before_count = len(self.ship_names)
            
            # 从 HTML 中直接提取所有 title 属性
            ship_titles = self._extract_ships_from_page_titles(html)
            
            self.ship_names.update(ship_titles)
            added = len(self.ship_names) - before_count
            
            print(f"[OK] 舰船图鉴页面：新增 {added} 个舰娘")
            return added

        except Exception as e:
            print(f"[ERROR] 获取舰船图鉴页面失败: {e}")
            return 0
    
    def _extract_ships_from_page_titles(self, html: str) -> Set[str]:
        """
        从 HTML 中提取所有 <a> 标签的 title 属性作为舰娘名称
        """
        ships = set()
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # 查找所有带 title 属性的链接
            all_links = soup.find_all('a', attrs={'title': True})
            
            for link in all_links:
                title = link.get('title', '').strip()
                
                if not title:
                    continue
                
                # 排除特殊的 title（分类、模板等）
                if any(keyword in title for keyword in [
                    "Category:", "Template:", "File:", "Help:", "Special:",
                    "编辑", "讨论", "链接", "历史", "语言", "更多", "MediaWiki",
                    "级加成"
                ]):
                    continue
                
                # 排除测试数据/占位符（META001-058, Plan001-042, T0-T4等）
                if any(re.match(pattern, title) for pattern in [
                    r'^META\d+$',      # META001-META999
                    r'^Plan\d+$',      # Plan001-Plan999
                    r'^T\d+$',         # T0-T999
                ]):
                    continue
                
                # 只保留合理长度的标题
                if 1 <= len(title) <= 80 and len(title.strip()) > 0:
                    ships.add(title)
            
            print(f"[DEBUG] 从舰船图鉴页面提取了 {len(ships)} 个舰娘")
            
        except Exception as e:
            print(f"[WARN] 舰船图鉴解析失败: {e}")
        
        return ships

    def fetch_from_fleet_tech_page(self) -> int:
        """
        从"舰队科技"页面抓取舰娘名称（722+ 条）
        
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
            before_count = len(self.ship_names)
            
            # 优先使用 BeautifulSoup 解析表格
            if BeautifulSoup:
                ship_links = self._extract_ships_from_fleet_tech_tables(html)
            else:
                ship_links = self._extract_ship_links_from_html(html)
            
            self.ship_names.update(ship_links)
            added = len(self.ship_names) - before_count
            
            print(f"[OK] 舰队科技页面：新增 {added} 个舰娘")
            return added

        except Exception as e:
            print(f"[ERROR] 获取舰队科技页面失败: {e}")
            return 0
    
    def _extract_ships_from_fleet_tech_tables(self, html: str) -> Set[str]:
        """
        使用 BeautifulSoup 从舰队科技页面的表格中提取舰娘名称
        
        舰队科技页面包含按舰种分类的表格，最后一个大表格包含 722 个舰娘
        """
        ships = set()
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # 查找所有表格
            tables = soup.find_all('table', {'class': 'wikitable'})
            
            if not tables:
                # 尝试查找任何包含链接的表格
                tables = soup.find_all('table')
            
            for table_idx, table in enumerate(tables):
                rows = table.find_all('tr')
                table_count = 0
                
                for row in rows[1:]:  # 跳过表头
                    cells = row.find_all(['td', 'th'])
                    
                    if not cells:
                        continue
                    
                    # 第一个单元格通常是舰娘名称/链接
                    first_cell = cells[0]
                    
                    # 多种方式提取舰娘名称
                    ship_name = None
                    
                    # 方式1：检查链接标签
                    link = first_cell.find('a')
                    if link:
                        # 优先使用 title 属性
                        ship_name = link.get('title', '').strip()
                        
                        # 如果没有 title，使用链接文本
                        if not ship_name:
                            ship_name = link.text.strip()
                        
                        # 如果还是没有，检查 href 属性
                        if not ship_name:
                            href = link.get('href', '')
                            if '/wiki/' in href:
                                ship_name = href.split('/wiki/')[-1].replace('_', ' ')
                    
                    # 方式2：直接使用单元格文本
                    if not ship_name:
                        cell_text = first_cell.text.strip()
                        lines = cell_text.split('\n')
                        ship_name = lines[0].strip() if lines else ''
                    
                    ship_name = ship_name.strip()
                    
                    # 过滤掉无效的名称
                    if not ship_name:
                        continue
                    
                    # 排除特殊关键词
                    if any(keyword in ship_name for keyword in ["Category:", "Template:", "File:", "阵营", "分组", "编辑", "讨论"]):
                        continue
                    
                    # 排除纯单个数字（但允许 22, 33 等有效舰娘名称）
                    if ship_name.isdigit() and len(ship_name) == 1:
                        continue
                    
                    # 排除大于等于3位的纯数字（如 100-131, 004 等）
                    # 除非是已知的有效数字舰娘
                    known_numeric_ships = {"22", "33"}
                    if ship_name.isdigit() and ship_name not in known_numeric_ships:
                        continue
                    
                    # 排除测试数据/占位符（META001-058, Plan001-042, T0-T4等）
                    if any(re.match(pattern, ship_name) for pattern in [
                        r'^META\d+$',      # META001-META999
                        r'^Plan\d+$',      # Plan001-Plan999
                        r'^T\d+$',         # T0-T999
                    ]):
                        continue
                    
                    # 排除系统标签
                    if any(keyword in ship_name for keyword in ["级加成"]):
                        continue
                    
                    ships.add(ship_name)
                    table_count += 1
                
                if table_count > 0:
                    print(f"[DEBUG] 舰队科技表格 {table_idx}: 提取 {table_count} 个舰娘")
            
            print(f"[DEBUG] BeautifulSoup 从表格提取了 {len(ships)} 个舰娘")
            
        except Exception as e:
            print(f"[WARN] BeautifulSoup 解析失败: {e}，尝试回退到正则表达式")
            ships = self._extract_ship_links_from_html(html)
        
        return ships

    def fetch_from_category(self) -> int:
        """
        从"舰娘"分类页面抓取舰娘名称（使用 MediaWiki API）
        支持多个分类来确保完整性
        
        Returns:
            int: 新增的舰娘数量
        """
        print(f"[INFO] 正在从分类页面获取舰娘名称...")
        
        before_count = len(self.ship_names)
        
        # 尝试多个相关分类
        categories = [
            "Category:舰娘",
            "Category:可建造舰舰娘", 
        ]
        
        for category in categories:
            try:
                api_url = f"{self.WIKI_BASE_URL}/api.php"
                continue_token = None
                category_count = 0
                
                # 分页获取所有分类成员
                while True:
                    params = {
                        "action": "query",
                        "list": "categorymembers",
                        "cmtitle": category,
                        "cmlimit": 500,
                        "cmtype": "page",
                        "format": "json",
                    }
                    
                    if continue_token:
                        params["cmcontinue"] = continue_token
                    
                    response = self.session.get(api_url, params=params, timeout=self.timeout)
                    response.encoding = 'utf-8'
                    
                    if response.status_code != 200:
                        print(f"[WARN] {category} API 请求失败 (status={response.status_code})")
                        break
                    
                    data = response.json()
                    
                    if "query" not in data or "categorymembers" not in data["query"]:
                        print(f"[WARN] {category} API 返回格式异常")
                        break
                    
                    members = data["query"]["categorymembers"]
                    
                    # 提取舰娘名称（过滤掉重定向等）
                    for member in members:
                        title = member.get("title", "").strip()
                        if not title or title.startswith("Category:"):
                            continue
                        
                        # 排除测试数据/占位符（META001-058, Plan001-042, T0-T4等）
                        if any(re.match(pattern, title) for pattern in [
                            r'^META\d+$',      # META001-META999
                            r'^Plan\d+$',      # Plan001-Plan999
                            r'^T\d+$',         # T0-T999
                        ]):
                            continue
                        
                        # 排除系统标签
                        if any(keyword in title for keyword in ["级加成"]):
                            continue
                        
                        # 排除纯数字舰娘除了已知的（22, 33）
                        known_numeric_ships = {"22", "33"}
                        if title.isdigit() and title not in known_numeric_ships:
                            continue
                        
                        self.ship_names.add(title)
                        category_count += 1
                    
                    # 检查是否有下一页
                    if "continue" not in data:
                        break
                    
                    continue_token = data["continue"].get("cmcontinue")
                
                if category_count > 0:
                    print(f"[OK] {category}：新增 {category_count} 个舰娘")

            except Exception as e:
                print(f"[ERROR] 获取 {category} 失败: {e}")
                continue
        
        added = len(self.ship_names) - before_count
        print(f"[INFO] 分类页面总计：新增 {added} 个舰娘（当前共 {len(self.ship_names)} 个）")
        return added

    def _extract_ship_links_from_html(self, html: str) -> Set[str]:
        """
        从 HTML 中提取舰娘名称，支持多种格式
        
        支持格式：
        - [[舰娘名称]] 或 [[舰娘名称|显示名]]（Wiki链接）
        - <a href="/wiki/舰娘名称">舰娘名称</a>（HTML链接）
        """
        ships = set()
        
        # 方式1：匹配 [[...]] 中的链接
        pattern = r'\[\[([^\[\]|]+)(?:\|[^\[\]]+)?\]\]'
        matches = re.findall(pattern, html)
        
        for match in matches:
            # 过滤掉非舰娘相关的链接
            title = match.strip()
            
            # 排除分类、模板、文件等
            if any(title.startswith(prefix) for prefix in ["Category:", "Template:", "File:", "Module:"]):
                continue
            
            # 排除无关链接
            if any(keyword in title for keyword in ["编辑", "讨论", "链接", "历史", "更多", "查看"]):
                continue
            
            # 只保留合理长度的标题
            if 1 <= len(title) <= 50:
                ships.add(title)
        
        # 方式2：匹配 HTML <a> 标签中的链接（如果没有使用 BeautifulSoup）
        # <a href="/wiki/..."  title="...">...</a>
        html_pattern = r'<a\s+href="[^"]*"[^>]*title="([^"]+)"[^>]*>'
        matches = re.findall(html_pattern, html)
        
        for match in matches:
            title = match.strip()
            
            # 同样的过滤条件
            if any(title.startswith(prefix) for prefix in ["Category:", "Template:", "File:", "Module:"]):
                continue
            
            if any(keyword in title for keyword in ["编辑", "讨论", "链接", "历史", "更多", "查看"]):
                continue
            
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
        
        # 优先使用舰船图鉴页面（最完整，有 849 个舰娘）
        ship_index_count = self.fetch_from_ship_index_page()
        
        # 使用舰队科技页面补充（如果舰船图鉴页面失败或缺漏）
        fleet_tech_count = self.fetch_from_fleet_tech_page()
        
        # 无论前两者结果如何，都使用分类 API 补充
        # 这确保我们能获取到所有的舰娘
        print("[INFO] 使用分类 API 补充舰娘数据...")
        self.fetch_from_category()
        
        if len(self.ship_names) < 300:
            print(f"[WARN] 获取的舰娘数量过少 ({len(self.ship_names)}), 可能存在网络或页面问题")
            return False
        
        print(f"\n[INFO] 总计获取 {len(self.ship_names)} 个舰娘")
        print(f"[INFO]   - 舰船图鉴页面: {ship_index_count} 个")
        print(f"[INFO]   - 舰队科技页面: {fleet_tech_count} 个")
        print(f"[INFO]   - 分类 API: {len(self.ship_names) - ship_index_count - fleet_tech_count} 个 (可能有重复)")

        
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
