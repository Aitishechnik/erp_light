# Vite + React + TypeScript — шаблон проекта

Стартовый каркас для веб-приложений в этой рабочей области. Покрывает весь цикл:
разработка → типы/линт/тесты → e2e в браузере → сборка → локальный деплой в Docker.

## Как начать новый проект

```sh
cp -r /mnt/extraspace/DHS_test/templates/vite-react-ts ~/../mnt/extraspace/<project>
cd <project>
pnpm install
git init -b main && git config core.hooksPath .githooks
git add -A && git commit -m "chore: scaffold from template"
pnpm dev
```

## Команды (контракт из skill `web-scaffold`)

| Команда | Что делает |
|---|---|
| `pnpm dev` | dev-сервер на `127.0.0.1:4100` |
| `pnpm build` | `tsc --noEmit` + `vite build` → `dist/` |
| `pnpm preview` | предпросмотр сборки на `127.0.0.1:4173` |
| `pnpm typecheck` | проверка типов |
| `pnpm lint` / `pnpm lint:fix` | Biome |
| `pnpm test` | unit/component (vitest + testing-library) |
| `pnpm e2e` | сборка + Playwright (chromium) |

Порты специально выбраны из зарезервированного диапазона 4100–4199 (`AGENTS.md`).

## Деплой

```sh
export TAG=$(git rev-parse --short HEAD)
APP_PORT=4120 docker compose -f deploy/docker-compose.yml up -d --wait
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4120/healthz   # 200
```

Откат: `TAG=<предыдущий sha> APP_PORT=4120 docker compose -f deploy/docker-compose.yml up -d --wait`.

Подробности — skill `web-deploy-local`; если нужен reverse-proxy перед несколькими
сервисами, добавить сервис `proxy` из этого скилла.

## Структура

```
src/            код приложения и unit-тесты рядом с ним
tests/setup.ts  настройка jsdom + jest-dom
e2e/            сценарии Playwright
deploy/         nginx.conf и docker-compose.yml
.githooks/      pre-commit: biome --write + typecheck
.github/        CI (типы, линт, тесты, сборка, e2e)
```

## Что менять при старте

1. `name` и `image`/`name:` в `deploy/docker-compose.yml` — под имя проекта.
2. `APP_PORT` в `.env` (скопировать из `.env.example`).
3. Заголовок и содержимое `src/App.tsx`, `index.html` (`<title>`).
