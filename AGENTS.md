# AGENTS.md — erp_lite

> Шаблон: `none` · создан: 2026-10-06 · порт: 4110
> Глобальные правила машины — в `~/.dsh/AGENTS.md`, они применяются автоматически.

## Проект

- Назначение: <одна строка — что это за приложение>
- Стек: Vite + React + TypeScript (strict), vitest + testing-library, Playwright, Biome
- Порт приложения: **4110** (`APP_PORT` в `.env`; dev/preview — из 4100–4199)

## Команды

```sh
pnpm dev          # 127.0.0.1:4100
pnpm typecheck    # tsc --noEmit
pnpm lint         # biome check .
pnpm test         # vitest
pnpm e2e          # сборка + Playwright (chromium)
pnpm build        # прод-сборка в dist/
```

## Деплой

```sh
export TAG=$(git rev-parse --short HEAD)
APP_PORT=4110 docker compose -f deploy/docker-compose.yml up -d --wait
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4110/healthz   # 200
```

Откат: `TAG=<предыдущий sha> ... up -d --wait`. Подробности — skill `web-deploy-local`.

## Специфика проекта

- Модель данных / БД: <нет | контейнер Postgres проекта на 554x, см. skill web-db>
- Внешние сервисы и ключи: <перечислить; секреты только в .env>
- Особые ограничения: <например, «не менять публичные URL», «RTL-вёрстка»>

## Чек-лист перед «готово»

1. `pnpm typecheck && pnpm lint && pnpm test`, для UI ещё `pnpm e2e`.
2. Интерфейс открыт и проверен (skill `web-ui-verify`), скриншот прочитан vision-субагентом.
3. Деплой проверен `/healthz` → 200, тег образа зафиксирован.
4. В отчёте перечислено, что **не** проверено.
