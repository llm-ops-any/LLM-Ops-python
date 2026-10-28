# 使用Debian 12的Python 3.10版本作为基础镜像
FROM python:3.10-slim-bookworm AS base

# 将requirements.txt拷贝到根目录下
COPY requirements.txt .

# 构建缓存并使用pip安装严格版本的requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/pkg -r requirements.txt

# 二阶段生产环境构建
FROM base AS production

# 设置工作目录
WORKDIR /app/api

# 定义环境变量
ENV FLASK_APP=app/http/app.py
ENV FLASK_ENV=production
ENV FLASK_DEBUG=0
ENV NLTK_DATA=/app/api/internal/core/unstructured/nltk_data

# CR-16102805：与课程原项目对齐，容器内拉 HuggingFace 走国内镜像站（默认走 huggingface.co 会超时）
ENV HF_ENDPOINT=https://hf-mirror.com

# CR-16102807：tiktoken 首次 get_encoding 会联网下载 BPE 文件（~1.6MB），国内网络下常卡数十秒到数分钟，
# 且默认缓存在 /tmp，容器重启即失效。这里把 cl100k_base 编码文件随镜像预置，运行时零联网。
ENV TIKTOKEN_CACHE_DIR=/app/api/docker/tiktoken_cache

# 设置容器时区为中国标准时间，避免时区错误
ENV TZ Asia/Shanghai

# 拷贝第三方依赖包+源码文件
COPY --from=base /pkg /usr/local
COPY . /app/api

# 拷贝运行脚本并设置权限
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 暴露5001端口
EXPOSE 5001

# 运行脚本并启动项目
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]