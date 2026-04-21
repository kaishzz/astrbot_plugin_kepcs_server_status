# astrbot_plugin_kepcs_server_status

AstrBot 插件，用于查询 KepCs 服务器列表并返回整理后的状态消息。

当前版本：`v1.3`

## 当前能力

- 提供 `kepcs_status` 指令
- 按当前 `mode` 值分组展示服务器
- 输出地图、人数和加入链接
- 自动隐藏非空闲但可用的服务器
- 汇总总在线人数
- 当接口全部不可用时返回明确错误提示

当前分组对应关系：

- `ze_xl` -> `Training map`
- `ze_pt` -> `Play map`

## 安装

1. 将项目放入 AstrBot 插件目录
2. 启动或重载 AstrBot
3. 在 AstrBot 插件配置界面填写本插件配置

项目已提供 `_conf_schema.json`，AstrBot 会据此生成配置表单。

## 配置

支持的配置项：

- `serverlist_url`
- `api_key`
- `bearer_token`

说明：

- `api_key` 和 `bearer_token` 至少填写一个
- 如果只填写 `api_key`，插件会同时发送 `X-API-Key` 和 `Authorization: Bearer ...`
- 如果只填写 `bearer_token`，插件只发送 Bearer 鉴权头
- 默认接口地址是 `https://kepapi.kaish.cn/api/kepcs/serverlist`

## 使用

在聊天中发送：

```text
kepcs_status
```

## 输出规则

- 空闲且可用的服务器会显示地图、人数和加入链接
- 不可用服务器会显示状态和错误信息
- 非空闲服务器默认隐藏
- 底部始终显示总在线人数

## 稳定性设计

- 上游响应体大小限制
- 服务器数量上限限制
- 字段 Markdown 转义与长度截断
- 主机和端口基础校验
- 短时缓存、失败退避和并发收敛

## 测试

```bash
py -m unittest discover -s tests
```
