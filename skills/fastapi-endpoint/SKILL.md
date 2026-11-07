---
name: fastapi-endpoint
description: >
  当任务涉及在订单服务中新增或修改 FastAPI 接口时必须使用本规范，
  包括新增路由、请求模型、响应模型或错误处理。进行代码修改前必须先阅读本规范。
---

# FastAPI 接口编码规范

## 路由
- 用 APIRouter 按资源分模块，前缀清晰（/orders、/users）。
- 路径用名词复数；动作交给 HTTP 方法表达，不在 URL 里写动词。

## 请求 / 响应模型
- 入参与出参一律用 Pydantic 模型，禁止裸 dict。
- 用 response_model= 显式声明响应模型，避免泄露内部字段。

## 错误处理
- 业务错误抛 HTTPException，带明确 status_code 与简短 detail。
- 不把内部异常信息直接透给客户端。