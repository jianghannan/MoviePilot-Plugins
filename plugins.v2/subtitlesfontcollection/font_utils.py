#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
字幕字体补全插件 - 工具类
提供通用的字体处理工具函数和常量
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

from app.log import logger


class FontUtils:
    """字体处理工具类，提供通用的字体处理功能"""

    # 常见字体文件扩展名
    FONT_EXTENSIONS = {".ttf", ".ttc", ".otf", ".woff", ".woff2"}

    # 字体扩展名列表（用于遍历）
    FONT_EXTENSIONS_LIST = [".ttf", ".ttc", ".otf", ".woff", ".woff2"]

    @staticmethod
    def normalize_font_name(name: str) -> str:
        """
        标准化字体名称用于匹配（去空格、转小写）
        :param name: 字体名称
        :return: 标准化后的字体名称
        """
        return name.replace(" ", "").lower()

    @staticmethod
    def strip_at_prefix(font_name: str) -> str:
        """
        去除字体名称的 @ 前缀（ASS字幕中 @ 前缀表示竖排字体）
        :param font_name: 字体名称
        :return: 去除 @ 前缀后的字体名称
        """
        return font_name.lstrip("@") if font_name.startswith("@") else font_name

    @staticmethod
    def decode_font_name(font_name: str) -> str:
        """
        解码字体名称
        ASS/SSA 字幕中的字体名称可能使用 #XX 格式编码非 ASCII 字符
        例如: #E6#96#B9#E6#AD#A3#E7#BB#BC#E8#89#BA_GBK -> 方正综艺_GBK
        :param font_name: 原始字体名称
        :return: 解码后的字体名称
        """
        import re

        if not font_name:
            return font_name

        # 检查是否包含 #XX 格式的编码
        if '#' not in font_name:
            return font_name

        try:
            # 匹配 #XX 格式（XX为两位十六进制）
            hex_pattern = re.compile(r'#([0-9A-Fa-f]{2})')

            # 检查是否有足够的 #XX 模式
            matches = hex_pattern.findall(font_name)
            if not matches:
                return font_name

            # 将 #XX 转换为字节序列
            byte_list = []
            result_parts = []

            i = 0
            while i < len(font_name):
                if font_name[i] == '#' and i + 2 < len(font_name):
                    hex_chars = font_name[i+1:i+3]
                    if all(c in '0123456789ABCDEFabcdef' for c in hex_chars):
                        byte_list.append(int(hex_chars, 16))
                        i += 3
                        continue

                # 如果有累积的字节，先解码
                if byte_list:
                    try:
                        decoded = bytes(byte_list).decode('utf-8')
                        result_parts.append(decoded)
                    except UnicodeDecodeError:
                        try:
                            decoded = bytes(byte_list).decode('gbk')
                            result_parts.append(decoded)
                        except UnicodeDecodeError:
                            # 解码失败，保留原始格式
                            for b in byte_list:
                                result_parts.append(f'#{b:02X}')
                    byte_list = []

                result_parts.append(font_name[i])
                i += 1

            # 处理末尾的字节
            if byte_list:
                try:
                    decoded = bytes(byte_list).decode('utf-8')
                    result_parts.append(decoded)
                except UnicodeDecodeError:
                    try:
                        decoded = bytes(byte_list).decode('gbk')
                        result_parts.append(decoded)
                    except UnicodeDecodeError:
                        for b in byte_list:
                            result_parts.append(f'#{b:02X}')

            decoded_name = ''.join(result_parts)

            if decoded_name != font_name:
                logger.debug(f"字体名称解码：{font_name} -> {decoded_name}")

            return decoded_name

        except Exception as e:
            logger.warning(f"字体名称解码失败 {font_name}: {e}")
            return font_name

    @staticmethod
    def get_font_files_in_directory(font_path: str) -> Dict[str, str]:
        """
        获取字体目录中所有的字体文件
        :param font_path: 字体目录路径
        :return: {文件名: 完整路径} 字典
        """
        if not font_path:
            return {}

        path = Path(font_path)
        if not path.exists():
            return {}

        font_files = {}

        try:
            # 递归扫描字体目录
            for file in path.rglob("*"):
                if file.is_file() and file.suffix.lower() in FontUtils.FONT_EXTENSIONS:
                    font_files[file.name] = str(file)
        except Exception as e:
            logger.warning(f"扫描字体目录失败：{e}")

        return font_files

    @staticmethod
    def check_font_exists_in_directory(
        font_id: str,
        font_path: str,
        existing_files: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        检查字体是否存在于字体目录中
        :param font_id: 字体ID
        :param font_path: 字体目录路径
        :param existing_files: 已扫描的字体文件字典（可选，避免重复扫描）
        :return: (是否存在, 存在时的文件路径)
        """
        if not font_path:
            return False, None

        path = Path(font_path)
        if not path.exists():
            return False, None

        # ASS字幕中 @ 前缀表示竖排字体，查找时需要去掉
        lookup_name = FontUtils.strip_at_prefix(font_id)

        # 如果没有提供已扫描的文件列表，则进行扫描
        if existing_files is None:
            existing_files = FontUtils.get_font_files_in_directory(font_path)

        # 标准化后的查找名称（用于模糊匹配）
        lookup_normalized = FontUtils.normalize_font_name(lookup_name)

        # 检查字体文件是否存在（通过文件名匹配）
        for ext in FontUtils.FONT_EXTENSIONS_LIST:
            # 尝试多种命名方式（精确匹配）
            possible_names = [
                f"{lookup_name}{ext}",
                f"{lookup_name.lower()}{ext}",
                f"{lookup_name.replace(' ', '')}{ext}",
                f"{lookup_name.replace(' ', '_')}{ext}",
            ]
            for name in possible_names:
                name_lower = name.lower()
                # 在已扫描的文件列表中查找（不区分大小写）
                for existing_file, existing_path in existing_files.items():
                    if existing_file.lower() == name_lower:
                        return True, existing_path

            # 模糊匹配：去空格、忽略大小写
            for existing_file, existing_path in existing_files.items():
                # 去掉扩展名后进行标准化比较
                file_stem = Path(existing_file).stem
                if FontUtils.normalize_font_name(file_stem) == lookup_normalized:
                    return True, existing_path

        return False, None
