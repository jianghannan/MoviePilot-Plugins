import re
from typing import List
from app.log import logger
from app.plugins.subtitlesfontcollection.font_utils import FontUtils


class SubtitleFontParser:
    """字幕字体解析器"""

    def __init__(self):
        pass

    @staticmethod
    def normalize_font_name(name: str) -> str:
        """
        标准化字体名称用于匹配（去空格、转小写）
        :param name: 字体名称
        :return: 标准化后的字体名称
        """
        return FontUtils.normalize_font_name(name)

    def __parse_fonts_from_content(self, content: str) -> List[str]:
        """
        从字幕文件内容中解析字体列表（纯算法，可独立测试）
        :param content: 字幕文件内容
        :return: 字体名称列表
        """
        fonts = []

        # 解码函数
        def decode(name: str) -> str:
            return FontUtils.decode_font_name(name)

        # 1. Style行格式: Style: Name,Fontname,Fontsize,...
        #    格式: Style: stylename,fontname,fontsize,primarycolor,...
        style_pattern = re.compile(r'^Style:\s*[^,]*,\s*([^,]+)', re.MULTILINE)
        style_matches = style_pattern.findall(content)
        for font in style_matches:
            font = decode(font.strip())
            # 过滤掉明显不是字体名的内容
            if font and font not in fonts and not font.isdigit():
                fonts.append(font)

        # 2. 解析内联字体标签 {\fnFontName}
        inline_pattern = re.compile(r'\\fn([^\\}]+)')
        inline_matches = inline_pattern.findall(content)
        for font in inline_matches:
            font = decode(font.strip())
            if font and font not in fonts and not font.isdigit():
                fonts.append(font)

        # 3. 解析 [Fonts] 段落中嵌入的字体声明
        #    格式: fontname: xxx
        fontname_pattern = re.compile(r'^fontname:\s*(.+)$', re.MULTILINE | re.IGNORECASE)
        fontname_matches = fontname_pattern.findall(content)
        for font in fontname_matches:
            font = decode(font.strip())
            if font and font not in fonts:
                fonts.append(font)

        return fonts

    def __check_font_used(self, content: str, font_name: str) -> bool:
        """
        检查字体是否在字幕内容中被实际使用
        :param content: 字幕文件内容
        :param font_name: 要检查的字体名称
        :return: True 表示被使用，False 表示未被使用
        """
        # 1. 检查是否在 Style 定义中
        style_pattern = re.compile(r'^Style:\s*([^,]*),\s*([^,]+)', re.MULTILINE)
        style_matches = style_pattern.findall(content)

        style_font_map = {}  # {样式名: 字体名}
        for style_name, font in style_matches:
            decoded_font = FontUtils.decode_font_name(font.strip())
            style_font_map[style_name.strip()] = decoded_font

        # 2. 检查 Style 中的字体是否被 Dialogue 引用
        used_in_style = False
        for style_name, style_font in style_font_map.items():
            if style_font == font_name:
                # 检查这个样式是否被对话使用
                dialogue_pattern = re.compile(
                    r'^Dialogue:[^,]*,[^,]*,[^,]*,' + re.escape(style_name) + r',',
                    re.MULTILINE
                )
                if dialogue_pattern.search(content):
                    used_in_style = True
                    break

        if used_in_style:
            return True

        # 3. 检查是否在内联字体标签中使用
        inline_pattern = re.compile(r'\\fn([^\\}]+)')
        inline_matches = inline_pattern.findall(content)
        for inline_font in inline_matches:
            decoded = FontUtils.decode_font_name(inline_font.strip())
            if decoded == font_name:
                return True

        return False

    def filter_used_fonts(self, content: str) -> List[str]:
        """
        解析并过滤出实际使用的字体列表
        :param content: 字幕文件内容
        :return: 实际使用的字体列表
        """
        # 先获取所有字体
        all_fonts = self.__parse_fonts_from_content(content)

        # 过滤出实际使用的字体
        used_fonts = []
        unused_fonts = []

        for font in all_fonts:
            if self.__check_font_used(content, font):
                used_fonts.append(font)
            else:
                unused_fonts.append(font)

        if unused_fonts:
            logger.info(f"发现 {len(unused_fonts)} 个未使用的字体: {unused_fonts}")

        return used_fonts
