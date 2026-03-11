import json
import re
from collections.abc import AsyncGenerator
from functools import wraps
from typing import Any, Dict, List, Optional

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import MessageEventResult, filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

PRIO_HIGH = 100


def _high_priority(deco):
    @wraps(deco)
    def wrapper(*args, **kwargs):
        kwargs.setdefault("priority", PRIO_HIGH)
        return deco(*args, **kwargs)
    return wrapper


high_priority_event = _high_priority(filter.event_message_type)


@register(
    "astrbot_plugin_welcome",
    "Sunchser",
    "一个简单的入群欢迎插件",
    "v2.0.0",
)
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}

    # =========================================================
    # 配置读取
    # =========================================================
    def _is_enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def _repair_multiline_welcome_text_json(self, raw: str) -> str:
        pattern = r'("welcome_text"\s*:\s*")([\s\S]*?)(")(\s*,\s*"image_url"\s*:)'

        def repl(match):
            prefix = match.group(1)
            content = match.group(2)
            quote = match.group(3)
            suffix = match.group(4)

            content = content.replace("\\", "\\\\")
            content = content.replace('"', '\\"')
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = content.replace("\n", "\\n")

            return f"{prefix}{content}{quote}{suffix}"

        try:
            return re.sub(pattern, repl, raw, flags=re.MULTILINE)
        except Exception:
            return raw

    def _get_rules(self) -> List[Dict[str, Any]]:
        raw = self.config.get("welcome_config_json", "[]")

        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]

        if not isinstance(raw, str):
            return []

        raw = raw.strip()
        if not raw:
            return []

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass

        fixed = self._repair_multiline_welcome_text_json(raw)
        try:
            data = json.loads(fixed)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass

        return []

    def _find_rule(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = str(group_id)
        for rule in self._get_rules():
            if str(rule.get("group_id", "")).strip() == gid:
                return rule
        return None

    def _render_text(self, template: str, group_id: str, user_id: str) -> str:
        user_name = user_id or "新朋友"
        text = template or "欢迎 {user_name} 加入本群~"
        return (
            text.replace("{group_id}", str(group_id or ""))
            .replace("{user_id}", str(user_id or ""))
            .replace("{user_name}", str(user_name))
            .replace("{nickname}", str(user_name))
        )

    # =========================================================
    # 监听入群事件
    # =========================================================
    @high_priority_event(filter.EventMessageType.ALL)
    async def handle_group_increase(
        self, event: AiocqhttpMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        try:
            if not self._is_enabled():
                return

            if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "raw_message"):
                return

            raw_message = event.message_obj.raw_message
            if not raw_message or not isinstance(raw_message, dict):
                return

            if (
                raw_message.get("post_type") == "notice"
                and raw_message.get("notice_type") == "group_increase"
            ):
                group_id = str(raw_message.get("group_id", "") or "")
                user_id = str(raw_message.get("user_id", "") or "")

                if not group_id or not user_id:
                    return

                rule = self._find_rule(group_id)
                if not rule:
                    return

                welcome_text = self._render_text(
                    str(rule.get("welcome_text", "") or ""),
                    group_id,
                    user_id
                )
                image_url = str(rule.get("image_url", "") or "").strip()

                chain = []

                if image_url:
                    if image_url.startswith("http://") or image_url.startswith("https://"):
                        chain.append(Comp.Image.fromURL(image_url))
                    else:
                        chain.append(Comp.Image.fromFileSystem(image_url))

                chain.append(Comp.Plain(welcome_text))

                yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"处理入群欢迎事件出错: {e}")

    # =========================================================
    # 调试命令
    # =========================================================
    @filter.command("welcome_show")
    async def welcome_show(
        self, event: AiocqhttpMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("当前不在群聊中。")
            return

        rule = self._find_rule(group_id)
        if not rule:
            yield event.plain_result(f"当前群 {group_id} 未配置欢迎规则。")
            return

        text = self._render_text(str(rule.get("welcome_text", "") or ""), group_id, "10000")
        image_url = str(rule.get("image_url", "") or "").strip()

        yield event.plain_result(
            f"当前群欢迎配置：group_id={rule.get('group_id', '')}, "
            f"welcome_text={rule.get('welcome_text', '')}, "
            f"image_url={image_url}"
        )

        chain = []
        if image_url:
            if image_url.startswith("http://") or image_url.startswith("https://"):
                chain.append(Comp.Image.fromURL(image_url))
            else:
                chain.append(Comp.Image.fromFileSystem(image_url))
        chain.append(Comp.Plain(f"[测试欢迎]\n{text}"))
        yield event.chain_result(chain)