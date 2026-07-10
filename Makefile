.PHONY: install lint format audit test check run migrate

install:            ## instala deps de runtime + dev
	pip install -e ".[dev]"
	pre-commit install

lint:               ## ruff: checa lint + ordenação de imports
	ruff check .

format:             ## ruff: formata o código
	ruff format .

audit:              ## pip-audit: varre vulnerabilidades nas dependências
	pip-audit --skip-editable

test:               ## roda a suíte de testes
	pytest -q

check: lint audit test   ## portão de qualidade: lint + audit + testes

run:                ## sobe o servidor de desenvolvimento
	python manage.py runserver

migrate:            ## aplica migrações
	python manage.py migrate
