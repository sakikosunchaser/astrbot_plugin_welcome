import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter
from astrbot.core import AstrBotConfig

# 默认配置（只在外部未设定时使用）
DEFAULT_WELCOME_CONFIG = {
    "1044962036": {
        "text": (
            "欢迎老师来到安安生日会游客群！\n"
            "请老师先阅读群公告，有问题请私信群管理。\n"
            "北京夏目安安生日会即将开启！请老师敬请期待，也祝老师在群里玩得愉快！"
        ),
        "image": "data/welcome.jpg"
    }
}

@register(
    "astrbot_plugin_welcome_multi_configurable",
    "多群动态欢迎插件",
    "多群支持，欢迎内容支持热修改或外部配置，不用改代码",
    "v2.1",
)
class WelcomeMultiGroupConfigurablePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        # 动态读取配置，否则用默认
        self._refresh_config()

    def _refresh_config(self):
        # 读取外部传入 welcome_config 配置，否则用默认
        self.welcome_config = self.config.get("welcome_config", DEFAULT_WELCOME_CONFIG)

    async def reload_config(self):
        """可选：如果支持配置热重载，这里可以加刷新逻辑"""
        self._refresh_config()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_group_increase(self, event):
        """读取最新 config 并发送对应欢迎消息"""
        try:
            # 每次事件都重新读取配置（确保动态生效）
            self._refresh_config()
            raw = getattr(event.message_obj, "raw_message", {})
            if (
                raw.get("post_type") == "notice"
                and raw.get("notice_type") == "group_increase"
            ):
                group_id = str(raw.get("group_id", ""))
                user_id = int(raw.get("user_id", 0))

                # 查找当前群欢迎配置
                group_cfg = self.welcome_config.get(group_id)
                if not group_cfg:
                    return

                welcome_text = group_cfg.get("text", "")
                welcome_img = group_cfg.get("image", "")

                msg_chain = [Comp.At(qq=user_id)]
                if welcome_text.strip():
                    msg_chain.append(Comp.Plain(text=welcome_text))
                if welcome_img.strip():
                    msg_chain.append(Comp.Image(file=f"file:///{welcome_img}"))
                yield event.chain_result(msg_chain)
        except Exception as e:
            logger.error(f"动态配置多群欢迎插件出错: {e}")
