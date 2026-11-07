from fastapi import FastAPI
from .quote import router as quote_router  # 导入新添加的报价接口路由

app = FastAPI()

# 将新添加的报价接口路由包含到主应用中
app.include_router(quote_router)