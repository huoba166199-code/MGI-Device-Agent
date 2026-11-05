FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 配置国内 pip 镜像源，极速构建
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 先拷贝依赖文件并安装（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目所有代码
COPY . .

# 暴露端口 (我们之前使用的 8503)
EXPOSE 8502

# 启动命令，绑定到 0.0.0.0 确保外部可访问
CMD ["streamlit", "run", "app.py", "--server.port=8502", "--server.address=0.0.0.0"]
