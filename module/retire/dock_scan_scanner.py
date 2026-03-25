from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

import module.config.server as server
from module.base.utils import (
    color_similar,
    crop,
    limit_in,
    random_normal_distribution_int,
    random_rectangle_point,
)
from module.logger import logger
from module.ocr.ocr import Ocr
from module.retire.assets import DOCK_CHECK, SHIP_DETAIL_CHECK
from module.retire.dock import CARD_GRIDS, DOCK_SCROLL
from module.retire.scanner import (
    DHash,
    EmotionScanner,
    FleetScanner,
    HashGenerator,
    LevelScanner,
    RarityScanner,
    Scanner,
    StatusScanner,
)


CARD_NAME_GRIDS = CARD_GRIDS.crop(area=(4, 160, 134, 186), name="NAME")


@dataclass(frozen=True)
class DockShip:
    rarity: str = ""
    level: int = 0
    emotion: int = 0
    fleet: int = 0
    status: str = ""
    name: str = ""
    name_image: Any = field(default=None, repr=False)
    button: Any = None
    hash_: str = field(default="", repr=False)


class NameScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_NAME_GRIDS
        lang = "jp" if server.server == "jp" else "cnocr"
        self.ocr_white = Ocr(
            buttons=[button.area for button in self.grids.buttons],
            lang=lang,
            letter=(255, 255, 255),
            threshold=144,
        )
        self.ocr_pink = Ocr(
            buttons=[button.area for button in self.grids.buttons],
            lang=lang,
            letter=(236, 210, 205),
            threshold=136,
        )
        self.ocr_white.SHOW_LOG = False
        self.ocr_pink.SHOW_LOG = False

    @staticmethod
    def _name_score(name: str) -> int:
        if name == "Unknown":
            return -999
        cjk_count = sum(1 for ch in name if "\u4e00" <= ch <= "\u9fff")
        alnum_count = sum(1 for ch in name if ch.isalnum())
        punct_count = len(name) - cjk_count - alnum_count
        return cjk_count * 3 + alnum_count * 2 - punct_count * 2

    @staticmethod
    def _normalize_name(name: str) -> str:
        text = (name or "").strip()
        if not text:
            return "Unknown"

        compact = "".join(ch for ch in text if not ch.isspace())
        if not compact:
            return "Unknown"

        cjk_count = sum(1 for ch in compact if "\u4e00" <= ch <= "\u9fff")
        alnum_count = sum(1 for ch in compact if ch.isalnum())
        punct_count = len(compact) - cjk_count - alnum_count

        if cjk_count == 0 and alnum_count <= 1:
            return "Unknown"
        if cjk_count == 0 and punct_count >= alnum_count:
            return "Unknown"

        return compact

    def _merge_name(self, white_name: str, pink_name: str) -> str:
        white_norm = self._normalize_name(white_name)
        pink_norm = self._normalize_name(pink_name)
        if white_norm == pink_norm:
            return white_norm

        white_score = self._name_score(white_norm)
        pink_score = self._name_score(pink_norm)
        return white_norm if white_score >= pink_score else pink_norm

    def _scan(self, image) -> List[str]:
        if not self.grids.buttons:
            return []

        try:
            white_names = self.ocr_white.ocr(image)
            pink_names = self.ocr_pink.ocr(image)

            if isinstance(white_names, str):
                white_names = [white_names]
            if isinstance(pink_names, str):
                pink_names = [pink_names]

            count = len(self.grids.buttons)
            white_names = list(white_names) if isinstance(white_names, list) else []
            pink_names = list(pink_names) if isinstance(pink_names, list) else []

            if len(white_names) < count:
                white_names.extend([""] * (count - len(white_names)))
            if len(pink_names) < count:
                pink_names.extend([""] * (count - len(pink_names)))

            return [self._merge_name(white_names[i], pink_names[i]) for i in range(count)]
        except Exception as exc:
            logger.debug(f"NameScanner OCR error: {exc}")
            return ["Unknown"] * len(self.grids.buttons)

    def limit_value(self, value) -> str:
        return value if value else "any"

    def move(self, vector) -> None:
        super().move(vector)
        buttons = [button.area for button in self.grids.buttons]
        self.ocr_white.buttons = buttons
        self.ocr_pink.buttons = buttons


