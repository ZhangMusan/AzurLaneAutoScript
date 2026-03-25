from __future__ import annotations

import glob
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
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
ALLOWED_NAME_RE = re.compile(r'^[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9\-\.·]+$')


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


class PreparedOcr(Ocr):
    def pre_process(self, image):
        if image is None:
            return np.zeros((1, 1), dtype=np.uint8)
        if not isinstance(image, np.ndarray):
            image = np.array(image)
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        return image.astype(np.uint8)

    def ocr_preprocessed(self, images: List[np.ndarray]) -> List[str]:
        if not images:
            return []
        image_list = [self.pre_process(image) for image in images]
        result_list = self.cnocr.atomic_ocr_for_single_lines(image_list, self.alphabet)
        result_list = [''.join(result) for result in result_list]
        return [self.after_process(result) for result in result_list]


class NameScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_NAME_GRIDS
        self.name_images: List[np.ndarray] = []
        lang = "jp" if server.server == "jp" else "cnocr"
        self.ocr_model = PreparedOcr(buttons=[(0, 0, 1, 1)], lang=lang, name='DOCK_NAME_PREPARED_OCR')
        self.ocr_model.SHOW_LOG = False
        self.wiki_lib = self._load_wiki_library()
        self.wiki_keys = list(self.wiki_lib.keys())

    @staticmethod
    def _normalize_for_match(name: str) -> str:
        text = (name or "").strip()
        text = text.strip('`~_"\'“”‘’—–―‖，,。.；;：:！？!?（）()[]【】<>《》…|=^*')
        text = re.sub(r'["\'“”‘’`~_—–―‖，,。.；;：:！？!?（）()\[\]【】<>《》…|=^*]', '', text)
        text = re.sub(r'\s+', '', text)
        return text

    @classmethod
    def _normalize_wiki_name(cls, name: str) -> str:
        text = (name or "").strip()
        if len(text) % 2 == 0:
            half = len(text) // 2
            if text[:half] == text[half:]:
                text = text[:half]
        text = re.sub(r'\([^)]*\)', '', text)
        text = re.sub(r'（[^）]*）', '', text)
        return cls._normalize_for_match(text)

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio()

    @classmethod
    def _pick_best_fuzzy(cls, target: str, candidates: List[str]) -> Tuple[str, float]:
        best_name = ""
        best_score = 0.0
        for candidate in candidates:
            score = cls._similarity(target, candidate)
            if score > best_score:
                best_score = score
                best_name = candidate
        return best_name, best_score

    @classmethod
    def _load_wiki_library(cls) -> Dict[str, str]:
        base = Path(__file__).resolve().parents[2]
        lib: Dict[str, str] = {}
        patterns = [
            str(base / 'dev_tools' / 'wiki_ship_names_*.txt'),
            str(base / 'dev_tools' / 'wiki_ship_names_auto.txt'),
        ]
        files: List[str] = []
        for pattern in patterns:
            files.extend(glob.glob(pattern))
        files = sorted(set(files), reverse=True)

        if files:
            latest = Path(files[0])
            for line in latest.read_text(encoding='utf-8', errors='ignore').splitlines():
                raw = line.strip()
                if not raw or raw.startswith('#'):
                    continue
                normalized = cls._normalize_wiki_name(raw)
                if normalized:
                    # 扫描阶段直接输出 wiki 标准名，用于修正 OCR 原始结果。
                    lib[normalized] = raw

        manual = {
            '普莉茅斯': '普利茅斯',
            '前芷': '前卫',
            '奠斯科': '莫斯科',
            '海主星': '海天',
            '一信浓': '信浓',
            '朱丽里': '朱利奥凯撒',
            '俾斯麦Zwe': '俾斯麦Zwei',
            '博伊西μ兵装': '博伊西',
            '博伊西u兵装': '博伊西',
        }
        for key, value in manual.items():
            lib[cls._normalize_for_match(key)] = value
            lib[cls._normalize_for_match(value)] = value

        return lib

    def match_known_name(self, name: str, level: int) -> str:
        raw = (name or '').strip()
        if not raw or raw == 'Unknown' or not self.wiki_lib:
            return raw or 'Unknown'

        candidates: List[str] = []

        def add_candidate(text: str) -> None:
            normalized = self._normalize_for_match(text)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        add_candidate(raw)
        add_candidate(self._normalize_wiki_name(raw))
        add_candidate(raw.replace('干', '十'))
        add_candidate(raw.replace('厂', '广'))
        add_candidate(raw.replace('宫佐夫', '米哈伊尔'))
        add_candidate(raw.replace('宫佐关', '米哈伊尔'))
        add_candidate(re.sub(r'[（(]?[μuU][·\.\s]*兵装[）)]?$', '', raw))

        if raw.startswith('一') and len(raw) >= 3:
            add_candidate(raw[1:])

        merged = re.sub(r'[·\.\-]', '', raw)
        add_candidate(merged)
        add_candidate(re.sub(r'[\.-]?改$', '', raw))

        # OCR 偶发将 Z20 识别为 一20/2、I20_2 等形式，这里统一回退到 Z 前缀。
        z_alias = re.fullmatch(r'[一I]?(\d{2})(?:[\/_\-]?(\d))?', re.sub(r'\s+', '', raw))
        if z_alias:
            group2 = z_alias.group(2)
            group1 = z_alias.group(1)
            if not group2 or group2 == group1[0]:
                add_candidate(f'Z{group1}')

        compact = self._normalize_for_match(raw)
        if compact and len(compact) % 2 == 0:
            half = len(compact) // 2
            if compact[:half] == compact[half:]:
                add_candidate(compact[:half])

        for candidate in candidates:
            upper_candidate = candidate.upper() if re.fullmatch(r'[A-Za-z0-9\-\.]+', candidate) else candidate
            if upper_candidate in self.wiki_lib:
                return self.wiki_lib[upper_candidate]

        best_key = ''
        best_score = 0.0
        for candidate in candidates:
            query = candidate.upper() if re.fullmatch(r'[A-Za-z0-9\-\.]+', candidate) else candidate
            key, score = self._pick_best_fuzzy(query, self.wiki_keys)
            if not key:
                continue
            len_diff = abs(len(key) - len(query))
            if level >= 100:
                if score >= 0.72 and len_diff <= 4 and score > best_score:
                    best_key = key
                    best_score = score
            else:
                if score >= 0.86 and len_diff <= 2 and score > best_score:
                    best_key = key
                    best_score = score

        if best_key:
            return self.wiki_lib[best_key]

        normalized = self._normalize_for_match(raw)
        if normalized and normalized != raw and ALLOWED_NAME_RE.match(normalized):
            return normalized

        return raw

    @staticmethod
    def _match_name_band(image: np.ndarray) -> np.ndarray:
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return image

        if image.ndim == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        height = gray.shape[0]
        if height <= 26:
            return image

        band_height = min(26, height)
        profile = np.array([0.35, 0.55, 0.8, 1.0, 1.0, 1.0, 0.8, 0.55, 0.35], dtype=np.float32)
        profile = cv2.resize(profile.reshape(-1, 1), (1, band_height), interpolation=cv2.INTER_LINEAR).reshape(-1)
        darkness = 255.0 - gray.mean(axis=1)

        best_top = 0
        best_score = float('-inf')
        for top in range(0, height - band_height + 1):
            score = float(np.dot(darkness[top : top + band_height], profile))
            if score > best_score:
                best_score = score
                best_top = top

        top = max(0, best_top - 1)
        bottom = min(height, best_top + band_height + 1)
        return image[top:bottom, :]

    @staticmethod
    def _build_letter_binary(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2,
        )
        adaptive = cv2.bitwise_not(adaptive)
        otsu = cv2.bitwise_not(otsu)

        # 统一使用灰度阈值结果，避免依赖特定文字颜色通道。
        return cv2.min(otsu, adaptive)

    @classmethod
    def _tighten_name_crop(cls, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return image, np.zeros((1, 1), dtype=np.uint8)

        binary = cls._build_letter_binary(image)
        foreground = cv2.bitwise_not(binary)
        _, strong_foreground = cv2.threshold(foreground, 180, 255, cv2.THRESH_BINARY)
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 1))
        strong_foreground = cv2.morphologyEx(strong_foreground, cv2.MORPH_OPEN, kernel_open)
        strong_foreground = cv2.morphologyEx(strong_foreground, cv2.MORPH_CLOSE, kernel_close)

        coords = cv2.findNonZero(strong_foreground)
        if coords is None:
            coords = cv2.findNonZero(foreground)
        if coords is None:
            return image, binary

        x, y, width, height = cv2.boundingRect(coords)
        if width <= 0 or height <= 0:
            return image, binary

        roi_foreground = strong_foreground[y:y + height, x:x + width]
        if roi_foreground.size == 0:
            roi_foreground = foreground[y:y + height, x:x + width]

        text_top = y
        text_bottom = y + height
        if roi_foreground.size > 0:
            row_counts = np.count_nonzero(roi_foreground, axis=1)
            # 提高有效文字行阈值，尽量排除底部星星/边框等稀疏干扰。
            row_threshold = max(5, int(width * 0.08))
            valid_rows = np.where(row_counts >= row_threshold)[0]
            if valid_rows.size > 0:
                text_top = y + int(valid_rows[0])
                text_bottom = y + int(valid_rows[-1] + 1)

        pad_x = 4
        pad_y = 0
        left = max(0, x - pad_x)
        right = min(image.shape[1], x + width + pad_x)

        top = max(0, text_top - pad_y)
        bottom = min(image.shape[0], text_bottom + pad_y)

        # 保留最小高度，避免在细字/弱对比度场景被过度收紧。
        min_height = 18
        if bottom - top < min_height:
            mid = (top + bottom) // 2
            top = max(0, mid - min_height // 2)
            bottom = min(image.shape[0], top + min_height)

        return image[top:bottom, left:right], binary[top:bottom, left:right]

    @staticmethod
    def _extract_text_mask(primary_binary: np.ndarray) -> np.ndarray:
        if primary_binary is None or not isinstance(primary_binary, np.ndarray) or primary_binary.size == 0:
            return np.zeros((1, 1), dtype=np.uint8)

        # primary_binary 中文字区域接近黑色，转为前景白色便于连通域筛选。
        foreground = cv2.bitwise_not(primary_binary)
        _, foreground = cv2.threshold(foreground, 180, 255, cv2.THRESH_BINARY)

        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel_open)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel_close)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        filtered = np.zeros_like(foreground)
        for label in range(1, num_labels):
            x, y, width, height, area = stats[label]
            if area < 10:
                continue
            if width < 2 or height < 5:
                continue
            filtered[labels == label] = 255

        return filtered

    @classmethod
    def _prepare_ocr_images(cls, image: np.ndarray, binary: np.ndarray | None = None) -> List[np.ndarray]:
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return []

        primary = binary if binary is not None else cls._build_letter_binary(image)
        variants: List[np.ndarray] = [primary]

        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
        variants.append(clahe)

        # 白字和粉字是船名常见颜色，先做近色提取降低背景噪声。
        rgb = image.astype(np.float32)
        dist_white = np.sqrt(np.sum((rgb - np.array((255.0, 255.0, 255.0), dtype=np.float32)) ** 2, axis=2))
        dist_pink = np.sqrt(np.sum((rgb - np.array((236.0, 210.0, 205.0), dtype=np.float32)) ** 2, axis=2))
        color_mask = np.where((dist_white <= 92) | (dist_pink <= 70), 255, 0).astype(np.uint8)
        color_mask = cv2.morphologyEx(
            color_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)),
        )
        color_mask = cv2.morphologyEx(
            color_mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        )
        if np.count_nonzero(color_mask) >= 12:
            variants.append(cv2.bitwise_not(color_mask))

        text_mask = cls._extract_text_mask(primary)
        if isinstance(text_mask, np.ndarray) and text_mask.size > 0 and np.count_nonzero(text_mask) >= 10:
            variants.append(cv2.bitwise_not(text_mask))

        otsu_threshold, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if otsu_threshold > 0:
            variants.append(otsu)

        _, clahe_otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(clahe_otsu)

        adaptive = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            15,
            3,
        )
        variants.append(adaptive)

        adaptive_clahe = cv2.adaptiveThreshold(
            clahe,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            15,
            2,
        )
        variants.append(adaptive_clahe)

        deduped: List[np.ndarray] = []
        for variant in variants:
            if variant is None or variant.size == 0:
                continue

            variant = variant.astype(np.uint8)
            candidates = [variant, cv2.bitwise_not(variant)]
            for candidate in candidates:
                if not deduped or not np.array_equal(deduped[-1], candidate):
                    deduped.append(candidate)

                # 名称行高度普遍在 24~28，放大后 OCR 识别稳定性更高。
                if candidate.shape[0] <= 32:
                    up2 = cv2.resize(candidate, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    if not np.array_equal(deduped[-1], up2):
                        deduped.append(up2)
                if candidate.shape[0] <= 24:
                    up3 = cv2.resize(candidate, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
                    if not np.array_equal(deduped[-1], up3):
                        deduped.append(up3)

        if len(deduped) > 14:
            deduped = deduped[:14]
        return deduped

    def _normalize_ocr_list(self, output, count: int) -> List[str]:
        if isinstance(output, str):
            output = [output]
        output = list(output) if isinstance(output, list) else []
        if len(output) < count:
            output.extend([""] * (count - len(output)))
        return output[:count]

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
            results: List[str] = []
            self.name_images = []

            for button in self.grids.buttons:
                rough_crop = crop(image, button.area, copy=True)
                band_crop = self._match_name_band(rough_crop)
                final_crop, primary_binary = self._tighten_name_crop(band_crop)
                self.name_images.append(final_crop.copy() if isinstance(final_crop, np.ndarray) else rough_crop)

                prepared_images = self._prepare_ocr_images(final_crop, primary_binary)
                raw_names = self._normalize_ocr_list(self.ocr_model.ocr_preprocessed(prepared_images), len(prepared_images))

                candidate_names: List[str] = []
                for raw_name in raw_names:
                    normalized = self._normalize_name(raw_name)
                    if normalized not in candidate_names:
                        candidate_names.append(normalized)

                if not candidate_names:
                    results.append("Unknown")
                    continue

                # 若候选可被词库精确命中，优先选择该候选。
                exact_hits: List[str] = []
                for candidate in candidate_names:
                    query = self._normalize_for_match(candidate)
                    if not query:
                        continue
                    if re.fullmatch(r'[A-Za-z0-9\-\.]+', query):
                        query = query.upper()
                    if query in self.wiki_lib:
                        hit = self.wiki_lib[query]
                        if hit not in exact_hits:
                            exact_hits.append(hit)
                if exact_hits:
                    results.append(max(exact_hits, key=self._name_score))
                    continue

                results.append(max(candidate_names, key=self._name_score))

            return results
        except Exception as exc:
            logger.debug(f"NameScanner OCR error: {exc}")
            self.name_images = [crop(image, button.area, copy=True) for button in self.grids.buttons]
            return ["Unknown"] * len(self.grids.buttons)

    def limit_value(self, value) -> str:
        return value if value else "any"

    def clear(self) -> None:
        super().clear()
        self.name_images = []

    def move(self, vector) -> None:
        super().move(vector)
        buttons = [button.area for button in self.grids.buttons]
        self.ocr_model.buttons = buttons


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

        raw_names = self.sub_scanners["name"].results
        levels = self.sub_scanners["level"].results
        name_scanner = self.sub_scanners["name"]
        name_images = list(name_scanner.name_images)
        matched_names = [
            name_scanner.match_known_name(name=name, level=level)
            for name, level in zip(raw_names, levels)
        ]

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
                matched_names,
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
