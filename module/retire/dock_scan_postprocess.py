from __future__ import annotations

import csv
import glob
import re
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

import module.config.server as server
from module.logger import logger
from module.retire.dock_scan_scanner import NameScanner, PreparedOcr

SYMBOLS = set('`~_"\'“”‘’—–―‖，,。；;：:！？!?（）()[]【】<>《》…•ˇ′=|^*')
ALLOWED_RE = re.compile(r'^[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9\-\.·]+$')
# OCR同音字误认容错表：常见的同音误字和多笔误字纠正
# 格式：{'错误字': '正确字', ...}
HOMOPHONE_CORRECTION = {
    # 常见同音误字
    '拉菲': '拉菲',  # 保留以作示例
    '茶': '茶',      # 同音的形近字
    '材': '才',      # 常见笔误
    '土': '士',      # 常见笔误
    '门': '闷',      # 同音
    '方': '芳',      # 同音
    '相': '湘',      # 同音
    '乡': '香',      # 同音
    '长': '昌',      # 同音
    '常': '尝',      # 同音
    '章': '张',      # 同音
    '商': '伤',      # 同音
    '生': '声',      # 同音
    '胜': '升',      # 同音
    '声': '生',      # 同音
    '升': '胜',      # 同音  
    '城': '成',      # 同音
    '成': '城',      # 同音
    '层': '曾',      # 同音
    '曾': '层',      # 同音
    # 可继续扩展
}
_RESCAN_OCR_CACHE: Dict[str, PreparedOcr] = {}
_RESCAN_OCR_CACHE_MAX = 16


def _get_rescan_ocr(lang: str) -> PreparedOcr:
    key = lang
    cached = _RESCAN_OCR_CACHE.get(key)
    if cached is not None:
        return cached

    if len(_RESCAN_OCR_CACHE) >= _RESCAN_OCR_CACHE_MAX:
        _RESCAN_OCR_CACHE.pop(next(iter(_RESCAN_OCR_CACHE)))

    ocr = PreparedOcr(buttons=[(0, 0, 1, 1)], lang=lang, name='DOCK_NAME_RESCAN_PREPARED_OCR')
    ocr.SHOW_LOG = False
    _RESCAN_OCR_CACHE[key] = ocr
    return ocr


def _normalize_for_match(name: str) -> str:
    text = (name or "").strip()
    text = text.strip('`~_"\'“”‘’—–―‖，,。.；;：:！？!?（）()[]【】<>《》…|=^*')
    text = re.sub(r'["\'“”‘’`~_—–―‖，,。.；;：:！？!?（）()\[\]【】<>《》…|=^*]', '', text)
    text = re.sub(r'\s+', '', text)
    return text

def _apply_homophone_correction(name: str) -> str:
    """
    应用同音字和多笔字纠正，提升已知舰娘的匹配率。
    对识别结果中的常见OCR误字进行纠正。
    """
    if not name:
        return name
    
    # 单个字符级别的纠正
    result = name
    for wrong_char, correct_char in HOMOPHONE_CORRECTION.items():
        if wrong_char in result and len(wrong_char) == 1:
            result = result.replace(wrong_char, correct_char)
    
    return result

def _normalize_wiki_name(name: str) -> str:
    s = (name or "").strip()
    if len(s) % 2 == 0:
        half = len(s) // 2
        if s[:half] == s[half:]:
            s = s[:half]
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'（[^）]*）', '', s)
    return _normalize_for_match(s)


def _has_residual_symbol(name: str) -> bool:
    if not name:
        return False
    if any(ch in SYMBOLS for ch in name):
        return True
    return not bool(ALLOWED_RE.match(name))


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _pick_best_fuzzy(target: str, candidates: List[str]) -> Tuple[str, float]:
    best_name = ""
    best_score = 0.0
    for cand in candidates:
        score = _similarity(target, cand)
        if score > best_score:
            best_score = score
            best_name = cand
    return best_name, best_score