class ShipScannerWithName(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_GRIDS
        self.sub_scanners: Dict[str, Scanner] = {
            "level": LevelScanner(),
            "emotion": EmotionScanner(),
            "rarity": RarityScanner(),
            "fleet": FleetScanner(),
            "status": StatusScanner(),
            "name": NameScanner(),
            "hash": HashGenerator(),
        }

    def _scan(self, image) -> List[DockShip]:
        for scanner in self.sub_scanners.values():
            scanner.scan(image, cached=True)

        name_images = [crop(image, button.area, copy=True) for button in self.sub_scanners["name"].grids.buttons]

        candidates: List[DockShip] = [
            DockShip(
                level=level,
                emotion=emotion,
                rarity=rarity,
                fleet=fleet,
                status=status,
                name=name,
                name_image=name_image,
                button=button,
                hash_=hash_,
            )
            for level, emotion, rarity, fleet, status, name, name_image, button, hash_ in zip(
                self.sub_scanners["level"].results,
                self.sub_scanners["emotion"].results,
                self.sub_scanners["rarity"].results,
                self.sub_scanners["fleet"].results,
                self.sub_scanners["status"].results,
                self.sub_scanners["name"].results,
                name_images,
                self.grids.buttons,
                self.sub_scanners["hash"].results,
            )
        ]

        for scanner in self.sub_scanners.values():
            scanner.clear()

        return candidates

    def scan(self, image, cached=False, output=True):
        return super().scan(image, cached=cached, output=output)

    def move(self, vector) -> None:
        for scanner in self.sub_scanners.values():
            scanner.move(vector)
        super().move(vector)

    def limit_value(self, value) -> Any:
        return value


class DockScannerStandalone:
    SCAN_ZONE: Tuple[int, int, int, int] = (93, 55, 1219, 719)
    MAX_SCAN_ROUNDS: int = 180
    MAX_BOTTOM_NO_NEW_ROUNDS: int = 4

    def __init__(self, test_name: str = "") -> None:
        self._results: List[DockShip] = []
        self.scan_zone = self.SCAN_ZONE
        self.zone_top = self.scan_zone[1]
        self.zone_height = self.scan_zone[3] - self.scan_zone[1]
        self.grids_top = 76

        self.mean_color_set = deque(maxlen=2)
        self.moving_distance: float = 0
        self.bound: List[int] = []

        self._stable = False
        self._no_change = 0
        self.last_results: List[DockShip] = []
        self.retry = 0
        self.scan_rounds = 0
        self.bottom_no_new_rounds = 0

        self.scanner = ShipScannerWithName()

        self.save_debug_info = False
        self.debug_folder = f"./log/dock_scan_test/{test_name}_{int(time.time() * 1000):x}"
        if self.save_debug_info:
            os.makedirs(self.debug_folder, exist_ok=True)

        self.debug_info = {
            "time": 0,
            "ship_count": 0,
            "dock_size": 0,
            "ocr_mistake": 0,
            "reposition_retry": 0,
        }
        self.ocr_mistake_image = []
        self.extend_log = []
        self.moving_distance_log = []

    @property
    def stable(self) -> bool:
        if self._stable:
            self._stable = False
            return True
        return False

    @property
    def mean_color(self):
        return self.mean_color_set[-1] if self.mean_color_set else None

    @mean_color.setter
    def mean_color(self, value):
        self.mean_color_set.append(value)

    def no_change(self) -> bool:
        return self._no_change > 3

    def _find_bound(self, image) -> List[int]:
        image = crop(image, self.scan_zone)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        std = np.std(image, axis=1)
        move_avg = np.convolve(std, np.ones((5,)) / 5, mode="valid")
        gap_seq = list(np.nonzero(move_avg < 20)[0]) + [1000]

        bound = []
        start = 0
        for i in range(len(gap_seq) - 1):
            if gap_seq[i + 1] - gap_seq[i] > 50 and i + 1 - start > 10:
                bound.append(int(np.mean(gap_seq[start : i + 1])))
                start = i + 1
        if len(bound) > 1:
            bound[-1] = min(bound[-2] + 225, bound[-1])

        return bound

    def reset_position(self) -> None:
        offset = 76 - self.grids_top
        self.grids_top += offset
        self.scanner.move((0, offset))
        if self.mean_color_set:
            self.mean_color_set.append(self.mean_color_set[0])

    def reposition(self, image, bound: List[int]) -> None:
        scan_image = crop(image, self.scan_zone)
        if self.mean_color is not None:
            y = 0
            for y in range(0, 20):
                if not color_similar(np.mean(scan_image[bound[0] + y], axis=0), self.mean_color, 60):
                    break
            offset = y + self.zone_top + bound[0] + 1 - self.grids_top
            self.grids_top += offset
            self.scanner.move((0, offset))

        self.mean_color = np.mean(scan_image[bound[-1]], axis=0)

    def _remove_duplicate(self, results: List[DockShip]) -> int:
        if self._results:
            if all(old.hash_ == new.hash_ for new, old in zip(results, self._results[-len(results):])):
                self._no_change += 999 if len(results) < 14 else 1
                return 0
            if all(old.hash_ == new.hash_ for new, old in zip(results[:7], self._results[-7:])):
                self._results.extend(results[7 - len(results):])
                self._no_change = 999 if len(results) < 14 else 0
                return len(results) - 7

        self._no_change = 0
        self._results.extend(results)
        return len(results)

    def ensure_in_dock(self, main) -> None:
        if main.appear(SHIP_DETAIL_CHECK, offset=(30, 30)):
            main.ui_back(DOCK_CHECK)

    def _scan(self, image) -> int:
        bound = self._find_bound(image)
        if len(bound) == 1:
            self._stable = True
            return 0
        if len(bound) == 2:
            if self.bound != bound:
                self._stable = False
                self.bound = bound
                return 0
        else:
            self.bound.clear()

        self.moving_distance = bound[-1] - (self.zone_height - 204 * 2 - 23 * 3) / 2 * 1.5
        self.moving_distance_log.append(self.moving_distance)
        self.reposition(image, bound)
        results = self.scanner.scan(image, cached=False, output=False)

        if not results:
            self.retry += 1
            self.debug_info["reposition_retry"] += 1
            logger.info(f"No ship detected, reset position. Retry {self.retry} time(s)")
            self.reset_position()
            self.reposition(image, bound)
            results = self.scanner.scan(image, cached=False, output=False)
            if self.retry > 3:
                self.moving_distance = random_normal_distribution_int(10, 20)
                self.retry = 0
        else:
            self.retry = 0

        inc = 0
        if all(old.hash_ == new.hash_ for new, old in zip(results, self.last_results)):
            self._stable = True
            inc = self._remove_duplicate(results)

        self.last_results = results
        return inc

    def multi_scan(self, main) -> None:
        from module.retire.enhancement import OCR_DOCK_AMOUNT

        self.scan_rounds = 0
        self.bottom_no_new_rounds = 0

        try:
            self.debug_info["dock_size"], _, _ = OCR_DOCK_AMOUNT.ocr(main.device.image)
        except Exception:
            self.debug_info["dock_size"] = 0

        if DOCK_SCROLL.appear(main):
            DOCK_SCROLL.set_bottom(main)
            DOCK_SCROLL.set_top(main)

        start_time = time.time()
        while True:
            self.scan_rounds += 1
            if self.scan_rounds > self.MAX_SCAN_ROUNDS:
                logger.warning(f"Dock scan reached max rounds ({self.MAX_SCAN_ROUNDS}), stop to avoid dead loop")
                break

            inc = 0
            while not self.stable:
                main.device.screenshot()
                self.ensure_in_dock(main)
                inc = self._scan(main.device.image)

            has_scroll = DOCK_SCROLL.appear(main)
            at_bottom = has_scroll and DOCK_SCROLL.at_bottom(main)

            if inc > 0:
                self.bottom_no_new_rounds = 0
            elif at_bottom:
                self.bottom_no_new_rounds += 1
            else:
                self.bottom_no_new_rounds = 0

            if not has_scroll:
                break
            if self.bottom_no_new_rounds >= self.MAX_BOTTOM_NO_NEW_ROUNDS:
                logger.info(f"Dock scan converged at bottom after {self.bottom_no_new_rounds} no-new rounds")
                break
            if at_bottom and self.no_change():
                break

            click_zone_index = random_normal_distribution_int(0, 6)
            start = random_rectangle_point((240 + click_zone_index * 165, 555, 250 + click_zone_index * 165, 719))
            moving_distance = self.moving_distance
            if at_bottom:
                moving_distance = limit_in(moving_distance, 80, 140)
            end = (start[0], start[1] - moving_distance)
            sharp_end = (end[0] - 165, end[1])
            main.device.swipe(start, end)
            if main.device.click_record:
                main.device.click_record.pop()
            main.device.swipe(end, sharp_end)
            if main.device.click_record:
                main.device.click_record.pop()

        end_time = time.time()
        self.debug_info["time"] = end_time - start_time
        self.debug_info["ship_count"] = len(self._results)

        if self.save_debug_info:
            hashs = [ship.hash_ for ship in self._results]
            sims = []
            for i in range(len(hashs)):
                for j in range(i + 1, len(hashs)):
                    sims.append(DHash.distance(hashs[i], hashs[j]))
            np.save(f"{self.debug_folder}/{len(sims)}.npy", np.array(sims))
            logger.info(f"Debug info saved in {self.debug_folder}")

    def scan_whole_dock(self, main) -> List[DockShip]:
        self.multi_scan(main)
        return self._results
