# syntax=docker/dockerfile:1
# Venera API uchun root'siz (non-root) production image.
#
# NEGA KONTEYNER, oddiy venv emas: bu host'da `python3-venv` paketi yo'q va
# uni o'rnatish uchun sudo kerak. Konteynerda bog'liqliklar image ichida
# turadi - host'ning Python holati umuman ahamiyatsiz bo'lib qoladi.
# Bundan tashqari frontend ham aynan shunday tarqatiladi (apps/web/Dockerfile),
# ya'ni ikkala xizmat bir xil naqsh bilan boshqariladi.
#
# PRODUCTION: bazaviy image'ni @sha256 digest bilan qadab qo'ying.
ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE}

# Python'ni konteyner uchun sozlash:
#   PYTHONDONTWRITEBYTECODE - .pyc fayllari read-only fayl tizimida keraksiz
#   PYTHONUNBUFFERED        - log DARHOL journalctl ga tushsin, buferda qolmasin
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Bog'liqliklar AVVAL o'rnatiladi: manba o'zgarganda ham bu qatlam keshdan
# olinadi va build sekundlarda tugaydi.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "pydantic-settings>=2.4" \
        "PyJWT>=2.9" \
        "PyYAML>=6.0"

COPY app ./app

# Swagger UI fayllari IMAGE ICHIGA yuklab olinadi.
#
# NEGA: FastAPI hujjat sahifasini default holda `cdn.jsdelivr.net` dan
# yuklaydi. Ichki tarmoqda (10.10.50.x, VPN ortida) internet YO'Q va sahifa
# BO'SH ochiladi - "hujjat bor" deb o'ylab, aslida yo'q holatga tushiladi.
# Fayllar bu yerda bo'lsa `app/main.py` ularni lokal beradi.
#
# Internet build MASHINASIDA kerak, foydalanuvchi tarmog'ida emas.
ARG SWAGGER_VERSION=5.17.14
ADD https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWAGGER_VERSION}/swagger-ui-bundle.js /app/app/static/swagger-ui-bundle.js
ADD https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWAGGER_VERSION}/swagger-ui.css /app/app/static/swagger-ui.css


# Root'siz ishlash. `config/` va `.env` image ichiga KIRMAYDI - ular runtime'da
# bind-mount qilinadi, chunki ularda sirlar bor va ular muhitga qarab farq
# qiladi. Bitta image staging va prod'da o'zgarishsiz ishlaydi.
RUN useradd --system --uid 10001 --no-create-home venera \
    && chown -R venera:venera /app
USER 10001

EXPOSE 8000

# HEALTHCHECK image ichida YO'Q: bu slim image'da curl/wget yo'q va sog'liq
# tekshiruvi TASHQARIDAN qilinadi (systemd + `/health` endpointi) - HTTP zond
# uchun standart joy aynan shu. Faqat o'zini tekshirish uchun konteynerga
# vosita qo'shish image'ni bekorga shishirardi.

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
