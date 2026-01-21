import pytz
from pathlib import Path
from app.log import logger
from threading import Event
from app.plugins import _PluginBase
from app.core.config import settings
from app.schemas import StorageSchema
from datetime import datetime, timedelta
from app.core.metainfo import MetaInfoPath
from app.schemas.types import NotificationType
from app.modules.filemanager import FileManagerModule
from apscheduler.triggers.cron import CronTrigger
from typing import Any, List, Dict, Tuple, Optional
from apscheduler.schedulers.background import BackgroundScheduler

from app.plugins.subtitlesfontcollection.font_utils import FontUtils
from app.plugins.subtitlesfontcollection.font_downloader import FontDownloader
from app.plugins.subtitlesfontcollection.subtitle_font_parser import SubtitleFontParser


class SubtitlesFontCollection(_PluginBase):
    """
    字幕字体补全插件
    自动搜索并补全字幕文件中需要的字体
    """

    # 插件名称
    plugin_name = "字幕字体补全"
    # 插件描述
    plugin_desc = "自动搜索并补全字幕文件中需要的字体"
    # 插件图标
    plugin_icon = "SubtitlesFontCollection.png"
    # 插件版本
    plugin_version = "1.0.0"
    # 插件作者
    plugin_author = "jianghannan"
    # 作者主页
    author_url = "https://github.com/jianghannan"
    # 插件配置项ID前缀
    plugin_config_prefix = "subtitlesfontcollection_"
    # 加载顺序
    plugin_order = 10
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _font_path = ""
    _notify = True  # 是否发送通知
    _active_tab = "all"  # 当前激活的Tab: all/downloaded/missing
    _media_path = ""
    _exclude_paths = ""
    _auto_download = True  # 是否自动下载缺失字体
    _font_sources = ""  # 字体下载源URL列表
    _use_caution_fonts = False  # 是否启用慎用字体包
    _scheduler = None

    # 退出事件
    _event = Event()


    def __cron2text(self, cron: str) -> str:
        """
        将cron表达式转换为中文描述
        :param cron: cron表达式（5位：分 时 日 月 周）
        :return: 中文描述
        """
        if not cron:
            return "未设置"

        try:
            parts = cron.strip().split()
            if len(parts) != 5:
                return f"无效的cron表达式: {cron}"

            minute, hour, day, month, weekday = parts

            # 周几映射
            weekday_map = {
                "0": "周日",
                "1": "周一",
                "2": "周二",
                "3": "周三",
                "4": "周四",
                "5": "周五",
                "6": "周六",
                "7": "周日",
                "SUN": "周日",
                "MON": "周一",
                "TUE": "周二",
                "WED": "周三",
                "THU": "周四",
                "FRI": "周五",
                "SAT": "周六",
            }

            result_parts = []

            # 解析月份
            if month != "*":
                if "," in month:
                    months = [f"{m}月" for m in month.split(",")]
                    result_parts.append(f"每年{'/'.join(months)}")
                elif "-" in month:
                    start, end = month.split("-")
                    result_parts.append(f"每年{start}月至{end}月")
                elif "/" in month:
                    _, interval = month.split("/")
                    result_parts.append(f"每隔{interval}个月")
                else:
                    result_parts.append(f"每年{month}月")

            # 解析日期
            if day != "*" and weekday == "*":
                if "," in day:
                    days = [f"{d}日" for d in day.split(",")]
                    result_parts.append(f"每月{'/'.join(days)}")
                elif "-" in day:
                    start, end = day.split("-")
                    result_parts.append(f"每月{start}日至{end}日")
                elif "/" in day:
                    _, interval = day.split("/")
                    result_parts.append(f"每隔{interval}天")
                else:
                    result_parts.append(f"每月{day}日")
            elif day == "*" and weekday == "*":
                result_parts.append("每天")

            # 解析周几
            if weekday != "*":
                if "," in weekday:
                    weeks = [weekday_map.get(w.upper(), w) for w in weekday.split(",")]
                    result_parts.append(f"每{'/'.join(weeks)}")
                elif "-" in weekday:
                    start, end = weekday.split("-")
                    start_text = weekday_map.get(start.upper(), start)
                    end_text = weekday_map.get(end.upper(), end)
                    result_parts.append(f"每{start_text}至{end_text}")
                elif "/" in weekday:
                    _, interval = weekday.split("/")
                    result_parts.append(f"每隔{interval}天")
                else:
                    week_text = weekday_map.get(weekday.upper(), f"周{weekday}")
                    result_parts.append(f"每{week_text}")

            # 解析时间
            time_text = ""
            if hour == "*" and minute == "*":
                time_text = "每分钟"
            elif hour == "*":
                if "/" in minute:
                    _, interval = minute.split("/")
                    time_text = f"每隔{interval}分钟"
                else:
                    time_text = f"每小时的第{minute}分钟"
            elif minute == "*":
                if "/" in hour:
                    _, interval = hour.split("/")
                    time_text = f"每隔{interval}小时"
                else:
                    time_text = f"{hour}点的每分钟"
            else:
                # 处理小时
                if "/" in hour:
                    _, interval = hour.split("/")
                    hour_text = f"每隔{interval}小时"
                elif "," in hour:
                    hour_text = f"{'/'.join(hour.split(','))}点"
                elif "-" in hour:
                    start, end = hour.split("-")
                    hour_text = f"{start}点至{end}点"
                else:
                    hour_text = f"{hour}点"

                # 处理分钟
                if "/" in minute:
                    _, interval = minute.split("/")
                    minute_text = f"每隔{interval}分钟"
                elif "," in minute:
                    minute_text = f"{'/'.join(minute.split(','))}分"
                elif "-" in minute:
                    start, end = minute.split("-")
                    minute_text = f"{start}分至{end}分"
                else:
                    minute_text = f"{minute.zfill(2)}分"

                if "/" in hour:
                    time_text = f"{hour_text}的{minute_text}"
                else:
                    time_text = f"{hour_text}{minute_text}"

            result_parts.append(time_text)

            return "".join(result_parts) + "执行"

        except Exception as e:
            logger.warning(f"解析cron表达式失败: {cron}, 错误: {e}")
            return f"cron: {cron}"

    def init_plugin(self, config: dict = None):
        """
        生效配置信息
        """
        if config:
            self._cron = config.get("cron")
            self._run_once = config.get("onlyonce")
            self._enabled = config.get("enabled", False)
            self._font_path = config.get("font_path", "")
            self._notify = config.get("notify", True)
            self._media_path = config.get("media_path", "")
            self._exclude_paths = config.get("exclude_paths", "")
            self._auto_download = config.get("auto_download", True)
            self._font_sources = config.get("font_sources", "")
            self._use_caution_fonts = config.get("use_caution_fonts", False)

            # 处理清除数据
            if config.get("clear_data"):
                self.__clear_all_data()
                # 关闭清除数据开关
                config["clear_data"] = False
                self.update_config(config)

        logger.info(f"字幕字体补全插件初始化完成，启用状态：{self._enabled}")

        # 启动定时任务
        if self._enabled:
            logger.debug("字幕字体补全插件配置：")
            logger.debug(f"立即运行一次：{self._run_once}")
            logger.debug(
                f"执行周期：{self.__cron2text(self._cron) if self._cron else '默认每7天执行一次'}"
            )
            logger.debug(f"字体存储路径：{self._font_path}")
            logger.debug(f"媒体文件路径：{self._media_path}")
            logger.debug(f"排除路径：{self._exclude_paths}")
            if self._run_once:
                self.__run_once()
                # 关闭一次性开关
                self._run_once = False
                self.update_config(
                    {
                        "onlyonce": False,
                        "enabled": self._enabled,
                        "cron": self._cron,
                        "font_path": self._font_path,
                        "media_path": self._media_path,
                        "exclude_paths": self._exclude_paths,
                        "notify": self._notify,
                        "auto_download": self._auto_download,
                        "font_sources": self._font_sources,
                        "use_caution_fonts": self._use_caution_fonts,
                    }
                )

    def __run_once(self):
        logger.info(f"字幕字体补全，立即运行一次...")
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self._scheduler.add_job(
            func=self.__update_fonts_status_from_library,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            name="字幕字体状态更新",
        )
        self._scheduler.add_job(
            func=self.__subtitlesfontcollection,
            trigger="date",
            run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=6),
            name="字幕字体补全",
        )
        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def __clear_all_data(self):
        """
        清除所有插件数据
        """
        # 清除媒体-字幕关系数据
        self.save_data("media_subtitles", {})
        # 清除字体全局数据
        self.save_data("fonts", {})
        # 清除统计数据
        self.save_data(
            "stats",
            {
                "total_media": 0,
                "total_subtitles": 0,
                "total_fonts": 0,
                "downloaded_fonts": 0,
                "missing_fonts": 0,
            },
        )
        logger.info("已清除所有插件数据")

    def __update_all_fonts_status(self):
        """
        更新所有统计数据
        """
        fonts = self.get_data("fonts") or {}
        media_subtitles = self.get_data("media_subtitles") or {}

        # 统计字体状态
        downloaded_count = sum(
            1 for f in fonts.values() if f.get("status") == "downloaded"
        )
        missing_count = sum(1 for f in fonts.values() if f.get("status") == "missing")

        # 统计媒体和字幕数量
        total_media = len(media_subtitles)
        total_subtitles = 0
        for media in media_subtitles.values():
            if media.get("media_type") == "movie":
                total_subtitles += len(media.get("subtitles", {}))
            elif media.get("media_type") == "tv":
                for season in media.get("seasons", {}).values():
                    for episode in season.get("episodes", {}).values():
                        total_subtitles += len(episode.get("subtitles", {}))

        # 保存统计数据
        stats = {
            "total_media": total_media,
            "total_subtitles": total_subtitles,
            "total_fonts": len(fonts),
            "downloaded_fonts": downloaded_count,
            "missing_fonts": missing_count,
        }
        self.save_data("stats", stats)
        logger.debug(f"统计数据已更新: {stats}")
        return stats

    def __get_font_status_text(self, status: str) -> str:
        """
        获取字体状态的中文文本
        """
        status_map = {
            "downloaded": "已下载",
            "missing": "缺失",
        }
        return status_map.get(status, status)

    def __get_font_status_color(self, status: str) -> str:
        """
        获取字体状态的颜色
        """
        color_map = {
            "downloaded": "success",
            "missing": "warning",
        }
        return color_map.get(status, "default")

    def __update_font_record(
        self,
        font_id: str,
        status: str = None,
        file_path: str = None,
    ):
        """
        更新字体记录状态
        :param font_id: 字体ID
        :param status: 字体状态（downloaded/missing）
        :param file_path: 下载后的文件路径
        """
        from datetime import datetime

        fonts = self.get_data("fonts") or {}

        if font_id in fonts:
            if status is not None:
                fonts[font_id]["status"] = status
            if file_path is not None:
                fonts[font_id]["file_path"] = file_path
            fonts[font_id]["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.save_data("fonts", fonts)

    def get_state(self) -> bool:
        """
        获取插件运行状态
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册插件远程命令
        """
        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """
        获取插件渲染模式
        :return: 1、渲染模式，支持：vue/vuetify，默认vuetify；2、vue模式下编译后文件的相对路径，默认为`dist/asserts`，vuetify模式下为None
        """
        return "vuetify", None

    def get_api(self) -> List[Dict[str, Any]]:
        """
        注册插件API
        """
        return [
            {
                "path": "/switch_tab",
                "endpoint": self.switch_tab,
                "methods": ["POST"],
                "summary": "切换Tab",
                "description": "切换当前激活的Tab页签",
                "auth": "bear",
            }
        ]

    def switch_tab(self, tab: str) -> dict:
        """
        切换Tab API
        """
        self._active_tab = tab
        # 保存到配置
        config = self.get_config() or {}
        config["active_tab"] = tab
        self.update_config(config)
        logger.debug(f"切换Tab到: {tab}")
        return {"success": True, "active_tab": tab}

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "立即运行一次",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "clear_data",
                                            "label": "清除数据",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VCronField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "5位cron表达式，留空自动",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "font_path",
                                            "label": "字体文件存储位置",
                                            "placeholder": "/fonts",
                                            "hint": "字体文件存储的完整路径，例如：/fonts",
                                            "persistent-hint": True,
                                            "clearable": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "media_path",
                                            "label": "媒体文件路径",
                                            "rows": 3,
                                            "placeholder": "每一行一个目录",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "exclude_paths",
                                            "label": "排除路径",
                                            "rows": 2,
                                            "placeholder": "每一行一个目录",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "use_caution_fonts",
                                            "label": "启用慎用字体包",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "warning",
                                            "variant": "tonal",
                                            "title": "⚠️ 慎用字体包警告",
                                            "text": "慎用字体包中的字体都是第三方魔改的字体，且存在着一些问题，我们也建议尽量不要使用这类字体。例如：\n"
                                            "• \"方正晶黑\"是第三方伪造的字体，由几个字体拼凑而成，而且有些字的字形是错误的，并非方正出品的字体；\n"
                                            "• \"熊兔流星体\"的 Family 属性为\"Heiti SC\"，安装后，网页中原本应以\"黑体\"显示的字可能会以\"熊兔流星体\"显示。\n"
                                            "请谨慎开启此选项！"
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "配置说明："
                                            "1. 字体文件存储位置：用于存放下载的字体文件。"
                                            "2. 媒体文件路径后拼接#【存储类型】，指定该媒所在的存储类型。默认本地存储，例如：/media/movies#Local。支持的存储类型有Local（本地）、Alipan（阿里云盘）、115（115网盘）、RClone、OpenList",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "font_path": "",
            "media_path": "",
            "notify": True,
            "exclude_paths": "",
            "use_caution_fonts": False,
        }


    def get_page(self) -> List[dict]:
        """
        构建插件数据页面
        支持两种视图：媒体视图（按媒体-字幕层级展示）和字体视图（按字体状态展示）
        """
        # 从配置中读取当前Tab状态
        config = self.get_config()
        if config:
            self._active_tab = config.get("active_tab", "media")

        # 获取数据
        fonts = self.get_data("fonts") or {}
        media_subtitles = self.get_data("media_subtitles") or {}
        stats = self.get_data("stats") or {}

        if not fonts and not media_subtitles:
            return [
                {
                    "component": "div",
                    "text": "暂无数据，请先运行一次任务扫描字幕文件",
                    "props": {"class": "text-center pa-4"},
                }
            ]

        # 构建Tab项
        def build_tab_item(tab_id: str, label: str, count: int, icon: str):
            is_active = self._active_tab == tab_id
            return {
                "component": "VTab",
                "props": {
                    "value": tab_id,
                    "class": "font-weight-bold" if is_active else "",
                },
                "text": f"{icon} {label} ({count})",
                "events": {
                    "click": {
                        "api": f"plugin/SubtitlesFontCollection/switch_tab?tab={tab_id}",
                        "method": "POST",
                    }
                },
            }

        # 统计数量
        downloaded_count = stats.get("downloaded_fonts", 0)
        missing_count = stats.get("missing_fonts", 0)
        total_media = stats.get("total_media", len(media_subtitles))

        # 获取当前激活Tab的索引
        tab_ids = ["media", "fonts", "downloaded", "missing"]
        current_index = (
            tab_ids.index(self._active_tab) if self._active_tab in tab_ids else 0
        )

        # 根据当前Tab构建内容
        if self._active_tab == "media":
            content = self.__build_media_view(media_subtitles, fonts)
        elif self._active_tab == "fonts":
            content = self.__build_font_view(fonts, status_filter=None)
        elif self._active_tab == "downloaded":
            content = self.__build_font_view(fonts, status_filter="downloaded")
        elif self._active_tab == "missing":
            content = self.__build_font_view(fonts, status_filter="missing")
        else:
            content = self.__build_media_view(media_subtitles, fonts)

        # 拼装页面
        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VCard",
                                "content": [
                                    {
                                        "component": "VTabs",
                                        "props": {
                                            "model-value": current_index,
                                            "color": "primary",
                                            "grow": True,
                                            "show-arrows": True,
                                        },
                                        "content": [
                                            build_tab_item(
                                                "media", "媒体视图", total_media, "🎬"
                                            ),
                                            build_tab_item(
                                                "fonts", "全部字体", len(fonts), "📊"
                                            ),
                                            build_tab_item(
                                                "downloaded",
                                                "已下载",
                                                downloaded_count,
                                                "✅",
                                            ),
                                            build_tab_item(
                                                "missing", "缺失", missing_count, "❌"
                                            ),
                                        ],
                                    },
                                    {"component": "VDivider"},
                                    {
                                        "component": "VCardText",
                                        "props": {
                                            "style": "max-height: 35rem; overflow-y: auto;"
                                        },
                                        "content": content,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    def __build_media_view(self, media_subtitles: dict, fonts: dict) -> List[dict]:
        """
        构建媒体视图：按媒体-字幕-字体层级展示
        """
        if not media_subtitles:
            return [
                {
                    "component": "div",
                    "text": "暂无媒体数据",
                    "props": {"class": "text-center pa-4"},
                }
            ]

        content = []
        for media_path, media_data in media_subtitles.items():
            media_name = media_data.get("media_name", "未知媒体")
            media_type = media_data.get("media_type", "movie")
            year = media_data.get("year", "")

            # 媒体类型图标
            type_icon = "🎬" if media_type == "movie" else "📺"
            media_title = f"{type_icon} {media_name}" + (f" ({year})" if year else "")

            # 构建媒体卡片
            media_card_content = []

            if media_type == "movie":
                # 电影：直接显示字幕列表
                subtitles = media_data.get("subtitles", {})
                subtitle_items = self.__build_subtitle_items(subtitles, fonts)
                media_card_content.extend(subtitle_items)
            else:
                # 电视剧：显示季-集-字幕层级
                seasons = media_data.get("seasons", {})
                for season_key, season_data in sorted(seasons.items()):
                    season_name = season_data.get("season_name", season_key)
                    episodes = season_data.get("episodes", {})

                    # 季标题
                    season_header = {
                        "component": "div",
                        "props": {
                            "class": "text-subtitle-1 font-weight-bold mt-2 mb-1"
                        },
                        "text": f"📁 {season_name}",
                    }
                    media_card_content.append(season_header)

                    # 集列表
                    for ep_key, ep_data in sorted(episodes.items()):
                        ep_name = ep_data.get("episode_name", ep_key)
                        subtitles = ep_data.get("subtitles", {})

                        # 集标题
                        ep_header = {
                            "component": "div",
                            "props": {"class": "text-body-2 ml-4 mt-1"},
                            "text": f"🎞️ {ep_key}: {ep_name}",
                        }
                        media_card_content.append(ep_header)

                        # 字幕列表
                        subtitle_items = self.__build_subtitle_items(
                            subtitles, fonts, indent=True
                        )
                        media_card_content.extend(subtitle_items)

            # 媒体展开面板
            media_panel = {
                "component": "VExpansionPanels",
                "props": {"class": "mb-2"},
                "content": [
                    {
                        "component": "VExpansionPanel",
                        "content": [
                            {
                                "component": "VExpansionPanelTitle",
                                "props": {"class": "text-subtitle-1 font-weight-bold"},
                                "text": media_title,
                            },
                            {
                                "component": "VExpansionPanelText",
                                "content": (
                                    media_card_content
                                    if media_card_content
                                    else [
                                        {
                                            "component": "div",
                                            "text": "暂无字幕",
                                            "props": {"class": "text-center"},
                                        }
                                    ]
                                ),
                            },
                        ],
                    }
                ],
            }
            content.append(media_panel)

        return content

    def __build_subtitle_items(
        self, subtitles: dict, fonts: dict, indent: bool = False
    ) -> List[dict]:
        """
        构建字幕条目列表
        """
        items = []
        indent_class = "ml-8" if indent else "ml-4"

        for sub_name, sub_data in subtitles.items():
            font_ids = sub_data.get("fonts", [])

            # 统计该字幕的字体状态
            downloaded = 0
            missing = 0
            font_chips = []

            for font_id in font_ids:
                font_info = fonts.get(font_id, {})
                status = font_info.get("status", "missing")
                font_name = font_info.get("font_name", font_id)

                if status == "downloaded":
                    downloaded += 1
                    color = "success"
                else:
                    missing += 1
                    color = "warning"

                font_chips.append(
                    {
                        "component": "VChip",
                        "props": {
                            "color": color,
                            "size": "x-small",
                            "class": "mr-1 mb-1",
                        },
                        "text": font_name,
                    }
                )

            # 字幕状态摘要
            status_text = f"✅{downloaded}" if downloaded else ""
            status_text += f" ❌{missing}" if missing else ""

            # 字幕条目
            subtitle_item = {
                "component": "div",
                "props": {
                    "class": f"{indent_class} my-2 pa-2",
                    "style": "background: rgba(0,0,0,0.03); border-radius: 4px;",
                },
                "content": [
                    {
                        "component": "div",
                        "props": {"class": "d-flex justify-space-between align-center"},
                        "content": [
                            {
                                "component": "span",
                                "props": {"class": "text-body-2"},
                                "text": f"📄 {sub_name}",
                            },
                            {
                                "component": "span",
                                "props": {"class": "text-caption"},
                                "text": status_text,
                            },
                        ],
                    },
                    {
                        "component": "div",
                        "props": {"class": "mt-1"},
                        "content": font_chips,
                    },
                ],
            }
            items.append(subtitle_item)

        return items

    def __build_font_view(self, fonts: dict, status_filter: str = None) -> List[dict]:
        """
        构建字体视图：按字体状态展示
        :param fonts: 字体数据
        :param status_filter: 状态过滤（downloaded/missing），None表示全部
        """
        if not fonts:
            return [
                {
                    "component": "div",
                    "text": "暂无字体数据",
                    "props": {"class": "text-center pa-4"},
                }
            ]

        # 过滤和排序
        font_list = list(fonts.items())
        if status_filter:
            font_list = [
                (k, v) for k, v in font_list if v.get("status") == status_filter
            ]

        # 排序：缺失 > 已下载
        status_order = {"missing": 0, "downloaded": 1}
        font_list = sorted(
            font_list,
            key=lambda x: status_order.get(x[1].get("status", ""), 2),
        )

        if not font_list:
            return [
                {
                    "component": "div",
                    "text": "暂无匹配的字体",
                    "props": {"class": "text-center pa-4"},
                }
            ]

        # 构建表格
        table_rows = []
        for font_id, font_data in font_list:
            status = font_data.get("status", "missing")
            font_name = font_data.get("font_name", font_id)
            # 优先从 file_path 提取文件名，否则使用 file_name 字段
            file_path = font_data.get("file_path", "")
            if file_path:
                file_name = Path(file_path).name
            else:
                file_name = font_data.get("file_name", "")
            used_by = font_data.get("used_by", [])

            # 状态单元格
            status_text = self.__get_font_status_text(status)
            status_color = self.__get_font_status_color(status)
            status_cell = {
                "component": "td",
                "props": {"style": "padding: 12px;"},
                "content": [
                    {
                        "component": "VChip",
                        "props": {"color": status_color, "size": "small"},
                        "text": status_text,
                    }
                ],
            }

            # 引用数量
            used_count = len(used_by)

            # 日志中打印 font_id 和 font_name 便于调试
            if font_id != font_name:
                logger.debug(f"字体显示: font_id={font_id}, font_name={font_name}")

            # 构建引用字幕列表内容
            subtitle_list_content = []
            for sub_path in used_by:
                # 只显示字幕文件名
                sub_name = Path(sub_path).name
                subtitle_list_content.append({
                    "component": "div",
                    "props": {"class": "text-body-2 py-1"},
                    "text": f"📄 {sub_name}",
                })

            # 引用单元格：使用展开面板
            used_by_cell = {
                "component": "td",
                "props": {"style": "padding: 4px;"},
                "content": [
                    {
                        "component": "VExpansionPanels",
                        "props": {"variant": "accordion", "flat": True},
                        "content": [
                            {
                                "component": "VExpansionPanel",
                                "content": [
                                    {
                                        "component": "VExpansionPanelTitle",
                                        "props": {
                                            "class": "pa-2",
                                            "style": "min-height: 36px;",
                                        },
                                        "content": [
                                            {
                                                "component": "VChip",
                                                "props": {
                                                    "size": "x-small",
                                                    "color": "primary",
                                                    "variant": "outlined",
                                                },
                                                "text": f"{used_count} 个字幕",
                                            }
                                        ],
                                    },
                                    {
                                        "component": "VExpansionPanelText",
                                        "props": {
                                            "class": "pa-2",
                                            "style": "overflow-y: auto;",
                                        },
                                        "content": subtitle_list_content if subtitle_list_content else [
                                            {
                                                "component": "div",
                                                "props": {"class": "text-caption text-grey"},
                                                "text": "暂无引用",
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }

            table_row = {
                "component": "tr",
                "content": [
                    {
                        "component": "td",
                        "props": {"style": "padding: 12px;"},
                        "text": font_name,
                    },
                    status_cell,
                    {
                        "component": "td",
                        "props": {"style": "padding: 12px;"},
                        "text": file_name,
                    },
                    used_by_cell,
                ],
            }
            table_rows.append(table_row)

        return [
            {
                "component": "VTable",
                "props": {"hover": True, "fixed-header": True, "height": "30rem"},
                "content": [
                    {
                        "component": "thead",
                        "content": [
                            {
                                "component": "tr",
                                "content": [
                                    {
                                        "component": "th",
                                        "props": {
                                            "class": "text-left",
                                            "style": "width: 30%;",
                                        },
                                        "text": "字体名称",
                                    },
                                    {
                                        "component": "th",
                                        "props": {
                                            "class": "text-left",
                                            "style": "width: 20%;",
                                        },
                                        "text": "状态",
                                    },
                                    {
                                        "component": "th",
                                        "props": {
                                            "class": "text-left",
                                            "style": "width: 30%;",
                                        },
                                        "text": "文件名",
                                    },
                                    {
                                        "component": "th",
                                        "props": {
                                            "class": "text-center",
                                            "style": "width: 20%;",
                                        },
                                        "text": "引用",
                                    },
                                ],
                            }
                        ],
                    },
                    {"component": "tbody", "content": table_rows},
                ],
            }
        ]

    def __subtitlesfontcollection(self):
        """
        字幕字体补全任务
        """
        logger.info("字幕字体补全任务执行开始")

        if not self._font_path:
            logger.warning("未配置字体文件存储位置，任务终止")
            return
        if not self._media_path:
            logger.warning("未配置媒体文件路径，任务终止")
            return

        # 收集字幕文件并解析字体
        logger.info("开始扫描字幕文件...")
        media_subtitles = self.__collect_subtitles_file()

        if not media_subtitles:
            logger.info("未发现有效的字幕文件，任务终止")
            return

        # 统计扫描结果
        total_subtitles = 0
        for media in media_subtitles.values():
            if media.get("media_type") == "movie":
                total_subtitles += len(media.get("subtitles", {}))
            else:
                for season in media.get("seasons", {}).values():
                    for episode in season.get("episodes", {}).values():
                        total_subtitles += len(episode.get("subtitles", {}))

        logger.info(
            f"扫描完成：发现 {len(media_subtitles)} 个媒体，{total_subtitles} 个字幕文件"
        )

        # 根据字体库更新字体状态
        logger.info("检查字体库中已有的字体...")
        self.__update_fonts_status_from_library()

        # 更新统计数据
        stats = self.__update_all_fonts_status()

        # 获取缺失字体列表
        fonts_data = self.get_data("fonts") or {}
        missing_fonts = [
            k for k, f in fonts_data.items() if f.get("status") == "missing"
        ]

        # 如果启用了自动下载且有缺失字体，执行下载任务
        download_success = []
        download_fail = []
        if self._auto_download and missing_fonts:
            logger.info(f"开始下载缺失字体，共 {len(missing_fonts)} 个...")
            download_success, download_fail = self.__download_missing_fonts(missing_fonts)

            # 下载完成后再次刷新字体状态
            logger.info("下载完成，重新检查字体库...")
            self.__update_fonts_status_from_library()

            # 更新统计数据
            stats = self.__update_all_fonts_status()

        # 发送通知
        if self._notify:
            # 重新获取最新的字体数据
            fonts_data = self.get_data("fonts") or {}
            missing_fonts_after = [
                f.get("font_name", k)
                for k, f in fonts_data.items()
                if f.get("status") == "missing"
            ]

            # 构建通知内容
            text_parts = [
                f"📊 扫描结果：",
                f"• 媒体数量：{stats.get('total_media', 0)}",
                f"• 字幕文件：{stats.get('total_subtitles', 0)}",
                f"• 字体总数：{stats.get('total_fonts', 0)}",
                f"• 已下载：{stats.get('downloaded_fonts', 0)}",
                f"• 缺失：{stats.get('missing_fonts', 0)}",
            ]

            # 添加下载结果信息
            if self._auto_download and (download_success or download_fail):
                text_parts.append("")
                text_parts.append(f"📥 下载结果：")
                if download_success:
                    text_parts.append(f"✅ 成功：{len(download_success)} 个")
                if download_fail:
                    text_parts.append(f"❌ 失败：{len(download_fail)} 个")
                    # 显示部分失败字体名称
                    fail_names = download_fail[:5]
                    text_parts.append(f"   失败字体：{', '.join(fail_names)}")
                    if len(download_fail) > 5:
                        text_parts.append(f"   ... 等共 {len(download_fail)} 个")

            # 添加仍缺失的字体信息
            if missing_fonts_after:
                text_parts.append("")
                text_parts.append(f"⚠️ 仍缺失字体：{', '.join(missing_fonts_after[:10])}")
                if len(missing_fonts_after) > 10:
                    text_parts.append(f"... 等共 {len(missing_fonts_after)} 个")
            else:
                text_parts.append("")
                text_parts.append("✅ 所有字体已下载完成！")

            self.post_message(
                mtype=NotificationType.Plugin,
                title="字幕字体补全扫描完成",
                text="\n".join(text_parts),
            )

        logger.info("字幕字体补全任务执行完成")

    def __download_missing_fonts(self, font_names: List[str]) -> Tuple[List[str], List[str]]:
        """
        下载缺失的字体
        :param font_names: 缺失字体名称列表
        :return: (成功列表, 失败列表)
        """
        if not font_names:
            return [], []

        if not self._font_path:
            logger.warning("未配置字体存储路径，无法下载字体")
            return [], font_names

        success_fonts = []
        fail_fonts = []

        try:
            # 初始化字体下载器
            downloader = FontDownloader(use_caution=self._use_caution_fonts)
            total = len(font_names)

            # 逐个下载字体
            logger.info(f"开始下载 {total} 个缺失字体到 {self._font_path}")
            for idx, font_name in enumerate(font_names, 1):
                # 检查任务是否被停止
                if self._event.is_set():
                    logger.info("字体下载任务被停止")
                    # 将剩余未下载的字体添加到失败列表
                    fail_fonts.extend(font_names[idx - 1:])
                    break

                logger.info(f"[{idx}/{total}] 正在下载字体：{font_name}")

                # 下载单个字体
                success, file_path = downloader.download_font(font_name, self._font_path)
                if success:
                    success_fonts.append(font_name)
                    logger.info(f"[{idx}/{total}] 字体下载成功：{font_name} -> {file_path}")

                    # 立即更新该字体的状态
                    self.__update_font_record(
                        font_id=font_name,
                        status="downloaded",
                        file_path=file_path,
                    )
                    # 更新统计数据
                    self.__update_all_fonts_status()
                else:
                    fail_fonts.append(font_name)
                    logger.warning(f"[{idx}/{total}] 字体下载失败：{font_name}")

            logger.info(f"字体下载完成：成功 {len(success_fonts)} 个，失败 {len(fail_fonts)} 个")

            if success_fonts:
                logger.info(f"下载成功的字体：{', '.join(success_fonts)}")
            if fail_fonts:
                logger.warning(f"下载失败的字体：{', '.join(fail_fonts)}")

            return success_fonts, fail_fonts

        except FileNotFoundError as e:
            logger.error(f"字体映射文件不存在：{e}")
            return success_fonts, fail_fonts + [f for f in font_names if f not in success_fonts and f not in fail_fonts]
        except Exception as e:
            logger.error(f"下载字体时发生错误：{e}")
            return success_fonts, fail_fonts + [f for f in font_names if f not in success_fonts and f not in fail_fonts]

    def __parse_storage_type(self, path: str) -> Tuple[str, StorageSchema]:
        """
        解析路径中的存储类型
        :param path: 路径字符串，可能包含#存储类型后缀
        :return: (纯路径, 存储类型)
        """
        storage_type = StorageSchema.Local
        clean_path = path.strip()

        if "#" in clean_path:
            parts = clean_path.split("#")
            if len(parts) == 2:
                clean_path = parts[0]
                storage_type_str = parts[1].strip()
                storage_map = {
                    "Local": StorageSchema.Local,
                    "Alipan": StorageSchema.Alipan,
                    "115": StorageSchema.U115,
                    "Rclone": StorageSchema.Rclone,
                    "OpenList": StorageSchema.Alist,
                }
                storage_type = storage_map.get(storage_type_str, StorageSchema.Local)

        return clean_path, storage_type

    def __is_excluded_path(self, file_path: Path, exclude_paths: List[str]) -> bool:
        """
        检查路径是否在排除列表中
        """
        for exclude_path in exclude_paths:
            if not exclude_path or not exclude_path.strip():
                continue
            try:
                if file_path.is_relative_to(Path(exclude_path.strip())):
                    return True
            except Exception as err:
                logger.debug(f"检查排除路径异常：{err}")
        return False

    def __parse_media_info(self, file_path: Path) -> Dict[str, Any]:
        """
        解析媒体信息，区分电影和电视剧
        :param file_path: 字幕文件路径
        :return: 媒体信息字典
        """
        import re

        file_meta = MetaInfoPath(file_path)
        media_name = file_meta.name or "未知名称"
        year = file_meta.year or ""

        # 尝试解析季集信息
        season = None
        episode = None
        episode_name = ""

        # 从路径或文件名中解析季集信息
        path_str = str(file_path)

        # 匹配 S01E01 格式
        se_match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", path_str)
        if se_match:
            season = f"S{int(se_match.group(1)):02d}"
            episode = f"E{int(se_match.group(2)):02d}"

        # 如果没有匹配到，尝试匹配 Season X 格式
        if not season:
            season_match = re.search(r"[Ss]eason\s*(\d{1,2})", path_str, re.IGNORECASE)
            if season_match:
                season = f"S{int(season_match.group(1)):02d}"

        # 尝试从路径结构中获取季信息
        if not season:
            for part in file_path.parts:
                s_match = re.match(r"^[Ss](\d{1,2})$", part)
                if s_match:
                    season = f"S{int(s_match.group(1)):02d}"
                    break

        # 判断媒体类型
        media_type = "tv" if season else "movie"

        # 构建媒体路径（作为唯一标识）
        if media_type == "tv":
            # 电视剧：使用父目录的父目录（或更上层）作为媒体路径
            # 假设结构：/tv/剧名/S01/xxx.ass 或 /tv/剧名/Season 1/xxx.ass
            media_path = None
            for i, part in enumerate(file_path.parts):
                if re.match(r"^[Ss]\d{1,2}$", part) or re.match(
                    r"^[Ss]eason\s*\d{1,2}$", part, re.IGNORECASE
                ):
                    media_path = str(Path(*file_path.parts[:i]))
                    break
            if not media_path:
                # 尝试使用倒数第二个目录
                media_path = (
                    str(file_path.parent.parent)
                    if len(file_path.parts) > 2
                    else str(file_path.parent)
                )
        else:
            # 电影：使用父目录作为媒体路径
            media_path = str(file_path.parent)

        return {
            "media_path": media_path,
            "media_name": media_name,
            "media_type": media_type,
            "year": str(year) if year else "",
            "season": season,
            "episode": episode,
            "episode_name": episode_name,
            "subtitle_name": file_path.name,
            "subtitle_path": str(file_path),
        }

    def __extract_fonts_from_subtitle(
        self, subtitle_path: Path, storage_type: StorageSchema
    ) -> List[str]:
        """
        从字幕文件中提取字体信息
        :param subtitle_path: 字幕文件路径
        :param storage_type: 存储类型
        :return: 字体ID列表
        """
        fonts = []
        local_file_path = None
        is_temp_file = False  # 标记是否为临时文件（需要清理）

        try:
            file_manager = FileManagerModule()
            file_manager.init_module()

            # 获取文件项
            file_item = file_manager.get_file_item(storage_type.value, subtitle_path)
            if not file_item:
                logger.warning(f"无法获取字幕文件项：{subtitle_path}")
                return fonts

            logger.debug(f"读取字幕文件内容：{subtitle_path}（存储类型：{storage_type.value}）")

            # 下载文件到本地（本地存储会直接返回原路径，远程存储会下载到临时目录）
            local_file_path = file_manager.download_file(file_item)
            if not local_file_path or not local_file_path.exists():
                logger.warning(f"无法下载字幕文件：{subtitle_path}")
                return fonts

            # 判断是否为临时文件（非本地存储下载的文件需要清理）
            # 本地存储返回的路径与原路径相同，无需清理
            is_temp_file = storage_type != StorageSchema.Local and local_file_path != subtitle_path

            # 读取文件内容，尝试多种编码
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'gb18030', 'utf-16', 'utf-16-le', 'utf-16-be']:
                try:
                    with open(local_file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.debug(f"字幕文件 {subtitle_path.name} 使用编码：{encoding}")
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

            if not content:
                logger.warning(f"无法读取字幕文件内容（编码识别失败）：{subtitle_path}")
                return fonts

            # 使用字体解析器解析并过滤出实际使用的字体
            parser = SubtitleFontParser()
            fonts = parser.filter_used_fonts(content)

            logger.info(f"字幕 {subtitle_path.name} 共发现 {len(fonts)} 个实际使用的字体：{fonts}")

        except Exception as e:
            logger.error(f"解析字幕字体失败 {subtitle_path}: {e}")

        finally:
            # 清理临时文件
            if is_temp_file and local_file_path and local_file_path.exists():
                try:
                    local_file_path.unlink()
                    logger.debug(f"已清理临时文件：{local_file_path}")
                except Exception as e:
                    logger.warning(f"清理临时文件失败 {local_file_path}: {e}")

        return fonts

    def __collect_subtitles_file(self) -> Dict[str, Any]:
        """
        收集字幕文件数据结构组织
        :return: media_subtitles 数据结构
        """
        from datetime import datetime

        exclude_paths = [
            p.strip() for p in self._exclude_paths.split("\n") if p.strip()
        ]
        paths = [p.strip() for p in self._media_path.split("\n") if p.strip()]

        # 媒体-字幕关系数据
        media_subtitles = self.get_data("media_subtitles") or {}
        # 字体全局数据
        fonts_data = self.get_data("fonts") or {}

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subtitle_extensions = settings.RMT_SUBEXT  # 字幕文件扩展名

        for path in paths:
            if not path:
                continue

            clean_path, storage_type = self.__parse_storage_type(path)

            file_manager = FileManagerModule()
            file_manager.init_module()

            logger.debug(f"尝试从存储 [{storage_type}] 获取路径：{clean_path}")

            try:
                # 获取文件项
                file_item = file_manager.get_file_item(
                    storage_type.value, Path(clean_path)
                )
                if not file_item:
                    logger.warning(f"存储 [{storage_type}] 中未找到路径：{clean_path}")
                    continue

                logger.debug(f"在存储 [{storage_type}] 中找到路径：{clean_path}")

                # 列出所有文件
                file_list = file_manager.list_files(file_item, recursion=True)
                if not file_list:
                    logger.debug(f"存储 [{storage_type}] 路径 {clean_path} 下无文件")
                    continue

                # 筛选字幕文件
                for file in file_list:
                    if self._event.is_set():
                        logger.info("字幕字体补全服务停止")
                        return media_subtitles

                    # 检查是否是文件
                    if file.type != "file":
                        continue

                    # 检查是否是字幕文件
                    if (
                        not file.extension
                        or f".{file.extension.lower()}" not in subtitle_extensions
                    ):
                        continue

                    if not file.path:
                        continue

                    file_path = Path(file.path)

                    # 检查是否在排除路径中
                    if self.__is_excluded_path(file_path, exclude_paths):
                        logger.debug(f"{file_path} 在排除目录中，跳过...")
                        continue

                    # 解析媒体信息
                    media_info = self.__parse_media_info(file_path)
                    media_path = media_info["media_path"]
                    media_name = media_info["media_name"]
                    media_type = media_info["media_type"]
                    year = media_info["year"]
                    season = media_info["season"]
                    episode = media_info["episode"]
                    subtitle_name = media_info["subtitle_name"]
                    subtitle_path = media_info["subtitle_path"]

                    logger.debug(
                        f"发现字幕文件：{subtitle_path} (媒体: {media_name}, 类型: {media_type})"
                    )

                    # 提取字幕中的字体
                    font_ids = self.__extract_fonts_from_subtitle(
                        file_path, storage_type
                    )
                    logger.debug(f"字幕 {subtitle_name} 使用字体: {font_ids}")

                    # 更新字体全局数据
                    for font_id in font_ids:
                        if font_id not in fonts_data:
                            fonts_data[font_id] = {
                                "font_name": font_id,  # 初始使用ID作为名称
                                "file_name": "",
                                "status": "missing",
                                "file_path": "",
                                "used_by": [],
                                "update_time": current_time,
                            }
                        # 添加引用
                        if subtitle_path not in fonts_data[font_id]["used_by"]:
                            fonts_data[font_id]["used_by"].append(subtitle_path)

                    # 构建字幕数据
                    subtitle_data = {
                        "subtitle_path": subtitle_path,
                        "fonts": font_ids,
                        "scan_time": current_time,
                    }

                    # 根据媒体类型组织数据
                    if media_path not in media_subtitles:
                        media_subtitles[media_path] = {
                            "media_name": media_name,
                            "media_type": media_type,
                            "year": year,
                        }
                        if media_type == "movie":
                            media_subtitles[media_path]["subtitles"] = {}
                        else:
                            media_subtitles[media_path]["seasons"] = {}

                    if media_type == "movie":
                        # 电影：直接添加到 subtitles
                        media_subtitles[media_path]["subtitles"][
                            subtitle_name
                        ] = subtitle_data
                    else:
                        # 电视剧：按季/集组织
                        if "seasons" not in media_subtitles[media_path]:
                            media_subtitles[media_path]["seasons"] = {}

                        if season:
                            if season not in media_subtitles[media_path]["seasons"]:
                                media_subtitles[media_path]["seasons"][season] = {
                                    "season_name": season.replace("S", "第") + "季",
                                    "episodes": {},
                                }

                            if episode:
                                if (
                                    episode
                                    not in media_subtitles[media_path]["seasons"][
                                        season
                                    ]["episodes"]
                                ):
                                    media_subtitles[media_path]["seasons"][season][
                                        "episodes"
                                    ][episode] = {"episode_name": "", "subtitles": {}}
                                media_subtitles[media_path]["seasons"][season][
                                    "episodes"
                                ][episode]["subtitles"][subtitle_name] = subtitle_data
                            else:
                                # 有季但没有集信息，放到 E00
                                if (
                                    "E00"
                                    not in media_subtitles[media_path]["seasons"][
                                        season
                                    ]["episodes"]
                                ):
                                    media_subtitles[media_path]["seasons"][season][
                                        "episodes"
                                    ]["E00"] = {"episode_name": "其他", "subtitles": {}}
                                media_subtitles[media_path]["seasons"][season][
                                    "episodes"
                                ]["E00"]["subtitles"][subtitle_name] = subtitle_data
                        else:
                            # 没有季信息，放到 S00
                            if "S00" not in media_subtitles[media_path]["seasons"]:
                                media_subtitles[media_path]["seasons"]["S00"] = {
                                    "season_name": "其他",
                                    "episodes": {},
                                }
                            if (
                                "E00"
                                not in media_subtitles[media_path]["seasons"]["S00"][
                                    "episodes"
                                ]
                            ):
                                media_subtitles[media_path]["seasons"]["S00"][
                                    "episodes"
                                ]["E00"] = {"episode_name": "其他", "subtitles": {}}
                            media_subtitles[media_path]["seasons"]["S00"]["episodes"][
                                "E00"
                            ]["subtitles"][subtitle_name] = subtitle_data

            except Exception as e:
                logger.error(f"从存储 [{storage_type}] 获取路径 {clean_path} 失败：{e}")
                continue

        # 保存数据
        self.save_data("media_subtitles", media_subtitles)
        self.save_data("fonts", fonts_data)

        return media_subtitles

    def __check_font_exists(self, font_id: str) -> Tuple[bool, Optional[str]]:
        """
        检查字体是否已存在于字体库中
        :param font_id: 字体ID
        :return: (是否存在, 存在时的文件路径)
        """
        if not self._font_path:
            return False, None

        # 1. 首先检查存储数据中记录的文件路径是否存在
        fonts_data = self.get_data("fonts") or {}
        if font_id in fonts_data:
            stored_file_path = fonts_data[font_id].get("file_path")
            if stored_file_path and Path(stored_file_path).exists():
                return True, stored_file_path

        # 2. 扫描字体目录中的所有字体文件进行匹配
        existing_files = self.__get_font_files_in_directory()

        # 使用工具类检查字体是否存在
        return FontUtils.check_font_exists_in_directory(font_id, self._font_path, existing_files)

    def __get_font_files_in_directory(self) -> Dict[str, str]:
        """
        获取字体目录中所有的字体文件
        :return: {文件名: 完整路径} 字典
        """
        return FontUtils.get_font_files_in_directory(self._font_path)

    def __update_fonts_status_from_library(self):
        """
        根据字体库更新字体状态
        - 检查标记为 missing 的字体是否已存在于字体库中
        - 检查标记为 downloaded 的字体文件是否仍然存在
        """
        from datetime import datetime
        logger.info("更新字体状态中...")
        fonts_data = self.get_data("fonts") or {}
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated = False

        for font_id, font_info in fonts_data.items():
            current_status = font_info.get("status")
            exists, file_path = self.__check_font_exists(font_id)

            if current_status != "downloaded":
                # 检查缺失字体是否已存在于字体库中
                if exists:
                    fonts_data[font_id]["status"] = "downloaded"
                    fonts_data[font_id]["file_path"] = file_path or ""
                    fonts_data[font_id]["update_time"] = current_time
                    logger.info(f"字体 {font_id} 已在字体库中找到，状态更新为已下载")
                    updated = True
            else:
                # 检查已下载字体的文件是否仍然存在
                if not exists:
                    fonts_data[font_id]["status"] = "missing"
                    fonts_data[font_id]["file_path"] = ""
                    fonts_data[font_id]["update_time"] = current_time
                    logger.warning(f"字体 {font_id} 的文件已不存在，状态更新为缺失")
                    updated = True
                elif file_path and fonts_data[font_id].get("file_path") != file_path:
                    # 更新文件路径（如果路径有变化）
                    fonts_data[font_id]["file_path"] = file_path
                    fonts_data[font_id]["update_time"] = current_time
                    updated = True

        if updated:
            self.save_data("fonts", fonts_data)
        self.__update_all_fonts_status()
        logger.info("更新字体状态完成")

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        # 默认每7天执行一次
        cron = self._cron if self._cron else "0 0 */7 * *"

        if self._enabled:
            return [
                {
                    "id": "SubtitlesFontCollection_ScanSubtitles",
                    "name": "字幕字体补全_扫描字幕文件",
                    "trigger": CronTrigger.from_crontab(cron),
                    "func": self.__subtitlesfontcollection,
                    "kwargs": {},
                },
                {
                    "id": "SubtitlesFontCollection_UpdateFontsStatus",
                    "name": "字幕字体补全_字体状态更新",
                    "trigger": CronTrigger.from_crontab("* * * * *"),
                    "func": self.__update_fonts_status_from_library,
                    "kwargs": {},
                }
            ]
        return []
        pass

    def stop_service(self):
        """
        停止插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
            self.__update_all_fonts_status()
            logger.info("字幕字体补全插件已停止")
        except Exception as e:
            print(str(e))
            logger.error(f"字幕字体补全插件停止失败：{str(e)}")
