# astrbot_plugin_kepcs_server_status

AstrBot 插件，用于查询 KepCS 服务端列表并在聊天中返回整理后的状态信息。

当前版本：`v1.0`

## 功能说明

- 通过 `status` 指令查询服务端状态
- 按 `Practice map`、`Play map` 分组展示
- 显示地图、人数和加入链接
- 自动隐藏非空闲且仍可用的繁忙服务器
- 统计总在线人数
- 当接口全部不可用或服务器全部繁忙时返回明确提示

## 安装

1. 将项目放入 AstrBot 插件目录。
2. 启动或重载 AstrBot，确保插件被正确加载。
3. 在 AstrBot 的插件配置界面中填写本插件配置项。项目已提供 `_conf_schema.json`，AstrBot 会据此生成配置表单。

## 配置

推荐通过 AstrBot 插件配置填写以下项目：

| 配置项 | 说明 |
| --- | --- |
| `api_key` | 必填，用于请求头 `X-API-Key` |
| `bearer_token` | 可选，用于请求头 `Authorization: Bearer ...`；留空时会复用 `api_key` |
| `serverlist_url` | 可选，用于覆盖默认接口地址，默认值为 `https://kepapi.kaish.cn/api/kepcs/serverlist` |

说明：

- 本插件不再依赖 `.env` 文件读取敏感信息。
- 请在 AstrBot 的插件配置中填写真实密钥，不要把敏感信息提交到仓库。
- 如果 `bearer_token` 留空，插件会自动使用 `api_key` 作为 Bearer Token。

## 使用方式

在聊天中发送：

```text
status
```

## 输出规则

- 在线且空闲的服务端会显示地图、人数和加入链接
- 不可用服务端会显示状态和错误信息
- 非空闲服务端默认隐藏，并在底部显示 `Non idle server hidden`
- 底部始终显示总在线人数

## 安全与稳定性

- 限制上游响应体大小，避免异常大包拖垮机器人
- 限制服务端数量，避免异常数据导致消息过长
- 对名称、地图、状态和错误信息做 Markdown 转义与长度截断
- 对主机和端口做基础校验，避免异常值直接进入加入链接
- 内置短时缓存、失败退避与并发收敛，降低重复请求压力

## 测试

```bash
py -m unittest discover -s tests
```

## 项目信息

- 插件名称：`astrbot_plugin_kepcs_server_status`
- 展示名称：`查询 KepCs 服务端信息`
- 作者：`kaish`
- 仓库地址：[kaishzz/astrbot_plugin_kepcs_server_status](https://github.com/kaishzz/astrbot_plugin_kepcs_server_status)
