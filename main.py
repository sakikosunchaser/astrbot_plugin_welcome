import os
import random
import logging
from typing import Any, Dict, List, Optional

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent

logger = logging.getLogger(__name__)


def _safe_get(obj: Any, *keys, default=None):
    cur = obj
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        else:
            cur = getattr(cur, key, default)
    return cur


@register("astrbot_plugin_welcome", "Sunchser", "一个简单的入群欢迎插件", "1.0.1")
class WelcomePlugin(Star):
    """
    AstrBot 4.19.4 + NapCat(OneBot v11) 入群欢迎插件
    功能：
    - 多群分别配置欢迎规则
    - 支持图文混合欢迎
    - 支持多条欢迎文案随机发送
    - 支持多张图片随机发送
    - 支持可选 @ 新成员
    - 支持默认欢迎文案/默认图片兜底
    """

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        logger.info("[astrbot_plugin_welcome] loaded, config keys=%s", list(self.config.keys()))

    # =========================================================
    # 配置读取
    # =========================================================
    def _get_rules(self) -> List[Dict[str, Any]]:
        rules = self.config.get("welcome_list", [])
        if not isinstance(rules, list):
            return []
        return [x for x in rules if isinstance(x, dict)]

    def _get_default_messages(self) -> List[str]:
        msgs = self.config.get("default_welcome_messages", [])
        if not isinstance(msgs, list):
            return ["欢迎 {user_name} 加入本群~"]
        msgs = [str(x).strip() for x in msgs if str(x).strip()]
        return msgs or ["欢迎 {user_name} 加入本群~"]

    def _get_default_image(self) -> str:
        return str(self.config.get("default_image", "") or "").strip()

    def _is_global_enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def _find_rule(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = str(group_id)
        for rule in self._get_rules():
            if str(rule.get("group_id", "")).strip() == gid:
                return rule
        return None

    # =========================================================
    # 模板渲染
    # =========================================================
    def _render_template(
        self,
        template: str,
        *,
        group_id: str,
        user_id: str,
        user_name: str,
        operator_id: str = "",
    ) -> str:
        text = template or "欢迎 {user_name} 加入本群~"
        mapping = {
            "{group_id}": str(group_id or ""),
            "{user_id}": str(user_id or ""),
            "{user_name}": str(user_name or "新朋友"),
            "{nickname}": str(user_name or "新朋友"),
            "{operator_id}": str(operator_id or ""),
        }
        for k, v in mapping.items():
            text = text.replace(k, v)
        return text

    def _pick_message(
        self,
        rule: Dict[str, Any],
        *,
        group_id: str,
        user_id: str,
        user_name: str,
        operator_id: str = "",
    ) -> str:
        # 优先多条随机
        welcome_messages = rule.get("welcome_messages", [])
        if isinstance(welcome_messages, list):
            candidates = [str(x).strip() for x in welcome_messages if str(x).strip()]
            if candidates:
                return self._render_template(
                    random.choice(candidates),
                    group_id=group_id,
                    user_id=user_id,
                    user_name=user_name,
                    operator_id=operator_id,
                )

        # 次选单条
        welcome_text = str(rule.get("welcome_text", "") or "").strip()
        if welcome_text:
            return self._render_template(
                welcome_text,
                group_id=group_id,
                user_id=user_id,
                user_name=user_name,
                operator_id=operator_id,
            )

        # 最后全局默认
        defaults = self._get_default_messages()
        return self._render_template(
            random.choice(defaults),
            group_id=group_id,
            user_id=user_id,
            user_name=user_name,
            operator_id=operator_id,
        )

    def _pick_image(self, rule: Dict[str, Any]) -> str:
        # 优先多图随机
        image_urls = rule.get("image_urls", [])
        if isinstance(image_urls, list):
            candidates = [str(x).strip() for x in image_urls if str(x).strip()]
            if candidates:
                return random.choice(candidates)

        # 次选单图
        image_url = str(rule.get("image_url", "") or "").strip()
        if image_url:
            return image_url

        # 最后全局默认
        return self._get_default_image()

    # =========================================================
    # NapCat / OneBot 事件解析
    # =========================================================
    def _get_raw_event(self, event: Any) -> Dict[str, Any]:
        """
        尽量从 AstrBot 事件对象中拿到 NapCat / OneBot 原始事件
        """
        raw = _safe_get(event, "message_obj", "raw_message", default=None)
        if isinstance(raw, dict):
            return raw

        raw = _safe_get(event, "raw_message", default=None)
        if isinstance(raw, dict):
            return raw

        # 兜底：直接从 event 上拼
        possible = {}
        for key in [
            "post_type",
            "notice_type",
            "sub_type",
            "group_id",
            "user_id",
            "operator_id",
            "self_id",
        ]:
            value = _safe_get(event, key, default=None)
            if value is not None:
                possible[key] = value
        return possible

    def _is_group_increase(self, event: Any) -> bool:
        raw = self._get_raw_event(event)
        return (
            str(raw.get("post_type", "")) == "notice"
            and str(raw.get("notice_type", "")) == "group_increase"
        )

    def _extract_event_info(self, event: Any) -> Dict[str, str]:
        raw = self._get_raw_event(event)

        group_id = str(raw.get("group_id", "") or "")
        user_id = str(raw.get("user_id", "") or "")
        operator_id = str(raw.get("operator_id", "") or "")
        sub_type = str(raw.get("sub_type", "") or "")

        # NapCat 的 group_increase 通常不直接给昵称，这里兜底用 user_id
        user_name = user_id or "新朋友"

        return {
            "group_id": group_id,
            "user_id": user_id,
            "operator_id": operator_id,
            "sub_type": sub_type,
            "user_name": user_name,
        }

    # =========================================================
    # 图片路径处理
    # =========================================================
    def _normalize_image(self, image: str) -> str:
        image = str(image or "").strip()
        if not image:
            return ""

        if image.startswith(("http://", "https://", "base64://", "file://")):
            return image

        if not os.path.isabs(image):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            image = os.path.abspath(os.path.join(base_dir, image))

        return image

    # =========================================================
    # 消息发送
    # =========================================================
    def _build_cq_message(self, text: str, image: str = "", at_user_id: str = "") -> str:
        parts = []

        if at_user_id:
            parts.append(f"[CQ:at,qq={at_user_id}] ")

        if image:
            parts.append(f"[CQ:image,file={image}]")

        if text:
            if image:
                parts.append("\n")
            parts.append(text)

        return "".join(parts).strip()

    async def _send_group_message(self, group_id: str, message: Any) -> bool:
        bot = getattr(self.context, "bot", None)
        if bot is None:
            return False

        # 兼容不同 bot 实现
        for method_name in ("send_group_msg", "send_group_message", "send_message"):
            method = getattr(bot, method_name, None)
            if callable(method):
                try:
                    result = method(group_id=group_id, message=message)
                    if hasattr(result, "__await__"):
                        await result
                    return True
                except TypeError:
                    try:
                        result = method(group_id, message)
                        if hasattr(result, "__await__"):
                            await result
                        return True
                    except Exception as e:
                        logger.warning("[astrbot_plugin_welcome] bot.%s positional failed: %s", method_name, e)
                except Exception as e:
                    logger.warning("[astrbot_plugin_welcome] bot.%s failed: %s", method_name, e)

        return False

    async def _send_welcome(self, group_id: str, text: str, image: str = "", at_user_id: str = ""):
        image = self._normalize_image(image)

        # 1. ��尝试结构化消息段
        segs = []
        if at_user_id:
            segs.append({"type": "at", "data": {"qq": at_user_id}})
        if image:
            segs.append({"type": "image", "data": {"file": image}})
        if text:
            segs.append({"type": "text", "data": {"text": text}})

        if segs and await self._send_group_message(group_id, segs):
            return

        # 2. 尝试 CQ 码
        cq_msg = self._build_cq_message(text=text, image=image, at_user_id=at_user_id)
        if cq_msg and await self._send_group_message(group_id, cq_msg):
            return

        # 3. 纯文本兜底
        fallback = text
        if image:
            fallback = f"{text}\n[图片] {image}" if text else f"[图片] {image}"

        if await self._send_group_message(group_id, fallback):
            return

        raise RuntimeError("failed to send welcome message by all strategies")

    # =========================================================
    # 核心欢迎逻辑
    # =========================================================
    async def _handle_welcome(self, event: Any):
        if not self._is_global_enabled():
            return

        if not self._is_group_increase(event):
            return

        info = self._extract_event_info(event)
        group_id = info["group_id"]
        user_id = info["user_id"]
        operator_id = info["operator_id"]
        user_name = info["user_name"]

        if not group_id or not user_id:
            logger.warning("[astrbot_plugin_welcome] invalid group increase event: %s", info)
            return

        rule = self._find_rule(group_id)
        if not rule:
            logger.debug("[astrbot_plugin_welcome] no welcome rule found for group_id=%s", group_id)
            return

        if not bool(rule.get("enabled", True)):
            logger.debug("[astrbot_plugin_welcome] welcome rule disabled for group_id=%s", group_id)
            return

        text = self._pick_message(
            rule,
            group_id=group_id,
            user_id=user_id,
            user_name=user_name,
            operator_id=operator_id,
        )
        image = self._pick_image(rule)
        at_new_member = bool(rule.get("at_new_member", False))

        logger.info(
            "[astrbot_plugin_welcome] send welcome group_id=%s user_id=%s sub_type=%s operator_id=%s",
            group_id,
            user_id,
            info["sub_type"],
            operator_id,
        )

        await self._send_welcome(
            group_id=group_id,
            text=text,
            image=image,
            at_user_id=user_id if at_new_member else "",
        )

    # =========================================================
    # 监听
    # =========================================================
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_event(self, event: AstrMessageEvent):
        try:
            await self._handle_welcome(event)
        except Exception as e:
            logger.exception("[astrbot_plugin_welcome] handle event failed: %s", e)

    # =========================================================
    # 调试命令
    # =========================================================
    @filter.command("welcome_test")
    async def welcome_test(self, event: AstrMessageEvent):
        try:
            group_id = str(event.get_group_id() or "")
        except Exception:
            group_id = str(_safe_get(event, "message_obj", "group_id", default="") or "")

        if not group_id:
            yield event.plain_result("当前不在群聊中，无法测试。")
            return

        rule = self._find_rule(group_id)
        if not rule:
            yield event.plain_result(f"当前群 {group_id} 未配置欢迎规则。")
            return

        text = self._pick_message(
            rule,
            group_id=group_id,
            user_id="10000",
            user_name="测试用户",
            operator_id="0",
        )
        image = self._pick_image(rule)
        at_new_member = bool(rule.get("at_new_member", False))

        try:
            await self._send_welcome(
                group_id=group_id,
                text=f"[测试欢迎]\n{text}",
                image=image,
                at_user_id="10000" if at_new_member else "",
            )
            yield event.plain_result("测试欢迎消息已发送，请查看群内。")
        except Exception as e:
            yield event.plain_result(f"测试发送失败：{e}")

    @filter.command("welcome_show")
    async def welcome_show(self, event: AstrMessageEvent):
        try:
            group_id = str(event.get_group_id() or "")
        except Exception:
            group_id = str(_safe_get(event, "message_obj", "group_id", default="") or "")

        if not group_id:
            yield event.plain_result("当前不在群聊中。")
            return

        rule = self._find_rule(group_id)
        if not rule:
            yield event.plain_result(f"当前群 {group_id} 未配置欢迎规则。")
            return

        summary = {
            "enabled": rule.get("enabled", True),
            "group_id": rule.get("group_id", ""),
            "at_new_member": rule.get("at_new_member", False),
            "welcome_text": rule.get("welcome_text", ""),
            "welcome_messages": rule.get("welcome_messages", []),
            "image_url": rule.get("image_url", ""),
            "image_urls": rule.get("image_urls", []),
        }
        yield event.plain_result(f"当前群欢迎配置：{summary}")