---
name: unit-test
description: >
  当新增或修改订单服务业务代码并需要配套测试时使用本规范。
  订单服务的业务代码变更必须配套 pytest 测试；决定新增测试后，先阅读本规范，再编写测试。
---

# 单元测试编写规范

## 框架与结构
- 用 pytest；测试文件命名 test_<module>.py，放在 tests/ 下。
- 一个测试只验证一件事，采用 Arrange-Act-Assert 三段式。

## 命名
- 测试函数名描述场景，如 test_calc_order_total_with_multiple_items。

## 覆盖要点
- 正常路径 + 边界（空列表、qty=0）+ 异常输入。
- 用 pytest.raises 验证错误路径。