def _rescan_vote_match(name: str, level: int, wiki_lib: Dict[str, str], wiki_keys: List[str]) -> Tuple[str, str, float]:
    raw = (name or "").strip()
    # 应用同音字和多笔字纠正，提升匹配率
    raw_corrected = _apply_homophone_correction(raw)
    
    candidates: List[str] = []

    def add_candidate(text: str) -> None:
        t = _normalize_for_match(text)
        if t and t not in candidates:
            candidates.append(t)

    # 使用纠正后的原始值作为第一个候选
    add_candidate(raw_corrected)
    add_candidate(_normalize_wiki_name(raw_corrected))
    add_candidate(raw_corrected.replace('干', '十'))
    add_candidate(raw_corrected.replace('厂', '广'))
    add_candidate(raw_corrected.replace('宫佐夫', '米哈伊尔'))
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

    compact = _normalize_for_match(raw)
    if compact and len(compact) % 2 == 0:
        half = len(compact) // 2
        if compact[:half] == compact[half:]:
            add_candidate(compact[:half])

    best_key = ''
    best_score = 0.0
    best_loose_key = ''
    best_loose_score = 0.0

    for cand in candidates:
        is_alnum = bool(re.fullmatch(r'[A-Za-z0-9\-\.]+', cand))
        if is_alnum:
            cand = cand.upper()

        if cand in wiki_lib:
            return wiki_lib[cand], 'rescan_vote_exact', 1.0

        key, score = _pick_best_fuzzy(cand, wiki_keys)
        if not key:
            continue

        len_diff = abs(len(key) - len(cand))
        if level >= 100:
            if score >= 0.72 and len_diff <= 4 and score > best_score:
                best_key = key
                best_score = score
        else:
            if score >= 0.86 and len_diff <= 2 and score > best_score:
                best_key = key
                best_score = score

        # 严格规则未命中时，允许中文名称做一层宽松兜底，提升实际舰名修正覆盖率。
        cjk_count = sum(1 for ch in cand if '\u4e00' <= ch <= '\u9fff')
        if (not is_alnum) and cjk_count >= 2:
            if score >= 0.66 and len_diff <= 6 and score > best_loose_score:
                best_loose_key = key
                best_loose_score = score

    if best_key:
        return wiki_lib[best_key], 'rescan_vote', best_score
    if best_loose_key:
        return wiki_lib[best_loose_key], 'rescan_vote_loose', best_loose_score
    return name, 'unresolved', 0.0


def _rescan_ocr_from_image(name_image: np.ndarray, level: int, wiki_lib: Dict[str, str], wiki_keys: List[str]) -> Tuple[str, str, float]:
    if name_image is None or not isinstance(name_image, np.ndarray):
        return '', 'unresolved', 0.0
    if name_image.size == 0:
        return '', 'unresolved', 0.0

    lang = 'jp' if server.server == 'jp' else 'cnocr'
    prepared_images = NameScanner._prepare_ocr_images(name_image)
    if not prepared_images:
        return '', 'unresolved', 0.0

    candidates: List[str] = []
    try:
        ocr = _get_rescan_ocr(lang=lang)
        for text in ocr.ocr_preprocessed(prepared_images):
            normalized = _normalize_for_match(str(text or ''))
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    except Exception:
        return '', 'unresolved', 0.0

    if not candidates:
        return '', 'unresolved', 0.0

    best_key = ''
    best_score = 0.0
    for cand in candidates:
        if cand in wiki_lib:
            return wiki_lib[cand], 'rescan_ocr_exact', 1.0

        key, score = _pick_best_fuzzy(cand, wiki_keys)
        if not key:
            continue

        len_diff = abs(len(key) - len(cand))
        if level >= 100:
            if score >= 0.72 and len_diff <= 4 and score > best_score:
                best_key = key
                best_score = score
        else:
            if score >= 0.86 and len_diff <= 2 and score > best_score:
                best_key = key
                best_score = score

    if best_key:
        return wiki_lib[best_key], 'rescan_ocr', best_score
    return '', 'unresolved', 0.0


def _load_wiki_library(base: Path) -> Dict[str, str]:
    lib: Dict[str, str] = {}

    patterns = [
        str(base / 'dev_tools' / 'wiki_ship_names_*.txt'),
        str(base / 'dev_tools' / 'wiki_ship_names_auto.txt'),
    ]
    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files), reverse=True)

    if files:
        latest = Path(files[0])
        for line in latest.read_text(encoding='utf-8', errors='ignore').splitlines():
            raw = line.strip()
            if not raw or raw.startswith('#'):
                continue
            std = _normalize_wiki_name(raw)
            if std:
                lib[std] = raw

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
    for k, v in manual.items():
        lib[_normalize_for_match(k)] = v
        lib[_normalize_for_match(v)] = v

    return lib


def _write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['index', 'name', 'level', 'rarity'])
        writer.writeheader()
        writer.writerows(rows)


def _write_report_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['index', 'before', 'after', 'method', 'score', 'level', 'rarity'],
        )
        writer.writeheader()
        writer.writerows(rows)


def _export_unresolved(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['index', 'before', 'level', 'rarity'])
        writer.writeheader()
        writer.writerows(rows)


def _sanitize_filename(text: str) -> str:
    value = (text or 'Unknown').strip()
    value = re.sub(r'[\\/:*?"<>|\s]+', '_', value)
    value = value.strip('._')
    return value or 'Unknown'


