# astrbot_plugin_welcome

一个适用于 **AstrBot 4.19.4 + NapCat** 的入群欢迎插件。

- 插件目录名：`astrbot_plugin_welcome`
- 插件中文名称：入群欢迎
- 作者：Sunchser
- 简介：一个简单的入群欢迎插件

## 功能特性

- 支持新群员入群欢迎
- 支持多群分别配置欢迎规则
- 支持不同群设置不同欢迎文案
- 支持图文混合欢迎消息
- 支持多条欢迎文案随机发送
- 支持多张欢迎图片随机发送
- 支持可选 @ 新成员
- 支持默认欢迎文案与默认图片兜底
- 支持可视化配置界面
- 提供测试命令用于上线前验证

## 适用环境

- AstrBot `4.19.4`
- NapCat
- OneBot v11 适配链路

## 目录结构

```text
astrbot_plugin_welcome/
├── main.py
├── metadata.yaml
├── README.md
└── welcome_conf_schema.json
```

## 重要说明

为了让 AstrBot WebUI 更稳地识别插件可视化配置，请将：

```text
welcome_conf_schema.json
```

再复制一份为：

```text
_conf_schema.json
```

即最终建议目录为：

```text
astrbot_plugin_welcome/
├── main.py
├── metadata.yaml
├── README.md
├── welcome_conf_schema.json
└── _conf_schema.json
```

其中 `_conf_schema.json` 与 `welcome_conf_schema.json` 内容完全相同。

## 安装方式

将插件目录放到 AstrBot 插件目录，例如：

```text
AstrBot/data/plugins/astrbot_plugin_welcome
```

然后重启 AstrBot 或在 WebUI 中重载插件。

## NapCat 兼容说明

本插件已针对 AstrBot + NapCat（OneBot v11）做定向兼容：

- 入群事件基于 `notice_type = group_increase`
- 支持 `sub_type = approve / invite`
- 发送时优先尝试 OneBot 消息段
- 若失败，则回退为 CQ 码
- 最后回退为纯文本

注意：

- NapCat 的 `group_increase` 事件通常只带 `user_id`，不一定直接提供新成员昵称
- 因此本插件默认会用 `user_id` 作为 `{user_name}` 的兜底值
- 在部分邀请场景中，`operator_id` 可能为空或为 `0`，因此不建议把它作为强依赖字段

## 配置方式

进入 AstrBot WebUI 的插件管理页面，打开本插件配置。

### 顶层配置项

- `enabled`：是否启用插件
- `default_image`：默认欢迎图片
- `default_welcome_messages`：默认欢迎文案列表
- `welcome_list`：多群欢迎配置列表

### 单个群配置项

- `enabled`：是否启用该群欢迎
- `group_id`：群号
- `at_new_member`：是否 @ 新成员
- `welcome_text`：单条欢迎文案
- `welcome_messages`：多条欢迎文案，随机发送，优先于 `welcome_text`
- `image_url`：单张欢迎图片
- `image_urls`：多张欢迎图片，随机发送，优先于 `image_url`

## 模板变量

欢迎文案支持以下占位符：

- `{user_name}`：新成员昵称
- `{nickname}`：同 `{user_name}`
- `{user_id}`：新成员 ID
- `{group_id}`：当前群号
- `{operator_id}`：操作者 ID

例如：

```text
欢迎 {user_name} 加入本群！
你的 ID：{user_id}
当前群号：{group_id}
```

## 配置示例

```json
{
  "enabled": true,
  "default_image": "",
  "default_welcome_messages": [
    "欢迎 {user_name} 加入本群~",
    "欢迎新朋友 {user_name}，请先阅读群公告~"
  ],
  "welcome_list": [
    {
      "enabled": true,
      "group_id": "123456789",
      "at_new_member": true,
      "welcome_text": "欢迎 {user_name} 来到 1 群！",
      "welcome_messages": [
        "欢迎 {user_name} 来到 1 群！",
        "{user_name} 欢迎加入，记得先看群公告哦~"
      ],
      "image_url": "https://example.com/welcome1.jpg",
      "image_urls": [
        "https://example.com/welcome1.jpg",
        "https://example.com/welcome2.jpg"
      ]
    },
    {
      "enabled": true,
      "group_id": "987654321",
      "at_new_member": false,
      "welcome_text": "欢迎 {user_name} 加入 2 群~",
      "welcome_messages": [],
      "image_url": "",
      "image_urls": []
    }
  ]
}
```

## 命令

### 测试当前群欢迎配置

```text
/welcome_test
```

作用：

- 在当前群发送一条测试欢迎消息
- 用于确认当前群配置是否生效

### 查看当前群欢迎配置

```text
/welcome_show
```

作用：

- 输出当前群对应的欢迎配置摘要

## 图片说明

支持两种形式：

### 1. 公网 URL

例如：

```text
https://example.com/welcome.jpg
```

### 2. 本地相对路径

例如：

```text
images/welcome.png
```

插件会自动把相对路径解析为相对于插件目录的绝对路径。

## 发送逻辑说明

插件会按以下优先级发送欢迎消息：

1. OneBot 结构化消息段
2. CQ 码消息
3. 纯文本兜底

如果图片发送失败，最终会退化成：

```text
欢迎内容
[图片] 图片地址
```

## 常见问题

### 1. 为什么 `/welcome_test` 可以发，但真实入群没欢迎？

请检查：

- NapCat 是否正常上报 `group_increase`
- AstrBot 是否把该事件透传到了插件层
- 目标群号是否与配置完全一致
- 对应群规则是否启用
- 机器人是否有该群发言权限

### 2. 为什么欢迎里显示的是用户 ID，不是昵称？

因为 NapCat 的入群事件通常不直接给新成员昵称，所以插件使用 `user_id` 作为兜底值。

如果你后续想进一步增强，可以接入额外的获取群成员资料逻辑。

### 3. 为什么图片发不出来？

不同 NapCat / OneBot 环境对图片发送可能有差异：

- 有的环境支持 URL
- 有的更适合本地路径
- 有的环境对路径格式较严格

建议优先测试：

- 公网 URL
- 插件目录下本地相对路径

## License

MIT
