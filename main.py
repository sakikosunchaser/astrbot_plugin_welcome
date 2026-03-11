import json
import os
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
    "v2.1.1",
)
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        logger.info("[welcome] plugin __init__ loaded")

    async def initialize(self):
        logger.info("[welcome] plugin initialized")

    async def terminate(self):
        logger.info("[welcome] plugin terminated")

    # =========================================================
    # 配置
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
        except Exception as e:
            logger.error(f"[welcome] multiline repair failed: {e}")
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

    async def _get_user_display_name(
        self, event: AiocqhttpMessageEvent, group_id: str, user_id: str
    ) -> str:
        """
        优先取群名片(card)，其次昵称(nickname)，最后回退到 user_id
        """
        try:
            info = await event.bot.get_group_member_info(
                group_id=int(group_id),
                user_id=int(user_id),
                no_cache=True,
            )
            card = str(info.get("card", "") or "").strip()
            nickname = str(info.get("nickname", "") or "").strip()

            if card:
                return card
            if nickname:
                return nickname
        except Exception as e:
            logger.warning(
                f"[welcome] failed to get group member info, group_id={group_id}, user_id={user_id}, err={e}"
            )

        return str(user_id or "新朋友")

    def _render_text(
        self, template: str, group_id: str, user_id: str, user_name: str
    ) -> str:
        text = template or "欢迎 {user_name} 加入本群~"
        return (
            text.replace("{group_id}", str(group_id or ""))
            .replace("{user_id}", str(user_id or ""))
            .replace("{user_name}", str(user_name or "新朋友"))
            .replace("{nickname}", str(user_name or "新朋友"))
        )

    def _normalize_image_path(self, image_url: str) -> str:
        image_url = str(image_url or "").strip()
        if not image_url:
            return ""

        if image_url.startswith(("http://", "https://")):
            return image_url

        if os.path.isabs(image_url):
            return image_url

        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.abspath(os.path.join(plugin_dir, image_url))

    def _build_chain(self, text: str, image_url: str = "", at_user_id: str = "") -> list:
        chain = []

        if image_url:
            final_image = self._normalize_image_path(image_url)
            if final_image.startswith(("http://", "https://")):
                chain.append(Comp.Image.fromURL(final_image))
            else:
                chain.append(Comp.Image.fromFileSystem(final_image))

        if at_user_id:
            chain.append(Comp.At(qq=int(at_user_id)))

        if text:
            # 如果前面有 @，这里前面补个换行更自然
            final_text = text
            if at_user_id:
                final_text = "\n" + final_text
            chain.append(Comp.Plain(text=final_text))

        return chain

    # =========================================================
    # 入群欢迎事件
    # =========================================================
    @high_priority_event(filter.EventMessageType.ALL)
    async def handle_group_increase(
        self, event: AiocqhttpMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        try:
            if not self._is_enabled():
                return

            if not hasattr(event, "message_obj") or not hasattr(
                event.message_obj, "raw_message"
            ):
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

                user_name = await self._get_user_display_name(event, group_id, user_id)

                welcome_text = self._render_text(
                    str(rule.get("welcome_text", "") or ""),
                    group_id,
                    user_id,
                    user_name,
                )
                image_url = str(rule.get("image_url", "") or "").strip()

                chain = self._build_chain(
                    text=welcome_text,
                    image_url=image_url,
                    at_user_id=user_id,
                )

                if chain:
                    yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"[welcome] handle_group_increase error: {e}")

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

        test_user_id = "10000"
        user_name = await self._get_user_display_name(event, group_id, test_user_id)

        welcome_text = self._render_text(
            str(rule.get("welcome_text", "") or ""),
            group_id,
            test_user_id,
            user_name,
        )
        image_url = str(rule.get("image_url", "") or "").strip()

        yield event.plain_result(
            f"当前群欢迎配置：group_id={rule.get('group_id', '')}, "
            f"welcome_text={rule.get('welcome_text', '')}, "
            f"image_url={image_url}"
        )

        chain = self._build_chain(
            text=f"[测试欢迎]\n{welcome_text}",
            image_url=image_url,
            at_user_id=test_user_id,
        )
        if chain:
            yield event.chain_result(chain)