def _save_name_crop(path: Path, image: np.ndarray) -> bool:
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    output = image
    if image.ndim == 3 and image.shape[2] == 3:
        output = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    return bool(cv2.imwrite(str(path), output))


def _is_empty_slot_row(row: dict) -> bool:
    name = (row.get('name') or '').strip()
    level = int(row.get('level') or 0)
    rarity = (row.get('rarity') or '').strip().lower()
    return level == 0 and rarity == 'unknown' and name in ('', 'Unknown')


def _export_name_crops(
    ships: list,
    rows: List[dict],
    output_dir: Path,
    unresolved_indexes: set[int] | None = None,
    non_tail_unknown_indexes: set[int] | None = None,
) -> Tuple[int, int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    unresolved_saved = 0
    non_tail_unknown_saved = 0

    for row in rows:
        idx = int(row['index'])
        ship = ships[idx - 1] if 0 < idx <= len(ships) else None
        image = getattr(ship, 'name_image', None) if ship else None
        filename = (
            f"{idx:04d}_lv{int(row['level'] or 0):03d}_"
            f"{_sanitize_filename(row['rarity'])}_"
            f"{_sanitize_filename(row['name'])}.png"
        )
        if _save_name_crop(output_dir / filename, image):
            saved += 1

        if unresolved_indexes and idx in unresolved_indexes:
            unresolved_dir = output_dir / 'unresolved'
            if _save_name_crop(unresolved_dir / filename, image):
                unresolved_saved += 1

        if non_tail_unknown_indexes and idx in non_tail_unknown_indexes:
            non_tail_unknown_dir = output_dir / 'non_tail_unknown'
            if _save_name_crop(non_tail_unknown_dir / filename, image):
                non_tail_unknown_saved += 1

    return saved, unresolved_saved, non_tail_unknown_saved


def process_dock_scan_result(ships: list, base_dir: str = '.') -> Dict[str, str]:
    base = Path(base_dir).resolve()
    today = date.today().strftime('%Y%m%d')

    raw_csv = base / f'dock_scan_results_{today}.csv'
    cleaned_backup_csv = base / f'dock_scan_results_{today}_cleaned.before_auto.csv'
    cleaned_csv = base / f'dock_scan_results_{today}_cleaned.csv'
    matched_csv = base / f'dock_scan_results_{today}_matched.csv'
    unresolved_csv = base / f'dock_scan_symbol_unresolved_{today}.csv'
    report_csv = base / f'dock_scan_symbol_match_report_{today}.csv'
    name_crop_dir = base / f'dock_scan_name_crops_{today}'

    raw_rows: List[dict] = []
    ship_by_index: Dict[int, object] = {}
    for i, ship in enumerate(ships, 1):
        ship_by_index[i] = ship
        raw_rows.append(
            {
                'index': i,
                'name': (getattr(ship, 'name', '') or 'Unknown').strip(),
                'level': int(getattr(ship, 'level', 0) or 0),
                'rarity': (getattr(ship, 'rarity', '') or 'unknown').strip(),
            }
        )
    _write_csv(raw_csv, raw_rows)

    if cleaned_csv.exists():
        cleaned_backup_csv.write_bytes(cleaned_csv.read_bytes())

    source_rows = list(raw_rows)

    wiki_lib = _load_wiki_library(base)
    wiki_keys = list(wiki_lib.keys())

    symbol_rows = 0
    fixed_rows = 0
    rescan_fixed_rows = 0
    clean_fixed_rows = 0
    unresolved_rows: List[dict] = []
    matched_rows: List[dict] = []
    report_rows: List[dict] = []

    for row in source_rows:
        idx = int(row['index'])
        name = (row['name'] or '').strip()
        level = str(row['level']).strip()
        rarity = (row['rarity'] or '').strip()
        level_int = int(level or 0)

        # 应用同音字和多笔字纠正，提升匹配率
        name_corrected = _apply_homophone_correction(name)
        
        final_name = name_corrected
        polluted = _has_residual_symbol(name_corrected)
        normalized = _normalize_for_match(name_corrected)
        method = 'clean'
        score = ''

        if polluted:
            symbol_rows += 1

        if name_corrected not in ('Unknown', ''):
            # 优先使用 wiki 标准名回填，确保 OCR 输出统一到实际舰娘名称。
            if normalized in wiki_lib:
                final_name = wiki_lib[normalized]
                if final_name != name_corrected:
                    method = 'wiki_exact'
                    score = '1.0'
                    clean_fixed_rows += 1
            else:
                ship_obj = ship_by_index.get(idx)
                name_image = getattr(ship_obj, 'name_image', None) if ship_obj else None

                ocr_name, ocr_method, ocr_score = _rescan_ocr_from_image(
                    name_image=name_image,
                    level=level_int,
                    wiki_lib=wiki_lib,
                    wiki_keys=wiki_keys,
                )
                if ocr_method in ('rescan_ocr', 'rescan_ocr_exact') and ocr_name and ocr_name != name_corrected:
                    final_name = ocr_name
                    method = ocr_method
                    score = f'{ocr_score:.4f}'
                    rescan_fixed_rows += 1
                else:
                    voted_name, voted_method, voted_score = _rescan_vote_match(
                        name=name_corrected,
                        level=level_int,
                        wiki_lib=wiki_lib,
                        wiki_keys=wiki_keys,
                    )
                    if voted_method in ('rescan_vote', 'rescan_vote_exact', 'rescan_vote_loose') and voted_name and voted_name != name_corrected:
                        final_name = voted_name
                        method = voted_method
                        score = f'{voted_score:.4f}' if voted_score else ''
                        if polluted:
                            rescan_fixed_rows += 1
                        else:
                            clean_fixed_rows += 1
                    elif polluted:
                        method = 'unresolved'

        if method == 'unresolved':
            unresolved_rows.append(
                {
                    'index': idx,
                    'before': name_corrected,
                    'level': level,
                    'rarity': rarity,
                }
            )

        if final_name != name_corrected:
            fixed_rows += 1

        matched_rows.append(
            {
                'index': idx,
                'name': final_name,
                'level': level,
                'rarity': rarity,
            }
        )

        if method != 'clean':
            report_rows.append(
                {
                    'index': idx,
                    'before': name_corrected,
                    'after': final_name,
                    'method': method,
                    'score': score,
                    'level': level,
                    'rarity': rarity,
                }
            )

    # 非舰娘空位仅应出现在扫描末尾：仅将末尾连续空位视为有效空位。
    tail_empty_indexes: set[int] = set()
    for row in reversed(matched_rows):
        if _is_empty_slot_row(row):
            tail_empty_indexes.add(int(row['index']))
            continue
        break

    unresolved_index_set = {int(row['index']) for row in unresolved_rows}
    non_tail_unknown_indexes: set[int] = set()
    for row in matched_rows:
        idx = int(row['index'])
        name = (row['name'] or '').strip()
        level = str(row['level']).strip()
        rarity = (row['rarity'] or '').strip()

        should_mark_unknown = False
        if name == 'Unknown' and not _is_empty_slot_row(row):
            should_mark_unknown = True
        elif _is_empty_slot_row(row) and idx not in tail_empty_indexes:
            should_mark_unknown = True

        if should_mark_unknown and idx not in unresolved_index_set:
            unresolved_rows.append(
                {
                    'index': idx,
                    'before': name,
                    'level': level,
                    'rarity': rarity,
                }
            )
            report_rows.append(
                {
                    'index': idx,
                    'before': name,
                    'after': name,
                    'method': 'unknown_non_tail',
                    'score': '',
                    'level': level,
                    'rarity': rarity,
                }
            )
            unresolved_index_set.add(idx)
            non_tail_unknown_indexes.add(idx)

    _write_csv(matched_csv, matched_rows)
    _write_csv(cleaned_csv, matched_rows)
    _export_unresolved(unresolved_csv, unresolved_rows)
    _write_report_csv(report_csv, report_rows)
    unresolved_indexes = {int(row['index']) for row in unresolved_rows}
    crop_saved, unresolved_crop_saved, non_tail_unknown_crop_saved = _export_name_crops(
        ships=ships,
        rows=matched_rows,
        output_dir=name_crop_dir,
        unresolved_indexes=unresolved_indexes,
        non_tail_unknown_indexes=non_tail_unknown_indexes,
    )

    logger.info(
        f'DockScan postprocess done: symbol={symbol_rows}, fixed={fixed_rows}, '
        f'rescan_fixed={rescan_fixed_rows}, clean_fixed={clean_fixed_rows}, '
        f'unresolved={len(unresolved_rows)}, '
        f'name_crops={crop_saved}, unresolved_crops={unresolved_crop_saved}, '
        f'non_tail_unknown_crops={non_tail_unknown_crop_saved}'
    )

    return {
        'raw_csv': str(raw_csv),
        'cleaned_csv': str(cleaned_csv),
        'matched_csv': str(matched_csv),
        'unresolved_csv': str(unresolved_csv),
        'report_csv': str(report_csv),
        'name_crop_dir': str(name_crop_dir),
    }
