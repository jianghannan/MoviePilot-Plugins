#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
从远端目录构造下载链接并下载字体文件。
默认读取 font_mapping_slim.json 或用户指定的 JSON，
并将条目与远端前缀拼接后进行下载。


模块用法示例：
    from download_fonts import FontDownloader
    downloader = FontDownloader()
    # 下载单个字体
    success, file_path = downloader.download_font(
        font_name="華康少女文字W3",
        output_dir="downloads",
    )
    if success:
        print(f"下载成功: {file_path}")
    else:
        print("下载失败")

"""


import json
from pathlib import Path

from app.log import logger
from app.utils.url import UrlUtils
from app.utils.http import RequestUtils
from app.plugins.subtitlesfontcollection.font_utils import FontUtils


__all__ = ["FontDownloader"]


class FontDownloader:
    """字体下载助手类，提供精简包优先、完整包回退的下载功能。"""

    # 硬编码配置
    BASE_URL = "https://pan.acgrip.com/"



    SLIM_PREFIX = "超级字体整合包 XZ/精简包"
    FULL_PREFIX = "超级字体整合包 XZ/完整包"
    CAUTION_PREFIX = "超级字体整合包 XZ/完整包/慎用"

    SLIM_MAP = "font_mapping_slim.json"
    FULL_MAP = "font_mapping_full.json"
    CAUTION_MAP = "font_mapping_caution.json"

    LPSUB_NEW_PREFIX = "LPSub Fonts/2023-12-24"
    LPSUB_OLD_PREFIX = "LPSub Fonts/LPSub Fonts 20230623"
    SARASA_PREFIX = "LPSub Fonts/Sarasa-Gothic"
    DREAMHAN_PREFIX = "LPSub Fonts/Dream-Han"

    LPSUB_NEW_MAP = "font_mapping_lpsub_new.json"
    LPSUB_OLD_MAP = "font_mapping_lpsub_old.json"
    SARASA_MAP = "font_mapping_sarasa.json"
    DREAMHAN_MAP = "font_mapping_dreamhan.json"

    CHUNK_SIZE = 1024 * 512  # 512KB 分片下载

    def __init__(self, use_caution: bool = False):
        """
        初始化下载器，加载字体映射文件。"""
        script_dir = Path(__file__).parent
        self.slim_map = self._load_mapping(script_dir / self.SLIM_MAP)
        self.full_map = self._load_mapping(script_dir / self.FULL_MAP)
        self.caution_map = (
            self._load_mapping(script_dir / self.CAUTION_MAP) if use_caution else {}
        )
        self.lpsub_new_map = self._load_mapping(script_dir / self.LPSUB_NEW_MAP)
        self.lpsub_old_map = self._load_mapping(script_dir / self.LPSUB_OLD_MAP)
        self.sarasa_map = self._load_mapping(script_dir / self.SARASA_MAP)
        self.dreamhan_map = self._load_mapping(script_dir / self.DREAMHAN_MAP)

        self.use_caution = use_caution
        self.http = RequestUtils(timeout=60)

    @staticmethod
    def _load_mapping(path: Path) -> dict:
        """
        读取字体映射 JSON，返回 {font_name: [relative_paths]}。
        Args:
            path: 映射文件路径。
        Returns:
            键为字体名，值为该字体关联的相对路径列表的字典。
        """
        if not path.exists():
            logger.error(f"找不到输入文件: {path}")
            raise FileNotFoundError(f"找不到输入文件: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.error("输入 JSON 格式不正确，应为 {font_name: [paths]} 结构")
            raise ValueError("输入 JSON 格式不正确，应为 {font_name: [paths]} 结构")
        return data

    @staticmethod
    def _build_url(base_url: str, remote_prefix: str, relative_path: str) -> str:
        """
        构造下载 URL，兼容 query 形式和直链前缀。
        Args:
            base_url: 下载基础地址，直链前缀形态。
            remote_prefix: 远端根目录前缀（不含起始斜杠）。
            relative_path: 映射中的相对路径。
        Returns:
            已按 URL 规则编码后的完整下载链接。
        """
        full_remote = f"{remote_prefix.rstrip('/')}/{relative_path.lstrip('/')}"
        encoded = UrlUtils.quote(full_remote)
        if base_url.endswith("?file="):
            return f"{base_url}{encoded}"
        base = base_url.rstrip("/")
        return f"{base}/{encoded}"

    def _download_file(self, url: str, dest_path: str, retries: int = 3) -> bool:
        """
        下载单个文件，带简单重试；成功返回 True。
        Args:
            url: 目标下载链接。
            dest_path: 本地保存路径（字符串）。
            retries: 失败重试次数。
        Returns:
            bool: 成功为 True，失败为 False。
        """
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, retries + 1):
            try:
                # 使用 RequestUtils 下载文件
                with self.http.response_manager("get", url, stream=True) as response:
                    if not response or response.status_code != 200:
                        logger.warning(
                            f"[HTTP {response.status_code if response else 'N/A'}] {url} (尝试 {attempt}/{retries})"
                        )
                        continue
                    # 分块写入文件
                    with dest.open("wb") as f:
                        for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                            if chunk:
                                f.write(chunk)
                    logger.info(f"[下载成功] {dest}")
                    return True
            except Exception as e:
                logger.warning(f"[下载失败] {url}: {str(e)} (尝试 {attempt}/{retries})")
        return False

    def _download_paths_for_font(
        self, font_name: str, paths: list, remote_prefix: str, output_dir: str
    ) -> tuple:
        """
        下载某字体关联的所有文件路径。
        Returns:
            (bool, str|None): 成功返回 (True, 文件路径)，失败返回 (False, None)。
        """
        all_ok = True
        downloaded_path = None
        for rel_path in paths:
            dest = Path(output_dir) / Path(rel_path).name
            dest_str = str(dest)

            # 检查文件是否已存在，如果存在则跳过下载
            if dest.exists():
                logger.info(f"[已存在] {dest.name}，跳过下载")
                downloaded_path = dest_str
                continue

            url = self._build_url(self.BASE_URL, remote_prefix, rel_path)
            ok = self._download_file(url, dest_str)
            if ok:
                # 记录最后一个成功下载的文件路径
                downloaded_path = dest_str
            else:
                all_ok = False
        if all_ok and downloaded_path:
            logger.info(f"[字体完成] {font_name}")
            return True, downloaded_path
        else:
            logger.warning(f"[字体有失败] {font_name}")
            return False, None

    def _find_font_in_map(self, lookup_name: str, font_map: dict) -> str | None:
        """
        在映射表中查找字体，支持精确匹配和模糊匹配（去空格）
        Returns:
            匹配到的字体名，未找到返回 None
        """
        # 1. 精确匹配
        if lookup_name in font_map:
            return lookup_name

        # 2. 模糊匹配（去空格、忽略大小写）
        lookup_normalized = FontUtils.normalize_font_name(lookup_name)
        for key in font_map.keys():
            if FontUtils.normalize_font_name(key) == lookup_normalized:
                return key

        return None

    def download_font(self, font_name: str, output_dir: str) -> tuple:
        """
        下载单个字体，按优先级依次查找各字体包。
        Args:
            font_name: 需要下载的字体名称。
            output_dir: 本地保存根目录（字符串路径）。
        Returns:
            (bool, str|None): 下载成功返回 (True, 文件路径)，失败返回 (False, None)。
        """
        # ASS字幕中 @ 前缀表示竖排字体，查找时需要去掉
        lookup_name = FontUtils.strip_at_prefix(font_name)

        # 字体包配置：(映射表, 前缀, 日志标签, 是否可用)
        font_sources = [
            (self.slim_map, self.SLIM_PREFIX, "精简包", True),
            (self.full_map, self.FULL_PREFIX, "完整包", True),
            (self.lpsub_new_map, self.LPSUB_NEW_PREFIX, "LPSub新包", True),
            (self.lpsub_old_map, self.LPSUB_OLD_PREFIX, "LPSub旧包", True),
            (self.sarasa_map, self.SARASA_PREFIX, "Sarasa", True),
            (self.dreamhan_map, self.DREAMHAN_PREFIX, "DreamHan", True),
            (self.caution_map, self.CAUTION_PREFIX, "慎用包", self.use_caution),
        ]

        # 按优先级遍历各字体包
        for font_map, prefix, label, is_enabled in font_sources:
            if not is_enabled:
                logger.warning(f"在[{label}]中找到字体 {font_name} 但[{label}未启用]")

                continue
            matched_name = self._find_font_in_map(lookup_name, font_map)
            if matched_name:
                paths = font_map[matched_name]
                match_info = f" -> {matched_name}" if matched_name != lookup_name else ""
                logger.info(f"[{label}] {font_name}{match_info}")
                return self._download_paths_for_font(font_name, paths, prefix, output_dir)

        logger.warning(f"[未找到] {font_name}")
        return False, None
