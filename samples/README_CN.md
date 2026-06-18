# Samples 使用说明

[English](./README.md) | 简体中文

本目录包含可直接运行的本地 HTTP API 客户端示例，对应 GameAssistantToolServer 的各项能力。

## 目录说明

- `knowledge/`：Knowledge 服务示例（文本知识插入 / 构建 / 查询）。
- `memory/`：Memory 服务示例（结构化记录 + 图片插入 / 构建 / 检索）。
- `mmr/`：MMR 服务示例（多模态文本/图片插入与检索）。
- `vision/`：Vision 服务示例（场景图片插入 / 构建 / 查询）。
- `requirements.txt`：示例脚本依赖。

## 前置条件

1. 先启动 GameAssistantToolServer（默认地址：`127.0.0.1:9190`）。
2. 按项目根目录 README 完成模型准备。
3. 建议使用 Python 3.10 及以上版本。

## 安装示例依赖

在本目录执行：

```bat
cd samples
pip install -r requirements.txt
```

`requirements.txt` 中包含：

- `rich`
- `requests-toolbelt`
- `pillow`

## 运行示例

建议从 `samples` 目录开始执行。

### 1) Knowledge 示例

```bat
cd knowledge
python run_knowledge_sample.py
```

流程说明：

1. 使用 `sample_texts/sample_1.txt` 与 `sample_texts/sample_2.txt`。
2. 初始化一个 knowledge 实例。
3. 插入文本并构建索引。
4. 执行两次查询。
5. 删除实例并清理。

### 2) Memory 示例

```bat
cd memory
python run_memory_sample.py
```

流程说明：

1. 在 `memory/sample_images` 下生成演示图片。
2. 初始化一个 memory 实例。
3. 插入包含 properties/tags/images 的记录。
4. 构建索引。
5. 执行条件检索、文本检索、图片检索。
6. 校验图片检索 top-1 结果并清理实例。

### 3) MMR 示例

```bat
cd mmr
python run_mmr_sample.py
```

流程说明：

1. 在 `mmr/sample_images` 下生成演示图片。
2. 检查 MMR enable 状态。
3. 初始化一个 MMR 实例。
4. 插入纯文本、纯图片、文本+图片三类记录。
5. 构建索引。
6. 分别执行文本查询与图片查询。
7. 列出记录并清理实例。

### 4) Vision 示例

```bat
cd vision
python run_vision_sample.py
```

流程说明：

1. 在 `vision/sample_images` 下生成演示图片。
2. 初始化 vision 实例并插入场景图片。
3. 构建索引。
4. 使用同一批图片发起查询。
5. 校验 top-1 picture_id 是否符合预期。
6. 删除实例并清理。

## Host 与端口

所有示例默认使用：

- `HOST = "127.0.0.1:9190"`

如果服务部署在其他地址，请修改以下文件中的 HOST：

- `knowledge/knowledge_api.py`
- `memory/memory_api.py`
- `mmr/mmr_api.py`
- `vision/vision_api.py`

## 预期输出

示例正常执行时通常会看到：

- API 返回 `"code": "ok"`
- 构建/查询阶段的进度输出
- 最终 cleanup 请求成功

## 常见问题

- 连接失败：确认服务已启动，且 HOST/端口可访问。
- 构建/查询失败：检查服务日志、模型与配置是否就绪。
- 缺少依赖：重新执行 `pip install -r requirements.txt`。
- 路径或权限问题：请在对应示例目录运行脚本，确保相对路径正确。
