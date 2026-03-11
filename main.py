import os
import re
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


@register(PLUGIN_NAME, "Sunchser", "一个简单的入群欢迎插件", "1.4.0")
class WelcomePlugin(Star):
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        logger.info("[welcome] plugin loaded")

    # =========================================================
    # 配置读取
    # =========================================================
    def _get_plugin_root(self) -> str:
        return os.path.dirname(os.path.abspath(__file__))

    def _get_config_file_candidates(self) -> List[str]:
        plugin_root = self._get_plugin_root()
        return [
            os.path.abspath(os.path.join(plugin_root, "..", "..", "config", f"{PLUGIN_NAME}_config.json")),
            os.path.abspath(os.path.join(plugin_root, "..", "..", "..", "config", f"{PLUGIN_NAME}_config.json")),
            os.path.abspath(os.path.join(os.getcwd(), "data", "config", f"{PLUGIN_NAME}_config.json")),
            os.path.abspath(os.path.join(os.getcwd(), "config", f"{PLUGIN_NAME}_config.json")),
        ]

    def _load_config_from_file(self) -> Dict[str, Any]:
        for path in self._get_config_file_candidates():
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        logger.info("[welcome] config loaded from file: %s", path)
                        return data
                except Exception as e:
                    logger.warning("[welcome] failed to read config file %s: %s", path, e)
        return {}

    def _load_config_from_context(self) -> Dict[str, Any]:
        cfg = _safe_get(self.context, "plugin_config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                logger.info("[welcome] config loaded from context.plugin_config")
                return cfg
            sub = cfg.get(PLUGIN_NAME)
            if isinstance(sub, dict):
                logger.info("[welcome] config loaded from context.plugin_config.%s", PLUGIN_NAME)
                return sub

        cfg = _safe_get(self.context, "data", "plugin_config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                logger.info("[welcome] config loaded from context.data.plugin_config")
                return cfg
            sub = cfg.get(PLUGIN_NAME)
            if isinstance(sub, dict):
                logger.info("[welcome] config loaded from context.data.plugin_config.%s", PLUGIN_NAME)
                return sub

        cfg = _safe_get(self.context, "config", default=None)
        if isinstance(cfg, dict):
            if "welcome_config_json" in cfg or "enabled" in cfg:
                logger.info("[welcome] config loaded from context.config")
                return cfg
            sub = cfg.get(PLUGIN_NAME)
            if isinstance(sub, dict):
                logger.info("[welcome] config loaded from context.config.%s", PLUGIN_NAME)
                return sub

        return {}

    def _refresh_config(self):
        if isinstance(self.config, dict) and self.config:
            return

        cfg = self._load_config_from_context()
        if cfg:
            self.config = cfg
            return

        cfg = self._load_config_from_file()
        if cfg:
            self.config = cfg
            return

        self.config = {}

    def _is_enabled(self) -> bool:
        self._refresh_config()
        return bool(self.config.get("enabled", True))

    # =========================================================
    # welcome_config_json 容错解析
    # =========================================================
    def _try_parse_rules_json(self, raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]

        if not isinstance(raw, str):
            return []

        raw = raw.strip()
        if not raw:
            return []

        # 1. 先按标准 JSON 解析
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception as e:
            logger.warning("[welcome] standard json parse failed: %s", e)

        # 2. 尝试修复 welcome_text 中的真实换行
        fixed = self._repair_multiline_welcome_text_json(raw)
        if fixed != raw:
            try:
                data = json.loads(fixed)
                if isinstance(data, list):
                    logger.info("[welcome] multiline welcome_text auto repaired successfully")
                    return [x for x in data if isinstance(x, dict)]
            except Exception as e:
                logger.warning("[welcome] repaired json parse failed: %s", e)

        return []

    def _repair_multiline_welcome_text_json(self, raw: str) -> str:
        """
        容错场景：
        用户在 welcome_text 对应的字符串里直接敲了真实换行，导致 JSON 非法。
        本函数尝试把：
            "welcome_text": "第一行
            第二行
            第三行",
        修成：
            "welcome_text": "第一行\n第二行\n第三行",
        """
        pattern = r'("welcome_text"\s*:\s*")([\s\S]*?)(")(\s*,\s*"image_url"\s*:)'

        def repl(match):
            prefix = match.group(1)
            content = match.group(2)
            quote = match.group(3)
            suffix = match.group(4)

            # 先保护已经存在的转义
            content = content.replace("\\", "\\\\")
            content = content.replace('"', '\\"')
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            content = content.replace("\n", "\\n")

            return f"{prefix}{content}{quote}{suffix}"

        try:
            repaired = re.sub(pattern, repl, raw, flags=re.MULTILINE)
            return repaired
        except Exception as e:
            logger.warning("[welcome] repair multiline json failed: %s", e)
            return raw

    def _get_rules(self) -> List[Dict[str, Any]]:
        self._refresh_config()
        raw = self.config.get("welcome_config_json", "[]")
        rules = self._try_parse_rules_json(raw)
        logger.info("[welcome] loaded rules count=%s", len(rules))
        return rules

    def _find_rule(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = str(group_id)
        for rule in self._get_rules():
            if str(rule.get("group_id", "")).strip() == gid:
                return rule
        return None

    # =========================================================
    # NapCat 事件解析
    # =========================================================
    def _get_raw_event(self, event: Any) -> Dict[str, Any]:
        raw = _safe_get(event, "message_obj", "raw_message", default=None)
        if isinstance(raw, dict):
            return raw

        raw = _safe_get(event, "raw_message", default=None)
        if isinstance(raw, dict):
            return raw

        possible = {}
        for key in ["post_type", "notice_type", "sub_type", "group_id", "user_id", "operator_id"]:
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
    # 文本渲染
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

    # =========================================================
    # 图片处理
    # =========================================================
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

    # =========================================================
    # 发消息
    # =========================================================
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
            logger.warning("[welcome] context.bot is None")
            return False

        for method_name in ("send_group_msg", "send_group_message", "send_message"):
            method = getattr(bot, method_name, None)
            if callable(method):
                try:
                    result = method(group_id=group_id, message=message)
                    if hasattr(result, "__await__"):
                        await result
                    logger.info("[welcome] send success via %s", method_name)
                    return True
                except TypeError:
                    try:
                        result = method(group_id, message)
                        if hasattr(result, "__await__"):
                            await result
                        logger.info("[welcome] send success via %s(positional)", method_name)
                        return True
                    except Exception as e:
                        logger.warning("[welcome] %s positional failed: %s", method_name, e)
                except Exception as e:
                    logger.warning("[welcome] %s failed: %s", method_name, e)

        return False

    async def _send_welcome(self, group_id: str, text: str, image: str = ""):
        image = self._normalize_image(image)

        # 1. 结构化消息段
        segs = []
        if image:
            segs.append({"type": "image", "data": {"file": image}})
        if text:
            segs.append({"type": "text", "data": {"text": text}})

        if segs and await self._send_group_message(group_id, segs):
            return

        # 2. CQ 码回退
        cq_msg = self._build_cq_message(text=text, image=image)
        if cq_msg and await self._send_group_message(group_id, cq_msg):
            return

        # 3. 纯文本回退
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

        raw = self._get_raw_event(event)
        logger.info("[welcome] raw event snapshot: %s", raw)

        if not self._is_group_increase(event):
            return

        logger.info("[welcome] group_increase detected")

        group_id = str(raw.get("group_id", "") or "")
        user_id = str(raw.get("user_id", "") or "")

        if not group_id or not user_id:
            logger.warning("[welcome] missing group_id or user_id")
            return

        rule = self._find_rule(group_id)
        logger.info("[welcome] matched rule: %s", rule)

        if not rule:
            return

        text = self._render_text(
            str(rule.get("welcome_text", "") or ""),
            group_id,
            user_id
        )
        image = str(rule.get("image_url", "") or "").strip()

        logger.info("[welcome] sending welcome, group_id=%s user_id=%s image=%s", group_id, user_id, image)
        await self._send_welcome(group_id=group_id, text=text, image=image)

    # =========================================================
    # 监听
    # =========================================================
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_event(self, event: AstrMessageEvent):
        try:
            await self._handle_welcome(event)
        except Exception as e:
            logger.exception("[welcome] handle event failed: %s", e)

    # =========================================================
    # 调试命令
    # =========================================================
    @filter.command("welcome_ping")
    async def welcome_ping(self, event: AstrMessageEvent):
        yield event.plain_result("welcome plugin alive")

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

        text = self._render_text(
            str(rule.get("welcome_text", "") or ""),
            group_id,
            "10000"
        )
        image = str(rule.get("image_url", "") or "").strip()

        try:
            await self._send_welcome(
                group_id=group_id,
                text=f"[测试欢迎]\n{text}",
                image=image
            )
            yield event.plain_result("测试欢迎消息已发送，请查看群内。")
        except Exception as e:
            yield event.plain_result(f"测试发送失败：{e}")