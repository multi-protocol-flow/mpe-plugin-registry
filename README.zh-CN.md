# mpe-plugin-registry

MPE 的静态插件市场 registry —— 由 GitHub Pages 托管的 `plugins` JSON 文件，
实现宿主市场契约（[`docs/plugin-marketplace.md`](https://github.com/multi-protocol-flow/multi-protocol-flow-executor/blob/main/docs/plugin-marketplace.md)）。

## 工作原理

宿主的 `mpe plugin install` 调用 `GET {base}/plugins` 并解析
`{"plugins": [...]}`。GitHub Pages 把仓库根的 `plugins` 文件映射到该 URL：

```
https://multi-protocol-flow.github.io/mpe-plugin-registry/plugins
```

每个插件条目的 `platforms.<os-arch>.url` 指向对应插件仓库的 release 资产
（zip），`sha256` 取自 release 的 `.sha256` 文件，供宿主安装时校验。

## 安装插件

```bash
# 插件目录解析：MPE_PLUGIN_DIR > config.toml [storage].plugins_dir
# > 数据目录 plugins > ./plugins（见 `mpe plugin dir`）
mpe plugin install redis --registry https://multi-protocol-flow.github.io/mpe-plugin-registry

# 或用环境变量
export MPE_PLUGIN_REGISTRY=https://multi-protocol-flow.github.io/mpe-plugin-registry
mpe plugin install redis

# 验证
mpe plugin list
mpe run-node '{"type":"redis:connect","host":"127.0.0.1","port":6379}'
```

## 新增插件或版本

1. 在 `plugins` 中追加/更新条目（同名多版本按版本降序排列——客户端取第一个匹配）。
2. `platforms` key 为 `<os>-<arch>`：`windows-x64 | windows-arm64 |
   linux-x64 | linux-arm64 | macos-x64 | macos-arm64`。
3. `url` 必须是 zip 的绝对 URL（如 GitHub release 资产），`sha256` 为 zip
   字节的十六进制摘要（必填，宿主强制校验），`size` 为字节大小（仅展示）。
4. 提交并推送；GitHub Pages 自动发布更新。
