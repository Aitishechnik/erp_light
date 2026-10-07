# frontend — интерфейс erp_lite

Одностраничное приложение для пяти ролей (менеджер по продажам, коммерческий директор,
директор по закупкам, менеджер по закупкам (импорт), исполнительный директор).
Боковое меню — разделы, один раздел = один экран. Работают **«Партии и остатки»**
и **«Планирование продаж»**, остальные разделы — заглушка «Модуль ещё не реализован».

Без сессии показывается экран входа ([`src/LoginPage.tsx`](src/LoginPage.tsx));
видимость разделов зависит от роли. Справочники и план продаж работают с данными,
загруженными из 1С на экране «Загрузка данных». Данные берутся из backend API (`/api/v1/...`),
деньги приходят **строками** — точность не теряется. Деньги на экран выводят
`formatMoney`, количество — `formatQuantity`, даты — `formatDate`
(все в [`src/api.ts`](src/api.ts)).

## Команды

```sh
pnpm install        # один раз
pnpm dev            # 127.0.0.1:4110, проксирует /api → 127.0.0.1:4111
pnpm typecheck      # tsc --noEmit
pnpm lint           # biome check .
pnpm lint:fix       # biome check --write .
pnpm test           # vitest (unit/component)
pnpm e2e            # сборка + Playwright (chromium)
pnpm build          # прод-сборка в dist/
pnpm preview        # предпросмотр сборки, 127.0.0.1:4173
```

Для `pnpm dev` backend должен быть запущен отдельно (`cd ../backend && make run`) —
иначе экран покажет ошибку загрузки.

## Структура

```
src/App.tsx            каркас: вход, меню разделов, активный экран (список SECTIONS)
src/LoginPage.tsx      экран входа
src/StockPage.tsx      экран «Партии и остатки»
src/SalesPlansPage.tsx экран «Планирование продаж» (клиент × товар × месяц)
src/NomenclaturePage.tsx экран «Номенклатура» (материалы, сырьё, готовая продукция)
src/CounterpartiesPage.tsx экран «Контрагенты» (покупатели и поставщики с признаками)
src/ImportsPage.tsx    экран «Загрузка данных» (6 типов выгрузок 1С + журнал)
src/api.ts             запросы к API + форматирование денег/количества/дат
src/apiMock.ts         помощник тестов: подмена fetch таблицей маршрутов
src/*.test.tsx         unit-тесты рядом с кодом
tests/setup.ts         настройка jsdom + jest-dom
e2e/                   сценарии Playwright
deploy/                nginx.conf + docker-compose.yml для локального деплоя
```

## Как добавить раздел

1. Пункт в `SECTIONS` ([`src/App.tsx`](src/App.tsx)): `ready: true` и, если нужно,
   список ролей `roles` — раздел будет виден только им.
2. Новая страница рядом (`src/<Раздел>Page.tsx`) + запросы в `src/api.ts`.
3. Тест на новую страницу и, если меняется поведение, сценарий в `e2e/`.

## Перед «готово»

```sh
pnpm typecheck && pnpm lint && pnpm test && pnpm e2e && pnpm build
```

Плюс реальная проверка интерфейса в браузере (skill `web-ui-verify`).

## Деплой

```sh
export TAG=$(git rev-parse --short HEAD)
APP_PORT=<порт> docker compose -f deploy/docker-compose.yml up -d --wait
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<порт>/healthz   # 200
```

> `deploy/docker-compose.yml` пока шаблонный: имя проекта `app-template`, порт по
> умолчанию `4120`. Перед первым деплоем erp_lite их нужно переименовать/задать.

## Ограничения

- Порт `4110` закреплён в `vite.config.ts` (`strictPort`), не менять без правки
  `AGENTS.md`.
- Вёрстка и тексты — на русском; десятичный разделитель на экране — запятая.
