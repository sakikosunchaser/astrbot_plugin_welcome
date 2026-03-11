import os
import json
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


@register("astrbot_plugin_welcome", "Sunchser", "一个简单的入群欢迎插件", "1.3.0")
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        logger.info("[astrbot_plugin_welcome] loaded")

    # =========================================================
    # 配置读取
    # =========================================================
    def _refresh_config(self):
        if self.config:
            return

        cfg = _safe_get(self.context, "plugin_config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                self.config = cfg
                return
            sub = cfg.get("astrbot_plugin_welcome")
            if isinstance(sub, dict):
                self.config = sub
                return

        cfg = _safe_get(self.context, "data", "plugin_config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                self.config = cfg
                return
            sub = cfg.get("astrbot_plugin_welcome")
            if isinstance(sub, dict):
                self.config = sub
                return

    def _is_enabled(self) -> bool:
        self._refresh_config()
        return bool(self.config.get("enabled", True))

    def _get_rules(self) -> List[Dict[str, Any]]:
        self._refresh_config()
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
        except Exception as e:
            logger.warning("[astrbot_plugin_welcome] welcome_config_json parse failed: %s", e)

        return []

    def _find_rule(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = str(group_id)
        for rule in self._get_rules():
            if str(rule.get("group_id", "")).strip() == gid:
                return rule
        return None

    # =========================================================
    # NapCat 事件
    # =========================================================
    def _get_raw_event(self, event: Any) -> Dict[str, Any]:
        raw = _safe_get(event, "message_obj", "raw_message", default=None)
        if isinstance(raw, dict):
            return raw

        raw = _safe_get(event, "raw_message", default=None)
        if isinstance(raw, dict):
            return raw

        possible = {}
        for key in ["post_type", "notice_type", "sub_type", "group_id", "user_id"]:
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

    # =========================================================
    # 文本/图片
    # =========================================================
    def _render_text(self, template: str, group_id: str, user_id: str) -> str:
        user_name = user_id or "新朋友"
        text = template or "欢迎 {user_name} 加入本群~"
        return (
            text.replace("{group_id}", str(group_id or ""))
            .replace("{user_id}", str(user_id or ""))
            .replace("{user_name}", str(user_name))
            .replace("{nickname}", str(user_name))
        )

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

    def _build_cq_message(self, text: str, image: str = "") -> str:
        parts = []
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
                    except Exception:
                        pass
                except Exception:
                    pass
        return False

    async def _send_welcome(self, group_id: str, text: str, image: str = ""):
        image = self._normalize_image(image)

        segs = []
        if image:
            segs.append({"type": "image", "data": {"file": image}})
        if text:
            segs.append({"type": "text", "data": {"text": text}})

        if segs and await self._send_group_message(group_id, segs):
            return

        cq_msg = self._build_cq_message(text=text, image=image)
        if cq_msg and await self._send_group_message(group_id, cq_msg):
            return

        fallback = text
        if image:
            fallback = f"{text}\n[图片] {image}" if text else f"[图片] {image}"

        if await self._send_group_message(group_id, fallback):
            return

        raise RuntimeError("failed to send welcome message")

    # =========================================================
    # 核心逻辑
    # =========================================================
    async def _handle_welcome(self, event: Any):
        if not self._is_enabled():
            return
        if not self._is_group_increase(event):
            return

        raw = self._get_raw_event(event)
        group_id = str(raw.get("group_id", "") or "")
        user_id = str(raw.get("user_id", "") or "")

        if not group_id or not user_id:
            return

        rule = self._find_rule(group_id)
        if not rule:
            return

        text = self._render_text(str(rule.get("welcome_text", "") or ""), group_id, user_id)
        image = str(rule.get("image_url", "") or "").strip()

        await self._send_welcome(group_id=group_id, text=text, image=image)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_event(self, event: AstrMessageEvent):
        try:
            await self._handle_welcome(event)
        except Exception as e:
            logger.exception("[astrbot_plugin_welcome] handle event failed: %s", e)

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

        yield event.plain_result(
            f"当前群欢迎配置：group_id={rule.get('group_id', '')}, "
            f"welcome_text={rule.get('welcome_text', '')}, "
            f"image_url={rule.get('image_url', '')}"
        )