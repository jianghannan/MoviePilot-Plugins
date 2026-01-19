import pytz
from pathlib import Path
from app.log import logger
from threading import Event
from app.plugins import _PluginBase
from app.core.config import settings
from datetime import datetime, timedelta
from apscheduler.triggers.cron import CronTrigger
from typing import Any, List, Dict, Tuple, Optional
from app.schemas.types import NotificationType
from apscheduler.schedulers.background import BackgroundScheduler


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
    _media_path = ""
    _notify = True  # 是否发送通知
    _active_tab = "all"  # 当前激活的Tab: all/downloaded/downloading/missing

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
            self._onlyonce = config.get("onlyonce")
            self._enabled = config.get("enabled", False)
            self._font_path = config.get("font_path", "")
            self._media_path = config.get("media_path", "")
            self._notify = config.get("notify", True)

            # 处理清除数据
            if config.get("clear_data"):
                self.__clear_all_data()
                # 关闭清除数据开关
                config["clear_data"] = False
                self.update_config(config)
                logger.info("字幕字体补全插件数据已清除")

        logger.info(f"字幕字体补全插件初始化完成，启用状态：{self._enabled}")

        # 启动定时任务 & 立即运行一次
        if self._enabled or self._onlyonce:

            if self._onlyonce:
                logger.info(f"字幕字体补全，立即运行一次")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(
                    func=self.__subtitlesfontcollection,
                    trigger="date",
                    run_date=datetime.now(tz=pytz.timezone(settings.TZ))
                    + timedelta(seconds=3),
                    name="字幕字体补全",
                )
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config(
                    {
                        "onlyonce": False,
                        "enabled": self._enabled,
                        "cron": self._cron,
                        "font_path": self._font_path,
                        "media_path": self._media_path,
                        "notify": self._notify,
                    }
                )
                if self._scheduler.get_jobs():
                    # 启动服务
                    self._scheduler.print_jobs()
                    self._scheduler.start()
        if self._enabled:
            logger.info(f"仅运行一次：{self._onlyonce}")
            logger.info(
                f"执行周期：{self.__cron2text(self._cron) if self._cron else '默认每7天执行一次'}"
            )
            logger.info(f"字体存储路径：{self._font_path}")
            logger.info(f"媒体文件路径：{self._media_path}")

    def __clear_all_data(self):
        """
        清除所有插件数据
        """
        # 清除字体数据
        self.save_data("fonts", {})
        # 清除统计数据
        self.save_data("missing_font_count", 0)
        self.save_data("downloaded_font_count", 0)
        self.save_data("downloading_font_count", 0)
        logger.info("已清除所有字体数据")

    def __sub_missing_fonts_count(self):
        """
        计算缺失的字体文件数量
        """
        fonts = self.get_data("fonts") or {}
        missing_count = sum(
            1 for font in fonts.values() if font.get("actions") == "缺失"
        )
        self.save_data("missing_font_count", missing_count)

    def __sub_downloaded_fonts_count(self):
        """
        计算已下载的字体文件数量
        """
        fonts = self.get_data("fonts") or {}
        downloaded_count = sum(
            1 for font in fonts.values() if font.get("actions") == "已下载"
        )
        self.save_data("downloaded_font_count", downloaded_count)

    def __sub_downloading_fonts_count(self):
        """
        计算下载中的字体文件数量
        """
        fonts = self.get_data("fonts") or {}
        downloading_count = sum(
            1 for font in fonts.values() if font.get("actions") == "下载中"
        )
        self.save_data("downloading_font_count", downloading_count)

    def __update_all_fonts_status(self):
        """
        更新所有字体的状态统计
        """
        self.__sub_missing_fonts_count()
        self.__sub_downloaded_fonts_count()
        self.__sub_downloading_fonts_count()

    def __send_font_notification(
        self,
        media_name: str,
        subtitle_file: Optional[list],
        subtitle_path: str,
        font_status: str,
        font_count: int = 0,
        failed_fonts: Optional[list] = None,
    ):
        """
        发送字体下载完成通知
        :param media_name: 电影或电视剧名称
        :param subtitle_file: 字幕文件名List
        :param subtitle_path: 字幕文件地址
        :param font_status: 字体下载状态（成功/部分成功/失败）
        :param font_count: 下载的字体数量
        :param failed_fonts: 失败的字体列表
        """
        if not self._notify:
            return

        # 构建通知内容
        if not subtitle_file:
            subtitle_file = ["未知字幕文件"]

        text_lines = [
            f"📄 字幕文件：{','.join(subtitle_file)}\n",
            f"📁 文件地址：{subtitle_path}\n",
            f"📊 下载状态：{font_status}",
        ]

        if font_count > 0:
            text_lines.append(f"\n✅ 下载数量：{font_count} 个字体")

        if failed_fonts:
            text_lines.append(f"\n❌ 失败字体：\n{','.join(failed_fonts)}")
        text = "\n".join(text_lines)

        self.post_message(
            mtype=NotificationType.Plugin,
            title=f"[{media_name}] 字幕字体补全任务执行完成",
            text=text,
        )
        logger.info(f"已发送字体补全通知：{media_name} - {subtitle_file}")

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
        logger.info(f"切换Tab到: {tab}")
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
                                        "component": "VTextField",
                                        "props": {
                                            "model": "media_path",
                                            "label": "媒体文件位置",
                                            "placeholder": "/Video",
                                            "hint": "媒体文件存储的完整路径，例如：/Video",
                                            "persistent-hint": True,
                                            "clearable": True,
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
                                            "text": "配置说明：\n1. 字体文件存储位置：用于存放下载的字体文件\n2. 媒体文件位置：用于扫描包含字幕的媒体文件",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {"enabled": False, "font_path": "", "media_path": "", "notify": True}

    def get_page(self) -> List[dict]:
        # 从配置中读取当前Tab状态
        config = self.get_config()
        if config:
            self._active_tab = config.get("active_tab", "all")

        # 字体明细
        fonts = self.get_data("fonts") or {}

        if not fonts:
            return [
                {
                    "component": "div",
                    "text": "暂无数据",
                    "props": {
                        "class": "text-center",
                    },
                }
            ]

        # 分类数据
        all_fonts = list(fonts.values())
        downloaded_fonts = [f for f in all_fonts if f.get("actions") == "已下载"]
        downloading_fonts = [f for f in all_fonts if f.get("actions") == "下载中"]
        missing_fonts = [f for f in all_fonts if f.get("actions") == "缺失"]

        # 根据当前Tab选择显示的数据
        if self._active_tab == "downloaded":
            display_fonts = downloaded_fonts
        elif self._active_tab == "downloading":
            display_fonts = downloading_fonts
        elif self._active_tab == "missing":
            display_fonts = missing_fonts
        else:
            display_fonts = all_fonts

        # 排序：下载中的按进度降序排列
        status_order = {"缺失": 0, "下载中": 1, "已下载": 2}
        display_fonts = sorted(
            display_fonts,
            key=lambda x: (
                status_order.get(x.get("actions", ""), 3),
                -(x.get("progress", 0) if x.get("actions") == "下载中" else 0),
            ),
        )

        # 统计数量
        downloaded_count = len(downloaded_fonts)
        downloading_count = len(downloading_fonts)
        missing_count = len(missing_fonts)

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

        # 获取当前激活Tab的索引
        tab_ids = ["all", "downloaded", "downloading", "missing"]
        current_index = (
            tab_ids.index(self._active_tab) if self._active_tab in tab_ids else 0
        )

        # 构建表格行
        table_rows = []
        for data in display_fonts:
            status = data.get("actions")
            font_name = data.get("font_name")
            file_name = data.get("file_name")

            # 状态显示内容
            if status == "下载中":
                progress = data.get("progress", 0)
                status_cell = {
                    "component": "td",
                    "props": {"style": "width: 200px; padding: 12px;"},
                    "content": [
                        {
                            "component": "VProgressLinear",
                            "props": {
                                "model-value": progress,
                                "color": "info",
                                "height": "20",
                            },
                            "content": [
                                {"component": "strong", "text": f"{progress}%"}
                            ],
                        }
                    ],
                }
            elif status == "已下载":
                status_cell = {
                    "component": "td",
                    "props": {"style": "padding: 12px;"},
                    "content": [
                        {
                            "component": "VChip",
                            "props": {"color": "success", "size": "small"},
                            "text": status,
                        }
                    ],
                }
            else:  # 缺失
                status_cell = {
                    "component": "td",
                    "props": {"style": "padding: 12px;"},
                    "content": [
                        {
                            "component": "VChip",
                            "props": {"color": "warning", "size": "small"},
                            "text": status,
                        }
                    ],
                }

            # 创建表格行
            table_row = {
                "component": "tr",
                "content": [
                    {
                        "component": "td",
                        "props": {"style": "padding: 12px;"},
                        "content": [
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-2"},
                                "text": font_name,
                            }
                        ],
                    },
                    status_cell,
                    {
                        "component": "td",
                        "props": {"style": "padding: 12px;"},
                        "content": [
                            {
                                "component": "div",
                                "props": {"class": "text-body-2"},
                                "text": file_name,
                            }
                        ],
                    },
                ],
            }
            table_rows.append(table_row)

        # 拼装页面 - 使用Tab切换显示
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
                                                "all", "全部", len(all_fonts), "📊"
                                            ),
                                            build_tab_item(
                                                "downloaded",
                                                "已下载",
                                                downloaded_count,
                                                "✅",
                                            ),
                                            build_tab_item(
                                                "downloading",
                                                "下载中",
                                                downloading_count,
                                                "⬇️",
                                            ),
                                            build_tab_item(
                                                "missing", "缺失", missing_count, "❌"
                                            ),
                                        ],
                                    },
                                    {"component": "VDivider"},
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {
                                                "component": "VTable",
                                                "props": {
                                                    "hover": True,
                                                    "fixed-header": True,
                                                    "height": "30rem",
                                                },
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
                                                                            "style": "width: 35%;",
                                                                        },
                                                                        "text": "字体名称",
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {
                                                                            "class": "text-left",
                                                                            "style": "width: 25%;",
                                                                        },
                                                                        "text": "状态",
                                                                    },
                                                                    {
                                                                        "component": "th",
                                                                        "props": {
                                                                            "class": "text-left",
                                                                            "style": "width: 40%;",
                                                                        },
                                                                        "text": "文件名",
                                                                    },
                                                                ],
                                                            }
                                                        ],
                                                    },
                                                    {
                                                        "component": "tbody",
                                                        "content": (
                                                            table_rows
                                                            if table_rows
                                                            else [
                                                                {
                                                                    "component": "tr",
                                                                    "content": [
                                                                        {
                                                                            "component": "td",
                                                                            "props": {
                                                                                "colspan": 3,
                                                                                "class": "text-center pa-4",
                                                                            },
                                                                            "text": "暂无数据",
                                                                        }
                                                                    ],
                                                                }
                                                            ]
                                                        ),
                                                    },
                                                ],
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

    def __subtitlesfontcollection(self):
        """
        字幕字体补全任务
        """
        logger.info("字幕字体补全任务开始执行")
        # self.__add_debug_data()
        self.__update_all_fonts_status()
        self.__send_font_notification(
            "111", ["2220","2221"], "333", "测试", 10, ["444", "555"]
        )  # 发送测试通知
        logger.info("字幕字体补全任务执行完成")

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
        if self._enabled and self._cron:
            return [
                {
                    "id": "SubtitlesFontCollection",
                    "name": "字幕字体补全",
                    "trigger": CronTrigger.from_crontab(self._cron),
                    "func": self.__subtitlesfontcollection,
                    "kwargs": {},
                }
            ]
        elif self._enabled:
            return [
                {
                    "id": "SubtitlesFontCollection",
                    "name": "字幕字体补全",
                    "trigger": CronTrigger.from_crontab("0 0 */7 * *"),
                    "func": self.__subtitlesfontcollection,
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
