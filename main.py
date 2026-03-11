import os
import json
import logging
from typing import Any, Dict, List, Optional

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PLUGIN_NAME = "astrbot_plugin_welcome"


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


@register(PLUGIN_NAME, "Sunchser", "一个简单的入群欢迎插件", "1.3.2")
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        logger.info("[welcome-debug] plugin loaded")

    # =========================================================
    # 配置读取
    # =========================================================
    def _get_plugin_root(self) -> str:
        return os.path.dirname(os.path.abspath(__file__))

    def _get_config_file_candidates(self) -> List[str]:
        """
        优先尝试几个常见配置文件位置
        """
        plugin_root = self._get_plugin_root()

        candidates = [
            os.path.abspath(os.path.join(plugin_root, "..", "..", "config", f"{PLUGIN_NAME}_config.json")),
            os.path.abspath(os.path.join(plugin_root, "..", "..", "..", "config", f"{PLUGIN_NAME}_config.json")),
            os.path.abspath(os.path.join(os.getcwd(), "data", "config", f"{PLUGIN_NAME}_config.json")),
            os.path.abspath(os.path.join(os.getcwd(), "config", f"{PLUGIN_NAME}_config.json")),
        ]
        return candidates

    def _load_config_from_file(self) -> Dict[str, Any]:
        for path in self._get_config_file_candidates():
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        logger.info("[welcome-debug] config loaded from file: %s", path)
                        return data
                except Exception as e:
                    logger.warning("[welcome-debug] failed to read config file %s: %s", path, e)
        return {}

    def _load_config_from_context(self) -> Dict[str, Any]:
        # 方式1：context.plugin_config
        cfg = _safe_get(self.context, "plugin_config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                logger.info("[welcome-debug] config loaded from context.plugin_config")
                return cfg
            sub = cfg.get(PLUGIN_NAME)
            if isinstance(sub, dict):
                logger.info("[welcome-debug] config loaded from context.plugin_config.%s", PLUGIN_NAME)
                return sub

        # 方式2：context.data.plugin_config
        cfg = _safe_get(self.context, "data", "plugin_config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                logger.info("[welcome-debug] config loaded from context.data.plugin_config")
                return cfg
            sub = cfg.get(PLUGIN_NAME)
            if isinstance(sub, dict):
                logger.info("[welcome-debug] config loaded from context.data.plugin_config.%s", PLUGIN_NAME)
                return sub

        # 方式3：context.config
        cfg = _safe_get(self.context, "config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                logger.info("[welcome-debug] config loaded from context.config")
                return cfg
            sub = cfg.get(PLUGIN_NAME)
            if isinstance(sub, dict):
                logger.info("[welcome-debug] config loaded from context.config.%s", PLUGIN_NAME)
                return sub

        return {}

    def _refresh_config(self):
        # 优先已有 config
        if isinstance(self.config, dict) and self.config:
            return

        # 再尝试 context
        cfg = self._load_config_from_context()
        if cfg:
            self.config = cfg
            return

        # 最后直接读配置文件
        cfg = self._load_config_from_file()
        if cfg:
            self.config = cfg
            return

        self.config = {}

    def _is_enabled(self) -> bool:
        self._refresh_config()
        return bool(self.config.get("enabled", True))

    def _get_rules(self) -> List[Dict[str, Any]]:
        self._refresh_config()
        raw = self.config.get("welcome_config_json", "[]")

        logger.info("[welcome-debug] current config = %s", self.config)
        logger.info("[welcome-debug] welcome_config_json raw = %r", raw)

        if isinstance(raw, list):
            rules = [x for x in raw if isinstance(x, dict)]
            logger.info("[welcome-debug] parsed rules from list = %s", rules)
            return rules

        if not isinstance(raw, str):
            logger.warning("[welcome-debug] welcome_config_json is not str/list, got %s", type(raw))
            return []

        raw = raw.strip()
        if not raw:
            return []

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                rules = [x for x in data if isinstance(x, dict)]
                logger.info("[welcome-debug] parsed rules from json = %s", rules)
                return rules
        except Exception as e:
            logger.warning("[welcome-debug] welcome_config_json parse failed: %s", e)

        return []

    def _find_rule(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = str(group_id)
        for rule in self._get_rules():
            if str(rule.get("group_id", "")).strip() == gid:
                return rule
        return None

    # =========================================================
    # 事件
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
            base_dir = self._get_plugin_root()
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
            logger.warning("[welcome-debug] context.bot is None")
            return False

        for method_name in ("send_group_msg", "send_group_message", "send_message"):
            method = getattr(bot, method_name, None)
            if callable(method):
                try:
                    result = method(group_id=group_id, message=message)
                    if hasattr(result, "__await__"):
                        await result
                    logger.info("[welcome-debug] send success via %s", method_name)
                    return True
                except TypeError:
                    try:
                        result = method(group_id, message)
                        if hasattr(result, "__await__"):
                            await result
                        logger.info("[welcome-debug] send success via %s(positional)", method_name)
                        return True
                    except Exception as e:
                        logger.warning("[welcome-debug] %s positional failed: %s", method_name, e)
                except Exception as e:
                    logger.warning("[welcome-debug] %s failed: %s", method_name, e)

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
            logger.info("[welcome-debug] plugin disabled")
            return

        raw = self._get_raw_event(event)
        logger.info("[welcome-debug] raw event snapshot: %s", raw)

        if not self._is_group_increase(event):
            return

        logger.info("[welcome-debug] group_increase detected")

        group_id = str(raw.get("group_id", "") or "")
        user_id = str(raw.get("user_id", "") or "")

        if not group_id or not user_id:
            logger.warning("[welcome-debug] missing group_id or user_id")
            return

        rule = self._find_rule(group_id)
        logger.info("[welcome-debug] matched rule: %s", rule)

        if not rule:
            return

        text = self._render_text(str(rule.get("welcome_text", "") or ""), group_id, user_id)
        image = str(rule.get("image_url", "") or "").strip()

        logger.info("[welcome-debug] sending welcome, group_id=%s user_id=%s image=%s", group_id, user_id, image)
        await self._send_welcome(group_id=group_id, text=text, image=image)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_event(self, event: AstrMessageEvent):
        try:
            await self._handle_welcome(event)
        except Exception as e:
            logger.exception("[welcome-debug] handle event failed: %s", e)

    @filter.command("welcome_show")
    async def welcome_show(self, event: AstrMessageEvent):
        try:
            group_id = str(event.get_group_id() or "")
        except Exception:
            group_id = str(_safe_get(event, "message_obj", "group_id", default="") or "")

        rules = self._get_rules()
        yield event.plain_result(
            f"group_id={group_id}\n"
            f"config={self.config}\n"
            f"rules={rules}"
        )