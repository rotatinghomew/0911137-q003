# 本地接口

- `GET /api/catalog`：资料名称、可选业务范围、业务时点范围、表计数与资料指纹。
- `GET /api/view`：当前摘要，可选 `cutoff` 整数和 `group` 业务范围；未知筛选项返回 400。
- `GET /api/source?table=tickets`：按实际资料表名称查询原始记录；不存在的表返回 404。
- `POST /api/releases`：JSON 对象包含 `name` 与 `options`，按当前筛选训练并做分组交叉验证，保存为未发布版本，成功返回 201。复核样本覆盖的售后事件不足两个时返回 400。
- `GET /api/releases`：版本目录，含分类集合、候选方案与发布状态。
- `GET /api/releases/{id}`：返回保存的完整版本，含绑定模型与验证报告，不重新计算。
- `POST /api/releases/{id}/publish`：JSON 对象包含 `scheme`，把该版本以指定候选方案发布；同时只有一个发布版本，旧版本保留但不改写。
- `GET /api/suggestions`：按当前发布版本为未复核工单生成建议，可选 `cutoff` 和 `group`；首次生成的解释随工单保存并原样返回。未发布版本时返回 400。
- `POST /api/analyses`：JSON 对象包含 `title` 与 `options`，重新计算并保存，成功返回 201。`options` 与当前摘要的筛选结构相同。
- `GET /api/analyses`：只返回版本目录及资料指纹。
- `GET /api/analyses/{id}`：返回保存的完整结果，不重新计算。

API 的 `rows` 是领域行，`summary` 是当前汇总，`notes` 是业务口径提示，`options` 是实际采用的筛选值。无记录使用空列表，不能把无观测偷偷表示为有效的零值。错误 JSON 的 `error` 可直接在页面反馈。

这是本地单用户应用，不包含认证与外网部署设置。默认只监听回环地址，容器中可显式监听所有接口，但宿主机端口建议只绑定回环地址。
