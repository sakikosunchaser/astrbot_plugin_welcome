import os
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
    "v2.0.2",
)
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        logger.info("[welcome-debug] plugin loaded, config=%s", dict(self.config))

    def _is_enabled(self) -> bool:
        enabled = bool(self.config.get("enabled", True))
        logger.info("[welcome-debug] enabled=%s", enabled)
        return enabled

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
        except Exception as e:
            logger.error("[welcome-debug] multiline repair failed: %s", e)
            return raw

    def _get_rules(self) -> List[Dict[str, Any]]:
        raw = self.config.get("welcome_config_json", "[]")
        logger.info("[welcome-debug] welcome_config_json raw=%r", raw)

        if isinstance(raw, list):
            rules = [x for x in raw if isinstance(x, dict)]
            logger.info("[welcome-debug] rules(from list)=%s", rules)
            return rules

        if not isinstance(raw, str):
            logger.warning("[welcome-debug] welcome_config_json type invalid: %s", type(raw))
            return []

        raw = raw.strip()
        if not raw:
            logger.warning("[welcome-debug] welcome_config_json empty")
            return []

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                rules = [x for x in data if isinstance(x, dict)]
                logger.info("[welcome-debug] rules(from json)=%s", rules)
                return rules
        except Exception as e:
            logger.warning("[welcome-debug] json parse failed: %s", e)

        fixed = self._repair_multiline_welcome_text_json(raw)
        try:
            data = json.loads(fixed)
            if isinstance(data, list):
                rules = [x for x in data if isinstance(x, dict)]
                logger.info("[welcome-debug] rules(from repaired json)=%s", rules)
                return rules
        except Exception as e:
            logger.warning("[welcome-debug] repaired json parse failed: %s", e)

        return []

    def _find_rule(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = str(group_id)
        for rule in self._get_rules():
            if str(rule.get("group_id", "")).strip() == gid:
                logger.info("[welcome-debug] matched rule for group_id=%s => %s", gid, rule)
                return rule
        logger.info("[welcome-debug] no rule for group_id=%s", gid)
        return None

    def _render_text(self, template: str, group_id: str, user_id: str) -> str:
        user_name = user_id or "新朋友"
        text = template or "欢迎 {user_name} 加入本群~"
        rendered = (
            text.replace("{group_id}", str(group_id or ""))
            .replace("{user_id}", str(user_id or ""))
            .replace("{user_name}", str(user_name))
            .replace("{nickname}", str(user_name))
        )
        logger.info("[welcome-debug] rendered text=%r", rendered)
        return rendered

    def _normalize_image_path(self, image_url: str) -> str:
        image_url = str(image_url or "").strip()
        if not image_url:
            return ""

        if image_url.startswith("http://") or image_url.startswith("https://"):
            logger.info("[welcome-debug] using remote image=%s", image_url)
            return image_url

        if os.path.isabs(image_url):
            logger.info("[welcome-debug] using abs image path=%s", image_url)
            return image_url

        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        final_path = os.path.abspath(os.path.join(plugin_dir, image_url))
        logger.info("[welcome-debug] image relative path=%s => final=%s exists=%s", image_url, final_path, os.path.exists(final_path))
        return final_path

    @high_priority_event(filter.EventMessageType.ALL)
    async def handle_group_increase(
        self, event: AiocqhttpMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        try:
            logger.info("[welcome-debug] handle_group_increase triggered, event type=%s", type(event))

            if not self._is_enabled():
                logger.info("[welcome-debug] plugin disabled, skip")
                return

            if not hasattr(event, "message_obj") or not hasattr(event.message_obj, "raw_message"):
                logger.info("[welcome-debug] no message_obj.raw_message")
                return

            raw_message = event.message_obj.raw_message
            logger.info("[welcome-debug] raw_message=%s", raw_message)

            if not raw_message or not isinstance(raw_message, dict):
                logger.info("[welcome-debug] raw_message invalid")
                return

            if not (
                raw_message.get("post_type") == "notice"
                and raw_message.get("notice_type") == "group_increase"
            ):
                logger.info("[welcome-debug] not group_increase notice")
                return

            logger.info("[welcome-debug] group_increase detected!")

            group_id = str(raw_message.get("group_id", "") or "")
            user_id = str(raw_message.get("user_id", "") or "")
            logger.info("[welcome-debug] group_id=%s user_id=%s", group_id, user_id)

            if not group_id or not user_id:
                logger.info("[welcome-debug] missing group_id or user_id")
                return

            rule = self._find_rule(group_id)
            if not rule:
                logger.info("[welcome-debug] no rule matched")
                return

            welcome_text = self._render_text(
                str(rule.get("welcome_text", "") or ""),
                group_id,
                user_id
            )
            image_url = str(rule.get("image_url", "") or "").strip()

            chain = []

            if image_url:
                final_image = self._normalize_image_path(image_url)
                if final_image.startswith("http://") or final_image.startswith("https://"):
                    chain.append(Comp.Image.fromURL(final_image))
                else:
                    chain.append(Comp.Image.fromFileSystem(final_image))

            chain.append(Comp.Plain(welcome_text))

            logger.info("[welcome-debug] about to yield welcome chain, len=%s", len(chain))
            yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"[welcome-debug] 处理入群欢迎事件出错: {e}")

    @filter.command("welcome_show")
    async def welcome_show(
        self, event: AiocqhttpMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        group_id = str(event.get_group_id() or "")
        logger.info("[welcome-debug] /welcome_show group_id=%s", group_id)

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
            final_image = self._normalize_image_path(image_url)
            if final_image.startswith("http://") or final_image.startswith("https://"):
                chain.append(Comp.Image.fromURL(final_image))
            else:
                chain.append(Comp.Image.fromFileSystem(final_image))
        chain.append(Comp.Plain(f"[测试欢迎]\n{text}"))
        logger.info("[welcome-debug] /welcome_show test chain len=%s", len(chain))
        yield event.chain_result(chain)