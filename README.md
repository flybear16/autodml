# autodml

**Auto Modeling Definition Language** — 用纯 Python / YAML / 直连数据库三种方式定义、校验、导出语义层模型（`mdl.json`）的 Python 库。

## 为什么

语义层（semantic layer）是 AI 生成 SQL 前的“业务翻译层”：逻辑表、计算列、表关系、指标。本库在纯 Python 生态内完成 MDL 的**生成（反射活库）→ 校验（lint）→ 导出（JSON/YAML）**闭环。

## 安装

```bash
pip install autodml            # 核心（YAML/JSON/校验）
pip install "autodml[db]"      # + SQLAlchemy 反射
pip install "autodml[dev]"     # + pytest
```

## 快速上手

### 1. 纯 Python 定义

```python
from autodml import Manifest, Model, Column, Relationship, Metric

m = (
    Manifest(manifest="shop")
    .add(
        Model(name="customers", refSql="public.customers", columns=[
            Column(name="id", type="integer", isPrimary=True, notNull=True),
            Column(name="name", type="string"),
        ]),
        Model(name="orders", refSql="public.orders", columns=[
            Column(name="id", type="integer", isPrimary=True, notNull=True),
            Column(name="customer_id", type="integer"),
            Column(name="amount", type="decimal"),
        ]),
        Relationship(
            name="orders_customer_fk", relationType="manyToOne",
            left={"modelName": "orders", "columnName": "customer_id"},
            right={"modelName": "customers", "columnName": "id"},
        ),
        Metric(name="total_revenue", baseModel="orders",
               expression="SUM(amount)", type="decimal"),
    )
)

from autodml.validate import validate
print(validate(m))          # OK / 逐条 issue

from autodml.serialize import write_json
write_json(m, "mdl.json")   # camelCase 输出
```

### 2. 从活库反射

```python
from autodml.introspect import reflect

m = reflect(
    "postgresql://user:***@localhost:5432/mydb",
    schema="public",
    include=["orders", "customers", "order_*"],
    exclude=["*_tmp"],
    infer_relationships=True,   # FK -> manyToOne/oneToOne 推断
)
```

### 3. YAML 目录

```text
proj/
  project.yml
  models/customers.yml
  models/orders.yml
  relationships.yml
  metrics.yml
  views/active_customers.yml
```

```yaml
# models/orders.yml
name: orders
refSql: public.orders
columns:
  - name: id
    type: integer
    isPrimary: true
    notNull: true
  - name: customer_id
    type: integer
```

## CLI

```bash
autodml init ./proj                     # 脚手架
autodml validate ./proj                 # lint（error 退出码 1）
autodml export ./proj -o mdl.json       # 导出 mdl.json
autodml export ./proj -o out/ --format yaml-dir
autodml reflect "postgresql://..." --schema public -o mdl.json
```

## MDL 核心概念

| 概念 | 说明 |
|------|------|
| `Model` | 逻辑表：`refSql` 指向物理表，columns + calculations |
| `Column` | 列，`type` 用 MDL 类型（string/integer/decimal/…） |
| `Calculation` | 计算列（expression） |
| `Relationship` | 表关系：oneToOne / oneToMany / manyToOne / manyToMany，左右 side |
| `Metric` | 指标：baseModel + expression（如 `SUM(amount)`） |
| `View` | 查询态视图：statement 是基于模型名的 SQL |

## 校验规则（v0.1）

- 命名（标识符合法性、保留字、`_tmp/_backup` 后缀警告）
- 类型（MDL 类型白名单）
- 重复（model/column/calculation/relationship 重名）
- 引用完整性（relationship 指向的 model/column 存在、metric 的 baseModel 存在、view 语句里的标识符已知）
- 结构（refSql/tableReference 二选一、表达式非空）

error 阻断（`ValidationError`），warning 只提示。

## 设计边界（v0.1）

- 序列化输出 camelCase `mdl.json`；复杂特性（nested struct、enumLabels、view 的 dimensions/measures 高级声明）留到后续版本
- 反射用 SQLAlchemy `inspect`，理论上支持所有 SQLAlchemy 方言（PostgreSQL/MySQL/SQLite/DuckDB…）
- `manyToOne`/`oneToOne` 推断基于 PK 约束；非规范库建议手工在 YAML 里覆盖

## 开发

```bash
git clone … && cd autodml
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q
```

## License

MIT
