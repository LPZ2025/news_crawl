# 配置文件说明

## 配置文件位置
`stock_article_generator/utils/config.yaml`

## 配置格式

### 1. NewsNow 平台（标准格式）

只需要 `id` 和 `name`，程序会自动使用 newsnow API：

```yaml
platforms:
  - id: "zhihu"
    name: "知乎"
  - id: "weibo"
    name: "微博"
```

### 2. 自定义 API 平台

需要 `id`、`name` 和 `api_url`，程序会调用你指定的 API：

```yaml
platforms:
  - id: "36kr"
    name: "36氪"
    api_url: "https://v2.xxapi.cn/api/hot36kr"
```

