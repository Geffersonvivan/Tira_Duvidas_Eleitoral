"""Autenticação via Clerk (portado do PJARI, instância independente do TDE).

Valida o JWT do Clerk (header Authorization ou cookie __session), verifica a
assinatura contra o JWKS do Clerk (cache 1h + fallback de rotação de chave) e
faz provisionamento JIT do usuário Django (username = clerk_id).

Degradação segura: se o Clerk não estiver configurado (sem CLERK_PUBLISHABLE_KEY),
o middleware é inerte e o site segue funcionando como público.
"""

import json
import logging

import jwt
import requests
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Paths que não passam por autenticação Clerk.
EXEMPT_PREFIXES = ("/admin/", "/health/", "/webhooks/", "/static/", "/media/")


class ClerkAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Clerk desligado: não interfere (site público).
        if not settings.CLERK_ENABLED:
            return self.get_response(request)

        if any(request.path.startswith(p) for p in EXEMPT_PREFIXES):
            return self.get_response(request)

        # Já autenticado por sessão Django (admin) — não mexe.
        if hasattr(request, "user") and request.user.is_authenticated:
            return self.get_response(request)

        token = self._extract_token(request)
        if not token:
            return self.get_response(request)

        try:
            payload = self._verify_token(token)
            clerk_user_id = payload.get("sub") if payload else None
            request.user = (
                self._get_or_create_user(clerk_user_id) if clerk_user_id else AnonymousUser()
            )
        except jwt.exceptions.ExpiredSignatureError:
            logger.debug("Clerk JWT expirado — %s", request.path)
            request.user = AnonymousUser()
        except Exception as e:
            logger.error("Erro ao validar token Clerk: %s", e)
            request.user = AnonymousUser()

        return self.get_response(request)

    @staticmethod
    def _extract_token(request):
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return request.COOKIES.get("__session")

    @staticmethod
    def _fetch_jwks():
        jwks = cache.get("clerk_jwks")
        if jwks:
            return jwks
        try:
            resp = requests.get(
                "https://api.clerk.com/v1/jwks",
                headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"},
                timeout=3,
            )
            resp.raise_for_status()
            jwks = resp.json()
            cache.set("clerk_jwks", jwks, timeout=3600)
            return jwks
        except Exception as e:
            logger.warning("Falha ao buscar JWKS do Clerk: %s", e)
            return None

    @classmethod
    def _verify_token(cls, token):
        jwks = cls._fetch_jwks()
        if not jwks:
            return None

        kid = jwt.get_unverified_header(token).get("kid")
        rsa_key = cls._find_rsa_key(jwks, kid)

        # Fallback de rotação de chave: invalida o cache e tenta de novo.
        if not rsa_key:
            cache.delete("clerk_jwks")
            jwks = cls._fetch_jwks()
            if jwks:
                rsa_key = cls._find_rsa_key(jwks, kid)
        if not rsa_key:
            logger.warning("RSA key não encontrada para kid=%s", kid)
            return None

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(rsa_key))
        return jwt.decode(token, public_key, algorithms=["RS256"], options={"verify_aud": False})

    @staticmethod
    def _find_rsa_key(jwks, kid):
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return {k: key[k] for k in ("kty", "kid", "use", "n", "e") if k in key}
        return None

    @staticmethod
    def _get_or_create_user(clerk_user_id):
        user = User.objects.filter(username=clerk_user_id).first()
        if user:
            return user

        # JIT: lock por cache para evitar corrida entre requests concorrentes.
        sync_key = f"clerk_jit_{clerk_user_id}"
        if cache.get(sync_key):
            return AnonymousUser()
        cache.set(sync_key, True, timeout=300)

        try:
            resp = requests.get(
                f"https://api.clerk.com/v1/users/{clerk_user_id}",
                headers={"Authorization": f"Bearer {settings.CLERK_SECRET_KEY}"},
                timeout=3,
            )
            if resp.status_code != 200:
                return AnonymousUser()
            data = resp.json()
            emails = data.get("email_addresses", [])
            email = emails[0].get("email_address", "") if emails else ""

            # Migração por e-mail: se já existe usuário com esse e-mail, adota o clerk_id.
            existing = User.objects.filter(email=email).first() if email else None
            if existing and existing.username != clerk_user_id:
                existing.username = clerk_user_id
                existing.first_name = (data.get("first_name") or existing.first_name)[:30]
                existing.last_name = (data.get("last_name") or existing.last_name)[:30]
                existing.save(update_fields=["username", "first_name", "last_name"])
                user = existing
            else:
                user = User.objects.create(
                    username=clerk_user_id,
                    email=email,
                    first_name=(data.get("first_name") or "")[:30],
                    last_name=(data.get("last_name") or "")[:30],
                )
                user.set_unusable_password()
                user.save()

            # Sincroniza o clerk_id no perfil (criado pelo signal post_save).
            from core.models import UserProfile

            UserProfile.objects.update_or_create(user=user, defaults={"clerk_id": clerk_user_id})
            cache.set(sync_key, True, timeout=3600)
            return user
        except Exception as e:
            logger.error("Falha no JIT sync Clerk: %s", e)
            return AnonymousUser()
