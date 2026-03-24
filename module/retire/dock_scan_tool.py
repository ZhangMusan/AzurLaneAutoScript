from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from module.daemon.daemon_base import DaemonBase
from module.logger import logger
from module.retire.dock import Dock
from module.ui.page import page_dock

from module.retire.dock_scan_postprocess import process_dock_scan_result
from module.retire.dock_scan_scanner import DockScannerStandalone, DockShip


class DockScanTool(DaemonBase, Dock):
    """
    内置船坞扫描工具类。

    Pages:
        in: page_dock
        out: page_dock
    """

    def run_dock_scan(self, do_postprocess: bool = False, base_dir: str = ".") -> Dict[str, object]:
        """
        执行全船坞扫描，并可选执行后处理导出。

        Args:
            do_postprocess: 是否执行名称纠错与 CSV 导出。
            base_dir: 导出文件根目录。

        Returns:
            dict: 扫描结果摘要。
        """
        logger.hr("Dock Scan Tool", level=1)
        logger.info(f"Output files directory: {Path(base_dir).resolve()}")

        self.ui_ensure(page_dock)

        logger.hr("Scanning Dock", level=2)
        scanner = DockScannerStandalone()
        ships: List[DockShip] = scanner.scan_whole_dock(self)

        logger.hr("Scan Results", level=2)
        logger.info(f"Total ships scanned: {len(ships)}")

        if not ships:
            logger.warning("No ships found in dock")
            return {
                "ok": True,
                "ships": [],
                "ship_count": 0,
                "artifacts": {},
            }

        rarity_stat = {}
        level_stat = {}
        for ship in ships:
            rarity = ship.rarity or "Unknown"
            rarity_stat[rarity] = rarity_stat.get(rarity, 0) + 1

            level = ship.level or 0
            level_range = f"{(level // 10) * 10}-{(level // 10 + 1) * 10 - 1}"
            level_stat[level_range] = level_stat.get(level_range, 0) + 1

        logger.hr("Rarity Distribution", level=3)
        for rarity in sorted(rarity_stat.keys()):
            logger.attr(rarity, rarity_stat[rarity])

        logger.hr("Level Distribution", level=3)
        for level_range in sorted(level_stat.keys()):
            logger.attr(level_range, level_stat[level_range])

        logger.hr("Ship List", level=3)
        for ship in ships:
            ship_name = ship.name if ship.name else "Unknown"
            logger.info(f"{ship_name:<15} Lv.{ship.level:<3} Rarity: {ship.rarity}")

        artifacts = {}
        if do_postprocess:
            logger.hr("Post Process", level=2)
            artifacts = process_dock_scan_result(ships, base_dir=base_dir)
            logger.attr("Raw CSV", artifacts.get("raw_csv", ""))
            logger.attr("Cleaned CSV", artifacts.get("cleaned_csv", ""))
            logger.attr("Matched CSV", artifacts.get("matched_csv", ""))
            logger.attr("Unresolved CSV", artifacts.get("unresolved_csv", ""))
            logger.attr("Match Report CSV", artifacts.get("report_csv", ""))
        else:
            logger.info("Post process disabled")

        return {
            "ok": True,
            "ships": ships,
            "ship_count": len(ships),
            "artifacts": artifacts,
        }
