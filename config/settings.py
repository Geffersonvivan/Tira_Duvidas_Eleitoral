"""Configuração Django — Tira Dúvidas Eleitoral.

Lê variáveis de `.env` (ver `.env.example`). Sem DATABASE_URL, usa SQLite,
para o portão de qualidade (`make check`) rodar verde sem Postgres local.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: str = "False") -> bool:
    return os.environ.get(name, default).lower() in {"1", "true", "yes"}


# --- Segurança ---------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-inseguro-troque-no-env")
DEBUG = _env_bool("DJANGO_DEBUG", "True")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# Railway expõe o domínio público em RAILWAY_PUBLIC_DOMAIN — libera host + CSRF sozinho.
_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if _railway_domain:
    ALLOWED_HOSTS.append(_railway_domain)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_railway_domain}")

# Hardening em produção (Railway termina o TLS e envia X-Forwarded-Proto).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # HttpOnly no cookie de sessão (default do Django, explícito aqui). O cookie
    # CSRF fica legível de propósito — o frontend lê o token para o header nas
    # chamadas AJAX; torná-lo HttpOnly quebraria o envio do X-CSRFToken.
    SESSION_COOKIE_HTTPONLY = True
    # HSTS — o site é servido só por HTTPS (Railway + redirect acima).
    # Configurável; 0 desliga. includeSubDomains/preload são opt-in (cuidado).
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "False")
    SECURE_HSTS_PRELOAD = _env_bool("DJANGO_HSTS_PRELOAD", "False")

# --- Apps --------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # apps do projeto
    "core",
    "rag",
    "llm",
    "perguntas",
    "materiais",
    "analytics",
    "conversas",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serve estáticos em produção
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Clerk JWT — roda após o AuthenticationMiddleware. Inerte se Clerk desligado.
    "core.middleware.ClerkAuthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# --- Auth (Clerk) ------------------------------------------------------
# Instância independente do TDE (usuários próprios, separados do PJARI).
# Sem CLERK_PUBLISHABLE_KEY, o login fica DESLIGADO e o site segue público
# (degradação segura — não quebra produção antes de configurar o Clerk).
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_WEBHOOK_SECRET = os.environ.get("CLERK_WEBHOOK_SECRET", "")
CLERK_ENABLED = bool(CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY)
# Defesa em profundidade na validação do JWT (opcional; se vazio, só a assinatura
# + claims básicos são conferidos). CLERK_ISSUER = Frontend API URL do Clerk
# (ex.: https://clerk.tiraduvidaseleitoral.com.br). CLERK_AUTHORIZED_PARTIES =
# lista separada por vírgula de origens (azp) aceitas.
CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "")
CLERK_AUTHORIZED_PARTIES = [
    p.strip() for p in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if p.strip()
]
LOGIN_URL = "/"

# --- Limites de uso (custo/abuso) -------------------------------------
# Teto de requisições por minuto, por usuário (ou IP no público), nos
# endpoints que chamam LLM. 0 desliga. Ver core/ratelimit.py (por worker
# com o cache padrão; Redis fecha o teto global — OPERACAO.md).
RATE_LIMIT_PERGUNTAS_POR_MIN = int(os.environ.get("RATE_LIMIT_PERGUNTAS_POR_MIN", "20"))
RATE_LIMIT_MATERIAIS_POR_MIN = int(os.environ.get("RATE_LIMIT_MATERIAIS_POR_MIN", "8"))

# --- Analytics de perguntas -------------------------------------------
# Limiar de distância de cosseno para agrupar perguntas de sentido próximo
# (0 = idêntico). ~0.12 corresponde a similaridade ~0.88. Calibrar com dados.
ANALYTICS_LIMIAR_DISTANCIA = float(os.environ.get("ANALYTICS_LIMIAR_DISTANCIA", "0.12"))

# --- Billing / Stripe --------------------------------------------------
# Assinatura recorrente (Essencial R$349, Profissional R$499). Crie os dois
# Prices RECORRENTES no dashboard do Stripe e cole os IDs aqui. Sem chaves, o
# billing fica inerte (as views retornam erro amigável) — não quebra o app.
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
BILLING_ENABLED = bool(STRIPE_SECRET_KEY)
# Interruptor da COBRANÇA: com False (default) o gate de cota é inerte — o app
# funciona sem limites, como hoje. Ligar (True) só quando o Stripe estiver
# configurado, senão os usuários travam nas 3 perguntas sem como pagar.
BILLING_ENFORCE = _env_bool("BILLING_ENFORCE", "False")
# Fim do acesso do passe (fixo p/ todos). Eleição (1º turno): 04/10/2026.
BILLING_ACESSO_ATE = os.environ.get("BILLING_ACESSO_ATE", "2026-10-05")
# Consultoria jurídica: só CTA de WhatsApp (sem checkout). Formato E.164 sem "+".
BILLING_WHATSAPP = os.environ.get("BILLING_WHATSAPP", "5549991031516")

# --- RAG · recuperação -------------------------------------------------
# Distância de cosseno máxima aceita num trecho recuperado (0 = idêntico,
# 2 = oposto). Acima disso o trecho é descartado por irrelevância, evitando
# alimentar o LLM com contexto fraco. Vazio = desligado (sem corte) — calibrar
# com o golden set antes de ativar (um valor muito baixo derruba contexto útil).
_rag_dist = os.environ.get("RAG_DISTANCIA_MAX", "").strip()
RAG_DISTANCIA_MAX = float(_rag_dist) if _rag_dist else None

# --- LGPD · retenção de dados -----------------------------------------
# Expurgo executado pelo comando `expurgar_dados` (agende no cron/Railway).
# 0 = desligado (nada é apagado por idade). Defina os prazos conforme a
# política de privacidade antes de ativar. Perguntas registradas são anônimas
# (sem vínculo com usuário); conversas são por usuário e também exclusíveis
# sob demanda (direito ao esquecimento) via API.
LGPD_RETENCAO_PERGUNTAS_DIAS = int(os.environ.get("LGPD_RETENCAO_PERGUNTAS_DIAS", "0"))
LGPD_RETENCAO_CONVERSAS_DIAS = int(os.environ.get("LGPD_RETENCAO_CONVERSAS_DIAS", "0"))

# --- RAG · ingestão do Google Drive (fonte viva) ----------------------
# A pasta "RAG" no Drive é compartilhada (leitura) com uma conta de serviço.
# Estrutura: RAG/<Assunto>/<Natureza>/arquivos. O 1º nível vira `assunto`
# (mapa abaixo); o 2º nível define a natureza (doutrina/curso → contexto,
# não citável). GOOGLE_SERVICE_ACCOUNT_JSON = conteúdo do JSON da chave.
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
RAG_DRIVE_ROOT_FOLDER_ID = os.environ.get(
    "RAG_DRIVE_ROOT_FOLDER_ID", "1ZBob8k0drK6m38TghIg6p_OG0avxs3qZ"
)
# Nome da pasta-raiz no Drive → assunto do RAG (enum rag.models.Assunto).
RAG_DRIVE_ASSUNTO_MAP = {
    "Juridico": "direito",
    "Jurídico": "direito",
    "Contábil": "contabilidade",
    "Contabil": "contabilidade",
    "Gestão de Tráfego": "impulsionamento",
    "Gestao de Trafego": "impulsionamento",
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Banco de dados ----------------------------------------------------
_db_url = os.environ.get("DATABASE_URL")
if _db_url and _db_url.startswith("postgres"):
    _u = urlparse(_db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _u.path.lstrip("/"),
            "USER": _u.username or "",
            "PASSWORD": _u.password or "",
            "HOST": _u.hostname or "",
            "PORT": str(_u.port or ""),
            # TCP keepalives: mantêm a conexão viva durante operações longas sem
            # SQL (ex.: OCR de um livro inteiro na ingestão do Drive), evitando
            # que o proxy/servidor derrube uma conexão ociosa. Inofensivo em prod.
            "OPTIONS": {
                "keepalives": 1,
                "keepalives_idle": 15,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --- Validação de senha ------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n / tz ---------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# --- Estáticos ---------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Em produção: WhiteNoise com compressão + manifest (cache-busting por hash).
# Em dev (DEBUG): storage simples, para não exigir collectstatic localmente.
_static_backend = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _static_backend},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Upload (Serviço 2: santinhos/PDFs) --------------------------------
# Peças gráficas passam do padrão de 2,5 MB. Imagem não é retida (§11.1),
# fica só em memória durante a análise.
_UPLOAD_MAX = 20 * 1024 * 1024  # 20 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = _UPLOAD_MAX
FILE_UPLOAD_MAX_MEMORY_SIZE = _UPLOAD_MAX

# --- Logging -----------------------------------------------------------
# Com DEBUG=False o Django, por padrão, não emite o traceback dos 500 em
# lugar nenhum (só e-mail para ADMINS). Sem isto, erros de produção ficam
# invisíveis. Enviamos tudo para stderr → capturado pelo gunicorn/Railway.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "padrao": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "padrao"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # Traceback completo dos 500 (inclui a exceção não tratada da view).
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

# --- Observabilidade (Sentry) -----------------------------------------
# Ativo só com SENTRY_DSN definido e fora do DEBUG. send_default_pii=False por
# LGPD (não envia corpo de request, e-mail nem a pergunta). traces_sample_rate
# controla o APM (0 = só erros, para não gerar custo/volume).
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN and not DEBUG:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
            send_default_pii=False,
            environment=os.environ.get("RAILWAY_ENVIRONMENT_NAME", "production"),
        )
    except ImportError:  # sentry-sdk não instalado neste ambiente — segue sem APM
        pass
