# 记录样式

以下为当前业务文件中的实际记录，字段口径见 `data-contract.md`；字段标识保持业务接口写法。

### `tickets`

字段：`case_id`、`created_at`、`product_line`、`text`、`ticket_id`。

```json
{
  "ticket_id": "t000",
  "case_id": "case0",
  "product_line": "服饰",
  "text": "描述不符相关售后记录 0",
  "created_at": 1
}
```

### `votes`

字段：`known_at`、`label`、`source`、`ticket_id`、`version`。

```json
{
  "ticket_id": "t000",
  "source": "s0",
  "version": "v1",
  "label": null,
  "known_at": 1
}
```

### `sources`

字段：`family`、`scope`、`source`、`version`。

```json
{
  "source": "s0",
  "family": "keyword",
  "version": "v1",
  "scope": [
    "家居",
    "服饰"
  ]
}
```

### `gold`

字段：`label`、`reviewed_at`、`ticket_id`。

```json
{
  "ticket_id": "t000",
  "label": "描述不符",
  "reviewed_at": 2
}
```
