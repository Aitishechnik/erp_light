"""Стенд «2027»: очистка данных, наполнение и моковые выгрузки 1С.

Сценарий, приближенный к реальности:

* планирование, поставки и факты очищаются; номенклатура, контрагенты, страны,
  курсы и роли остаются;
* за тремя менеджерами закрепляются 15 клиентов;
* на 2027 год строится план продаж (14 позиций, все 12 месяцев), его утверждают
  коммерческий директор и генеральный, из него собирается план закупок сырья
  (14 основных строк и 6 альтернатив);
* в ``data/mock/2027`` пишутся выгрузки «как из 1С»: продажи за январь и февраль,
  импортные поступления и две партии;
* поступления заводятся файлом, строки получают цены; две партии проверяют
  автоподхват при загрузке «Партии», остальные привязываются к плану.

Команды (порядок важен): ``reset`` → ``clients`` → ``plans`` → ``files`` → ``receipts``.
``all`` делает всё подряд.

Запуск: ``backend/.venv/bin/python scripts/stand_2027.py all``
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

API = "http://127.0.0.1:4111/api/v1"
PASSWORD = "123"
ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "data" / "mock" / "2027"

# Контейнер базы проекта: очистка идёт SQL-ом, потому что часть истории
# (журнал загрузок, снимки) не удаляется через API.
DB_CONTAINER = "erp_lite-db-1"
DB_USER = "erp_lite"
DB_NAME = "erp_lite"

TRUNCATE = (
    "batches",
    "batch_items",
    "batch_expenses",
    "batch_payments",
    "stock_snapshots",
    "sales_facts",
    "sales_fact_unmatched",
    "product_aliases",
    "deviation_reasons",
    "month_result_snapshots",
    "month_results",
    "sales_plan_correction_items",
    "sales_plan_corrections",
    "sales_plan_approvals",
    "sales_plan_items",
    "sales_plans",
    "purchase_plan_source_events",
    "purchase_plan_items",
    "purchase_plans",
    "import_sessions",
)


@dataclass(frozen=True)
class Product:
    """Позиция стенда: готовая продукция, её сырьё и поставка."""

    finished: str
    finished_code: str
    raw: str
    raw_code: str
    country: str
    supplier: str
    recipe: Decimal
    base_kg: Decimal
    price_rub: Decimal
    price_usd: Decimal
    duty: Decimal


@dataclass(frozen=True)
class Alternative:
    """Альтернативная строка плана: другое сырьё или другая страна для позиции."""

    main: str
    raw: str
    raw_code: str
    country: str
    supplier: str
    share: Decimal  # доля от годовой потребности основной строки
    price_rub: Decimal
    price_usd: Decimal
    duty: Decimal = Decimal("5")


PRODUCTS: tuple[Product, ...] = (
    Product(
        "Грецкий орех сушеный, вес, кг",
        "ТОВ395389",
        "Грецкий орех сушеный, вес",
        "ТОВ395561",
        "Китай",
        "SHENYANG EAN FOODS CO., LTD (Китай)",
        Decimal("1.02"),
        Decimal("5200"),
        Decimal("1150"),
        Decimal("8.40"),
        Decimal("5"),
    ),
    Product(
        "Грецкий орех в скорлупе, Global Village, вес, кг",
        "ТОВ395262",
        "Грецкий орех в скорлупе, вес",
        "ТОВ395123",
        "Китай",
        "DALIAN GOODLUCK AGRICULTURAL PRODUCTS CO., LTD. (Китай)",
        Decimal("1.06"),
        Decimal("2600"),
        Decimal("690"),
        Decimal("3.90"),
        Decimal("5"),
    ),
    Product(
        "Изюм Малаяр, вес, кг",
        "ТОВ395494",
        "Изюм Малаяр, вес",
        "ТОВ395158",
        "Узбекистан",
        "SAMARKAND DRIED FRUITS LLC (Узбекистан)",
        Decimal("1.01"),
        Decimal("8400"),
        Decimal("420"),
        Decimal("2.60"),
        Decimal("5"),
    ),
    Product(
        "Изюм светлый Голден, вес, кг",
        "ТОВ396581",
        "Изюм светлый Голден, вес",
        "ТОВ395884",
        "Иран",
        "PARS DATES CO. (Иран)",
        Decimal("1.01"),
        Decimal("3900"),
        Decimal("480"),
        Decimal("2.95"),
        Decimal("5"),
    ),
    Product(
        "Курага, вес, кг",
        "ТОВ395240",
        "Курага светлая № 1 вес",
        "ТОВ395166",
        "Узбекистан",
        "SAMARKAND DRIED FRUITS LLC (Узбекистан)",
        Decimal("1.03"),
        Decimal("6100"),
        Decimal("510"),
        Decimal("3.10"),
        Decimal("5"),
    ),
    Product(
        "Финики БОН-БОН, вес, кг",
        "ТОВ396391",
        "Финики БОН-БОН, вес",
        "ТОВ395655",
        "Иран",
        "PARS DATES CO. (Иран)",
        Decimal("1.02"),
        Decimal("4400"),
        Decimal("560"),
        Decimal("3.30"),
        Decimal("5"),
    ),
    Product(
        "Кешью сушеный, W320, вес, кг",
        "ТОВ395393",
        "Кешью сушеный, W320, вес",
        "ТОВ395148",
        "Китай",
        "SHANDONG WEIFANG IMPORT & EXPORT CO., LTD.(Китай)",
        Decimal("1.03"),
        Decimal("3100"),
        Decimal("980"),
        Decimal("7.10"),
        Decimal("5"),
    ),
    Product(
        "Миндаль сушеный, 23-25, вес, кг",
        "ТОВ395873",
        "Миндаль сушеный, 23-25, вес",
        "ТОВ395563",
        "Турция",
        "ANATOLIA KURUYEMIS TIC. LTD (Турция)",
        Decimal("1.04"),
        Decimal("3700"),
        Decimal("890"),
        Decimal("6.20"),
        Decimal("5"),
    ),
    Product(
        "Арахис сушеный, вес, кг",
        "ТОВ395366",
        "Арахис сушеный, вес",
        "ТОВ395120",
        "Китай",
        "SHANDONG WEIFANG IMPORT & EXPORT CO., LTD.(Китай)",
        Decimal("1.03"),
        Decimal("4200"),
        Decimal("780"),
        Decimal("5.40"),
        Decimal("5"),
    ),
    Product(
        "Инжир, сушеный, вес, кг",
        "ТОВ395497",
        "Инжир сушеный, вес",
        "ТОВ395162",
        "Турция",
        "ANATOLIA KURUYEMIS TIC. LTD (Турция)",
        Decimal("1.04"),
        Decimal("3000"),
        Decimal("980"),
        Decimal("6.70"),
        Decimal("5"),
    ),
    Product(
        "Кешью сушеный, W180, вес, кг",
        "ТОВ395648",
        "Кешью сушеный, W180, вес",
        "ТОВ395245",
        "Китай",
        "SHANDONG WEIFANG IMPORT & EXPORT CO., LTD.(Китай)",
        Decimal("1.03"),
        Decimal("2400"),
        Decimal("1250"),
        Decimal("8.90"),
        Decimal("5"),
    ),
    Product(
        "Миндаль сушеный, 27-30, вес, кг",
        "ТОВ396353",
        "Миндаль сушеный, 27-30, вес",
        "ТОВ396271",
        "Турция",
        "ANATOLIA KURUYEMIS TIC. LTD (Турция)",
        Decimal("1.04"),
        Decimal("2800"),
        Decimal("1120"),
        Decimal("7.80"),
        Decimal("5"),
    ),
    Product(
        "Пекан сушеный, вес, кг",
        "ТОВ395410",
        "Пекан сушеный, вес",
        "ТОВ395151",
        "Турция",
        "ANATOLIA KURUYEMIS TIC. LTD (Турция)",
        Decimal("1.03"),
        Decimal("2600"),
        Decimal("1380"),
        Decimal("9.60"),
        Decimal("5"),
    ),
    Product(
        "Чернослив, вес",
        "ТОВ395244",
        "Чернослив, вес",
        "ТОВ395633",
        "Узбекистан",
        "SAMARKAND DRIED FRUITS LLC (Узбекистан)",
        Decimal("1.02"),
        Decimal("5000"),
        Decimal("520"),
        Decimal("3.20"),
        Decimal("5"),
    ),
)

# Альтернативы: другая страна/калибр для уже существующей позиции. Своей
# потребности у них нет — количество это план закупки, а приход идёт в котёл
# основной строки.
ALTERNATIVES: tuple[Alternative, ...] = (
    Alternative(
        "Грецкий орех в скорлупе, Global Village, вес, кг",
        "Грецкий орех, сырой очищенный, (ядро), вес",
        "ТОВ395126",
        "Узбекистан",
        "SAMARKAND DRIED FRUITS LLC (Узбекистан)",
        Decimal("0.25"),
        Decimal("520"),
        Decimal("6.50"),
    ),
    Alternative(
        "Кешью сушеный, W320, вес, кг",
        "Кешью сушеный, W240, вес",
        "ТОВ395340",
        "Китай",
        "SHANDONG WEIFANG IMPORT & EXPORT CO., LTD.(Китай)",
        Decimal("0.20"),
        Decimal("940"),
        Decimal("7.40"),
    ),
    Alternative(
        "Курага, вес, кг",
        "Курага Иран, вес",
        "ТОВ397404",
        "Иран",
        "PARS DATES CO. (Иран)",
        Decimal("0.20"),
        Decimal("560"),
        Decimal("4.20"),
    ),
    Alternative(
        "Финики БОН-БОН, вес, кг",
        "Финики Захиди, вес",
        "ТОВ396692",
        "Иран",
        "PARS DATES CO. (Иран)",
        Decimal("0.20"),
        Decimal("430"),
        Decimal("3.40"),
    ),
    Alternative(
        "Изюм Малаяр, вес, кг",
        "Изюм темный Сояги, вес",
        "ТОВ395161",
        "Узбекистан",
        "SAMARKAND DRIED FRUITS LLC (Узбекистан)",
        Decimal("0.20"),
        Decimal("380"),
        Decimal("2.90"),
    ),
    Alternative(
        "Миндаль сушеный, 23-25, вес, кг",
        "Миндаль сушеный, 25-27, вес",
        "ТОВ395886",
        "Турция",
        "ANATOLIA KURUYEMIS TIC. LTD (Турция)",
        Decimal("0.20"),
        Decimal("950"),
        Decimal("6.80"),
    ),
)

COUNTRIES = (("Иран", 35), ("Узбекистан", 25), ("Турция", 20))

# Клиенты по менеджерам: по пять на каждого, как в жизни — сети разного масштаба.
MANAGERS: dict[str, tuple[str, ...]] = {
    "sales": (
        "Пятерочка (Агроторг)",
        "Перекресток (ТД Перекресток)",
        "МАГНИТ МАРКЕТ",
        "Дикси",
        "Лента",
    ),
    "sales2": (
        "Вкус Вилл (Вкусвилл ПАО)",
        "Метро (Кэш энд Керри)",
        "Азбука Вкуса (Городской Супермаркет)",
        "Мария-РА (Розница К-1)",
        "17:17",
    ),
    "sales3": (
        "Верный",
        "АШАН",
        "Гиперглобус",
        "Глобус-Гурмэ",
        "Магнит (Тандер)",
    ),
}

MANAGER_NAMES = {
    "sales": "Менеджер по продажам (демо)",
    "sales2": "Менеджер по продажам 2 (демо)",
    "sales3": "Менеджер по продажам 3 (демо)",
}

# Сезонность спроса: летом спад, к декабрю пик.
SEASON = (
    Decimal("0.80"),
    Decimal("0.85"),
    Decimal("0.95"),
    Decimal("1.00"),
    Decimal("1.05"),
    Decimal("1.10"),
    Decimal("0.95"),
    Decimal("0.90"),
    Decimal("1.00"),
    Decimal("1.10"),
    Decimal("1.20"),
    Decimal("1.30"),
)

# Как распродаётся январский план: часть строк недобирает, часть уходит сверх плана.
JAN_FACTORS = (
    Decimal("1.00"),
    Decimal("0.45"),
    Decimal("0.75"),
    Decimal("0.00"),
    Decimal("0.90"),
    Decimal("1.12"),
)

FEB_FACTORS = (
    Decimal("0.80"),
    Decimal("1.00"),
    Decimal("0.55"),
    Decimal("0.95"),
    Decimal("1.05"),
    Decimal("0.30"),
)


class Api:
    """Маленький клиент API: у каждого пользователя своя сессия в cookie."""

    def __init__(self, login: str) -> None:
        self.login = login
        self.client = httpx.Client(base_url=API, timeout=120)
        response = self.client.post("/auth/login", json={"login": login, "password": PASSWORD})
        if response.status_code != 200:
            raise SystemExit(f"Не вошёл как {login}: {response.text}")

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} → {response.status_code}: {response.text}")
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def upload(self, path: str, file: Path) -> Any:
        with file.open("rb") as handle:
            return self.request(
                "POST",
                path,
                files={"file": (file.name, handle, "application/vnd.ms-excel")},
            )


# --- шаг 1: очистка ------------------------------------------------------------


def psql(sql: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            DB_CONTAINER,
            "psql",
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-At",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"psql: {result.stderr.strip()}")
    return result.stdout.strip()


def cmd_reset() -> None:
    """Убрать планирование, поставки и факты; справочники и роли оставить."""
    psql(f"TRUNCATE {', '.join(TRUNCATE)}")
    psql("UPDATE counterparties SET manager_id = NULL")
    counts = psql(
        "select 'планы', count(*) from sales_plans union all "
        "select 'факты', count(*) from sales_facts union all "
        "select 'партии', count(*) from batches union all "
        "select 'номенклатура', count(*) from products union all "
        "select 'контрагенты', count(*) from counterparties union all "
        "select 'люди', count(*) from users"
    )
    print("Очищено. Осталось:\n" + counts)


# --- шаг 2: клиенты за менеджерами ---------------------------------------------


def users_by_login(api: Api) -> dict[str, str]:
    rows = api.get("/users")
    return {row["login"]: row["id"] for row in rows}


def find_counterparty(api: Api, name: str) -> str:
    rows = api.get("/counterparties", params={"include_inactive": True})
    for row in rows:
        if row["name"].casefold() == name.casefold():
            return row["id"]
    raise SystemExit(f"Контрагент «{name}» не найден в справочнике")


def cmd_clients() -> None:
    """Закрепить 15 клиентов за тремя менеджерами (правит коммерческий директор)."""
    api = Api("commercial")
    users = users_by_login(api)
    for login, clients in MANAGERS.items():
        manager_id = users[login]
        for name in clients:
            counterparty_id = find_counterparty(api, name)
            api.patch(f"/counterparties/{counterparty_id}", json={"manager_id": manager_id})
    print(f"Закреплено клиентов: {sum(len(rows) for rows in MANAGERS.values())}")


# --- шаг 3: планы ---------------------------------------------------------------


def month_quantities() -> dict[tuple[str, str, int], Decimal]:
    """Клиент × позиция × месяц: количество плана (кг)."""
    plan: dict[tuple[str, str, int], Decimal] = {}
    for manager_index, clients in enumerate(MANAGERS.values()):
        for client_index, client in enumerate(clients):
            for product_index, product in enumerate(PRODUCTS):
                # Не каждый клиент берёт весь ассортимент.
                if (client_index * 5 + product_index * 3 + manager_index) % 4 == 3:
                    continue
                share = Decimal("0.030") + Decimal("0.008") * Decimal(
                    (client_index * 7 + product_index * 5 + manager_index * 3) % 6
                )
                for month in range(1, 13):
                    quantity = (product.base_kg * share * SEASON[month - 1]).quantize(
                        Decimal("0.001")
                    )
                    plan[(client, product.finished, month)] = quantity
    return plan


def cmd_plans() -> None:
    """План продаж на 2027 по менеджерам, утверждение и план закупок."""
    plan = month_quantities()
    clients = {}
    products = {}

    commercial = Api("commercial")
    for row in commercial.get("/counterparties", params={"include_inactive": True}):
        clients[row["name"]] = row["id"]
    # По коду, а не по имени: в справочнике есть одноимённые готовые позиции и сырьё.
    finished_by_name: dict[str, dict[str, Any]] = {}
    for row in commercial.get("/products"):
        products[row["code"]] = row
        if row["kind"] == "finished":
            finished_by_name.setdefault(row["name"], row)

    by_manager: dict[str, dict[tuple[str, str, int], Decimal]] = {name: {} for name in MANAGERS}
    for (client, product, month), quantity in plan.items():
        for login, names in MANAGERS.items():
            if client in names:
                by_manager[login][(client, product, month)] = quantity
                break

    plan_ids: dict[str, str] = {}
    for login, rows in by_manager.items():
        manager = Api(login)
        plans = manager.get("/sales-plans", params={"year": 2027})
        if plans:
            plan_id = plans[0]["id"]
        else:
            plan_id = manager.post("/sales-plans", json={"year": 2027})["id"]
        items = [
            {
                "client_id": clients[client],
                "product_id": finished_by_name[product]["id"],
                "month": month,
                "quantity": str(quantity),
            }
            for (client, product, month), quantity in sorted(rows.items())
        ]
        manager.put(f"/sales-plans/{plan_id}/items", json={"items": items})
        manager.post(f"/sales-plans/{plan_id}/submit")
        commercial.post(f"/sales-plans/{plan_id}/approve")
        plan_ids[login] = plan_id
        print(f"{login}: {len(items)} строк плана, утверждён")

    commercial.post("/annual-sales-plans/2027/submit")
    Api("executive").post("/annual-sales-plans/2027/approve")
    print("Годовой план отдела согласован генеральным")

    purchase = Api("purchase")
    countries = {row["name"]: row["id"] for row in purchase.get("/countries")}
    for name, days in COUNTRIES:
        if name not in countries:
            row = purchase.post("/countries", json={"name": name, "delivery_days": days})
            countries[name] = row["id"]

    suppliers = {}
    for row in purchase.get("/counterparties", params={"include_inactive": True}):
        suppliers[row["name"]] = row["id"]
    for product in PRODUCTS:
        if product.supplier not in suppliers:
            row = purchase.post(
                "/counterparties",
                json={"name": product.supplier, "is_import_supplier": True},
            )
            suppliers[product.supplier] = row["id"]

    plans = purchase.get("/purchase-plans", params={"year": 2027})
    purchase_plan_id = (
        plans[0]["id"] if plans else purchase.post("/purchase-plans", json={"year": 2027})["id"]
    )

    annual: dict[str, Decimal] = {}
    for (_client, product, _month), quantity in plan.items():
        annual[product] = annual.get(product, Decimal("0")) + quantity

    # Сначала основные строки: альтернативе нужен id основной строки.
    main_items: list[dict[str, Any]] = []
    for product in PRODUCTS:
        quantity = (annual.get(product.finished, Decimal("0")) * product.recipe).quantize(
            Decimal("0.001")
        )
        if quantity <= 0:
            continue
        main_items.append(
            {
                "sales_product_id": products[product.finished_code]["id"],
                "product_id": products[product.raw_code]["id"],
                "country_id": countries[product.country],
                "quantity": str(quantity),
                "norm": str(product.recipe),
                "price_rub": str(product.price_usd * Decimal("79.5")),
            }
        )
    saved = purchase.put(f"/purchase-plans/{purchase_plan_id}/items", json={"items": main_items})
    main_ids = {(row["sales_product_id"], row["product_id"]): row["id"] for row in saved["items"]}
    main_items_with_ids = [
        {**item, "id": main_ids[(item["sales_product_id"], item["product_id"])]}
        for item in main_items
    ]
    product_by_finished = {product.finished: product for product in PRODUCTS}
    alternative_items: list[dict[str, Any]] = []
    for alternative in ALTERNATIVES:
        main = product_by_finished[alternative.main]
        main_quantity = (annual.get(main.finished, Decimal("0")) * main.recipe).quantize(
            Decimal("0.001")
        )
        if main_quantity <= 0:
            continue
        main_id = main_ids[(products[main.finished_code]["id"], products[main.raw_code]["id"])]
        alternative_items.append(
            {
                "sales_product_id": products[main.finished_code]["id"],
                "product_id": products[alternative.raw_code]["id"],
                "country_id": countries[alternative.country],
                "quantity": str((main_quantity * alternative.share).quantize(Decimal("0.001"))),
                "norm": str(main.recipe),
                "price_rub": str(alternative.price_rub),
                "alternative_of_id": main_id,
                "notes": f"Альтернатива: {alternative.raw}",
            }
        )

    items = [*main_items_with_ids, *alternative_items]
    purchase.put(f"/purchase-plans/{purchase_plan_id}/items", json={"items": items})
    purchase.post(f"/purchase-plans/{purchase_plan_id}/submit")
    Api("executive").post(f"/purchase-plans/{purchase_plan_id}/approve")
    print(
        f"План закупок: {len(main_items)} основных + {len(alternative_items)} "
        "альтернативных строк, утверждён генеральным"
    )


# --- шаг 4: моковые выгрузки ------------------------------------------------------


def _sheet(workbook: Workbook) -> Any:
    sheet = workbook.active
    sheet.title = "TDSheet"
    return sheet


def _widths(sheet: Any, widths: list[int]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def write_sales_file(path: Path, year: int, month: int, rows: list[dict[str, Any]]) -> None:
    """Отчёт «Продажи» как из 1С: шапка с периодом, клиенты группами, позиции с отступом."""
    month_names = (
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    )
    workbook = Workbook()
    sheet = _sheet(workbook)
    sheet["A1"] = "Отчёт «Продажи»"
    sheet["A1"].font = Font(bold=True, size=12)
    sheet["A2"] = f"Период: {month_names[month - 1]} {year} г."
    sheet["A3"] = "ООО «Импорт Трейдинг»"
    headers = (
        "Контрагент",
        "Номенклатура",
        "Количество",
        "Сумма продажи",
        "Сумма скидки",
    )
    for index, title in enumerate(headers, start=1):
        cell = sheet.cell(row=5, column=index, value=title)
        cell.font = Font(bold=True)

    row = 6
    for client in sorted({line["client"] for line in rows}):
        group = sheet.cell(row=row, column=1, value=client)
        group.font = Font(bold=True)
        row += 1
        for line in (item for item in rows if item["client"] == client):
            name = sheet.cell(row=row, column=1, value=line["product"])
            name.alignment = Alignment(indent=1)
            sheet.cell(row=row, column=2, value=line["product"])
            sheet.cell(row=row, column=3, value=float(line["quantity"]))
            sheet.cell(row=row, column=4, value=float(line["amount"]))
            sheet.cell(row=row, column=5, value=float(line["discount"]))
            row += 1

    total = sum(float(line["amount"]) for line in rows)
    sheet.cell(row=row + 1, column=1, value="Итог")
    sheet.cell(row=row + 1, column=4, value=round(total, 2))
    _widths(sheet, [46, 52, 14, 16, 14])
    workbook.save(path)


def write_receipts_file(path: Path, batches: list[dict[str, Any]]) -> None:
    """Выгрузка «Импортные поступления»: четыре нужные колонки и лишние, как в 1С."""
    workbook = Workbook()
    sheet = _sheet(workbook)
    headers = (
        " ",
        "УУ",
        "БУ",
        "НУ",
        "Дата",
        "Номер",
        "Вид операции",
        "Вид поступления",
        "Сумма",
        "Валюта",
        "Контрагент",
        "Оригинал получен",
        "Склад",
        "Организация",
        "Подразделение",
        "Ответственный",
        "Номер вход. документа",
        "Дата вход. документа",
        "Комментарий",
        "Состояние ЭДО",
    )
    for index, title in enumerate(headers, start=1):
        sheet.cell(row=1, column=index, value=title)
    for offset, batch in enumerate(batches, start=2):
        sheet.cell(row=offset, column=2, value="Да")
        sheet.cell(row=offset, column=3, value="Нет")
        sheet.cell(row=offset, column=4, value="Нет")
        sheet.cell(row=offset, column=5, value=batch["date"])
        sheet.cell(row=offset, column=6, value=batch["number"])
        sheet.cell(row=offset, column=7, value="покупка, комиссия")
        sheet.cell(row=offset, column=8, value="На склад")
        sheet.cell(row=offset, column=9, value=float(batch["amount"]))
        sheet.cell(row=offset, column=10, value="USD")
        sheet.cell(row=offset, column=11, value=batch["supplier"])
        sheet.cell(row=offset, column=12, value="Нет Нет")
        sheet.cell(row=offset, column=13, value="Склад СТУПИНО NEW")
        sheet.cell(row=offset, column=14, value='ООО "Импорт Трейдинг"')
        sheet.cell(row=offset, column=15, value="Основное производство")
        sheet.cell(row=offset, column=16, value="Шахидул Ислам Съед")
        sheet.cell(row=offset, column=17, value=batch["invoice"])
        sheet.cell(row=offset, column=18, value=batch["invoice_date"])
        sheet.cell(row=offset, column=19, value=batch["comment"])
    _widths(
        sheet,
        [3, 6, 6, 6, 20, 16, 20, 16, 14, 8, 52, 14, 24, 24, 24, 24, 22, 18, 56, 14],
    )
    workbook.save(path)


def write_items_file(path: Path, raw: str, quantity: Decimal, price_usd: Decimal) -> None:
    """Выгрузка «Партия»: позиции одного поступления (как 1С отдаёт карточку)."""
    workbook = Workbook()
    sheet = _sheet(workbook)
    headers = (
        "№",
        "Количество",
        "Номенклатура",
        "Способ отражения расходов",
        "Серия ",
        "Ед.",
        "К.",
        "Цена",
        "Сумма",
        "% НДС",
        "Сумма НДС",
    )
    for index, title in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=index, value=title)
        cell.font = Font(bold=True)
    sheet.cell(row=2, column=1, value=1)
    sheet.cell(row=2, column=2, value=float(quantity))
    sheet.cell(row=2, column=3, value=raw)
    sheet.cell(row=2, column=6, value="кг")
    sheet.cell(row=2, column=7, value=1)
    sheet.cell(row=2, column=8, value=float(price_usd))
    sheet.cell(row=2, column=9, value=float((quantity * price_usd).quantize(Decimal("0.01"))))
    sheet.cell(row=2, column=10, value="22%")
    _widths(sheet, [5, 12, 46, 24, 30, 8, 6, 10, 14, 8, 12])
    workbook.save(path)


def cmd_files() -> None:
    """Сгенерировать выгрузки 1С по плану: продажи, поступления, партии."""
    MOCK.mkdir(parents=True, exist_ok=True)
    plan = month_quantities()
    prices = {product.finished: product.price_rub for product in PRODUCTS}

    def sales_rows(month: int, factors: tuple[Decimal, ...], extra: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        index = 0
        for (client, product, row_month), quantity in sorted(plan.items()):
            if row_month != month:
                continue
            factor = factors[(index * 7 + len(client) + len(product)) % len(factors)]
            index += 1
            sold = (quantity * factor).quantize(Decimal("0.001"))
            if sold <= 0:
                continue
            rows.append(
                {
                    "client": client,
                    "product": product,
                    "quantity": sold,
                    "amount": (sold * prices[product]).quantize(Decimal("0.01")),
                    "discount": Decimal("0"),
                }
            )
        # Продажи вне плана: клиент взял позицию, которой в его плане нет.
        clients = [client for names in MANAGERS.values() for client in names]
        candidates = [
            (client, product)
            for client in clients
            for product in PRODUCTS
            if (client, product.finished, month) not in plan
        ]
        start = (month * 5) % len(candidates)
        for offset, (client, product) in enumerate(candidates[start : start + extra]):
            quantity = (Decimal("80") + Decimal(offset * 37)).quantize(Decimal("0.001"))
            rows.append(
                {
                    "client": client,
                    "product": product.finished,
                    "quantity": quantity,
                    "amount": (quantity * prices[product.finished]).quantize(Decimal("0.01")),
                    "discount": Decimal("0"),
                }
            )
        # Возвраты: две-три строки с минусом, как в отчёте 1С.
        for offset in range(2):
            line = rows[(offset * 11 + month) % len(rows)]
            returned = (line["quantity"] * Decimal("0.08")).quantize(Decimal("0.001"))
            if returned <= 0:
                continue
            rows.append(
                {
                    "client": line["client"],
                    "product": line["product"],
                    "quantity": -returned,
                    "amount": (-returned * prices[line["product"]]).quantize(Decimal("0.01")),
                    "discount": Decimal("0"),
                }
            )
        return rows

    january = sales_rows(1, JAN_FACTORS, extra=6)
    # Позиции, которых нет в справочнике: две строки уходят в очередь сопоставления.
    january.append(
        {
            "client": next(iter(MANAGERS["sales"])),
            "product": "Орех макадамия сушеный, вес",
            "quantity": Decimal("120.000"),
            "amount": Decimal("168000.00"),
            "discount": Decimal("0"),
        }
    )
    january.append(
        {
            "client": next(iter(MANAGERS["sales2"])),
            "product": "Курага Тунис, вес",
            "quantity": Decimal("85.000"),
            "amount": Decimal("46750.00"),
            "discount": Decimal("0"),
        }
    )
    february = sales_rows(2, FEB_FACTORS, extra=4)
    write_sales_file(MOCK / "Продажи за Январь 2027.xlsx", 2027, 1, january)
    write_sales_file(MOCK / "Продажи за Февраль 2027.xlsx", 2027, 2, february)

    batches = build_batches()
    write_receipts_file(MOCK / "Импортные поступления 2027.xlsx", batches)
    # Две партии заводим файлом «Партия» — проверяем путь загрузки позиций.
    # Две партии с датами 2027 года: проверяем именно автоподхват при загрузке.
    file_batches = batches[1:3]
    for batch in file_batches:
        write_items_file(
            MOCK / f"Партия {batch['number']}.xlsx",
            batch["raw"],
            batch["quantity"],
            batch["price_usd"],
        )
    (MOCK / "batches.json").write_text(
        json.dumps(
            [
                {
                    "number": batch["number"],
                    "date": batch["date"],
                    "supplier": batch["supplier"],
                    "product_code": batch["raw_code"],
                    "raw": batch["raw"],
                    "quantity": str(batch["quantity"]),
                    "price_usd": str(batch["price_usd"]),
                    "duty": str(batch["duty"]),
                    "via_file": batch in file_batches,
                }
                for batch in batches
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"Файлы в {MOCK}: продажи январь ({len(january)} строк), "
        f"февраль ({len(february)}), поступления ({len(batches)}), "
        f"партии файлом: {len(file_batches)}"
    )


def build_batches() -> list[dict[str, Any]]:
    """Поставки под план января–марта: основное сырьё и альтернативы.

    У кешью и грецкого ореха в скорлупе основное сырьё закрыто на 55 % — так
    видно, как альтернатива подхватывает нехватку. У миндаля первый завоз
    сдвинут на февраль.
    """
    plan = month_quantities()
    main_need: dict[str, Decimal] = {}
    for product in PRODUCTS:
        total = sum(
            (
                quantity
                for (_client, name, month), quantity in plan.items()
                if name == product.finished and month <= 3
            ),
            Decimal("0"),
        )
        main_need[product.raw_code] = total * product.recipe

    main_coverage = {product.raw_code: Decimal("0.95") for product in PRODUCTS}
    main_coverage[PRODUCTS[1].raw_code] = Decimal("0.55")  # грецкий в скорлупе
    main_coverage[PRODUCTS[6].raw_code] = Decimal("0.55")  # кешью W320
    main_dates = (
        ("2026-12-11 10:20:00", "2026-12-11", Decimal("0.45")),
        ("2027-01-15 09:40:00", "2027-01-15", Decimal("0.35")),
        ("2027-02-12 11:05:00", "2027-02-12", Decimal("0.20")),
    )
    delayed_dates = (
        ("2027-02-05 12:00:00", "2027-02-05", Decimal("0.45")),
        ("2027-02-20 10:00:00", "2027-02-20", Decimal("0.35")),
        ("2027-03-10 09:30:00", "2027-03-10", Decimal("0.20")),
    )
    alternative_dates = (
        ("2027-02-10 10:00:00", "2027-02-10", Decimal("0.50")),
        ("2027-03-12 10:00:00", "2027-03-12", Decimal("0.30")),
        ("2027-04-05 10:00:00", "2027-04-05", Decimal("0.20")),
    )

    supplies: list[dict[str, Any]] = []
    for product in PRODUCTS:
        shipments = delayed_dates if product.raw_code == PRODUCTS[7].raw_code else main_dates
        supplies.append(
            {
                "raw": product.raw,
                "raw_code": product.raw_code,
                "supplier": product.supplier,
                "price_usd": product.price_usd,
                "duty": product.duty,
                "need": main_need[product.raw_code],
                "coverage": main_coverage[product.raw_code],
                "shipments": shipments,
            }
        )
    product_by_finished = {product.finished: product for product in PRODUCTS}
    for alternative in ALTERNATIVES:
        main = product_by_finished[alternative.main]
        supplies.append(
            {
                "raw": alternative.raw,
                "raw_code": alternative.raw_code,
                "supplier": alternative.supplier,
                "price_usd": alternative.price_usd,
                "duty": alternative.duty,
                "need": main_need[main.raw_code] * alternative.share,
                "coverage": Decimal("0.90"),
                "shipments": alternative_dates,
            }
        )

    batches: list[dict[str, Any]] = []
    number = 1
    for supply in supplies:
        for stamp, invoice_date, share in supply["shipments"]:
            quantity = (supply["need"] * supply["coverage"] * share).quantize(Decimal("0.001"))
            if quantity <= 0:
                continue
            batches.append(
                {
                    "number": f"ИТ-2027-{number:04d}",
                    "date": stamp,
                    "invoice_date": invoice_date,
                    "invoice": f"INV-2027-{number:03d}",
                    "supplier": supply["supplier"],
                    "raw": supply["raw"],
                    "raw_code": supply["raw_code"],
                    "price_usd": supply["price_usd"],
                    "duty": supply["duty"],
                    "quantity": quantity,
                    "amount": (quantity * supply["price_usd"]).quantize(Decimal("0.01")),
                    "comment": (f"{supply['raw']} {quantity:.0f} кг, инвойс INV-2027-{number:03d}"),
                }
            )
            number += 1
    return batches


# --- шаг 5: поступления -----------------------------------------------------------


def cmd_receipts() -> None:
    """Загрузить поступления файлом и заполнить строки ценами и привязкой к плану."""
    api = Api("import")
    batches_spec = json.loads((MOCK / "batches.json").read_text(encoding="utf-8"))
    api.upload("/imports/import_receipts", MOCK / "Импортные поступления 2027.xlsx")

    purchase = Api("purchase")
    plan_id = purchase.get("/purchase-plans", params={"year": 2027})[0]["id"]
    plan = purchase.get(f"/purchase-plans/{plan_id}")
    links = {row["product_id"]: row["id"] for row in plan["items"]}
    raw_ids = {row["code"]: row["id"] for row in purchase.get("/products")}

    existing = {row["batch_number"]: row for row in api.get("/batches")}
    filled = 0
    for spec in batches_spec:
        batch = existing.get(spec["number"])
        if batch is None:
            raise SystemExit(f"Поступления {spec['number']} нет после загрузки файла")
        if spec["via_file"]:
            # Путь «из файла»: строки приходят без цены и без привязки — как в жизни.
            file = MOCK / f"Партия {spec['number']}.xlsx"
            api.upload(f"/batches/{batch['id']}/import-items", file)
            continue
        api.put(
            f"/batches/{batch['id']}",
            json={
                "batch_number": batch["batch_number"],
                "batch_date": batch["batch_date"],
                "currency": "USD",
                "supplier_id": batch["supplier_id"],
                "current_exchange_rate": "79.5",
                "auto_rate": False,
                "comment": batch["comment"],
                "items": [
                    {
                        "product_code": spec["product_code"],
                        "product_name": spec["raw"],
                        "product_kind": "raw",
                        "unit": "кг",
                        "quantity": spec["quantity"],
                        "unit_price_currency": spec["price_usd"],
                        "duty_percent": str(spec["duty"]),
                        "vat_percent": "22",
                        "purchase_plan_item_id": links.get(raw_ids[spec["product_code"]]),
                    }
                ],
                "expenses": [],
                "payments": [],
            },
        )
        filled += 1
    print(f"Поступления: {len(batches_spec)}, заполнено ценами и планом — {filled}")


# --- шаг 6: причины отклонений -----------------------------------------------------

# Причина по позиции: так объяснения выглядят правдоподобно, а не «другое» везде.
REASON_BY_RAW = {
    "Грецкий орех сушеный, вес": ("supply_late", "Контейнер из Шэньяна пришёл 22.01"),
    "Грецкий орех в скорлупе, вес": (
        "supply_late",
        "Задержка на таможне, выпуск 19.01",
    ),
    "Изюм Малаяр, вес": ("quality", "Отказ лаборатории: влажность выше нормы"),
    "Изюм светлый Голден, вес": (
        "client_refused",
        "Сеть сократила заказ перед праздниками",
    ),
    "Курага светлая № 1 вес": ("no_stock", "Остатка не хватило, ждали вторую машину"),
    "Финики БОН-БОН, вес": ("price", "Клиент просил скидку, отложили поставку"),
    "Кешью сушеный, W320, вес": (
        "supply_late",
        "Недопоставка 45% — контейнер ушёл на февраль",
    ),
    "Миндаль сушеный, 23-25, вес": (
        "supply_late",
        "Первая поставка перенесена на февраль",
    ),
}


def cmd_reasons(year: int = 2027, month: int = 1) -> None:
    """Проставить причины недоборам: каждый менеджер по своим клиентам.

    Заодно проверяется право: чужой клиент — отказ 403.
    """
    total = 0
    for login in MANAGERS:
        api = Api(login)
        result = api.get("/month-results", params={"year": year, "month": month})
        rows = [row for row in result["rows"] if row["group"] != "extra"]
        rows = [row for row in rows if Decimal(row["deviation"]) < 0 and not row["reason"]]
        for row in rows:
            code, comment = _reason_for(row["product_name"])
            api.put(
                f"/month-results/{year}/{month}/reasons",
                json={
                    "client_id": row["client_id"],
                    "product_id": row["product_id"],
                    "reason": code,
                    "comment": comment,
                },
            )
            total += 1
        print(f"{login}: причин поставлено {len(rows)}")

    # Чужой клиент: коммерческий директор ставит причину всем, менеджер — только своим.
    commercial = Api("commercial")
    sales3_id = users_by_login(commercial)["sales3"]
    foreign = next(
        row
        for row in commercial.get("/month-results", params={"year": year, "month": month})["rows"]
        if row["manager_id"] and row["manager_id"] != sales3_id and row["group"] != "extra"
    )
    outsider = Api("sales3")
    response = outsider.client.put(
        f"/month-results/{year}/{month}/reasons",
        json={
            "client_id": foreign["client_id"],
            "product_id": foreign["product_id"],
            "reason": "other",
            "comment": "проверка",
        },
    )
    print(f"чужой клиент для sales3 → {response.status_code} (строка скрыта: 403 или 404)")
    print(f"Всего причин поставлено: {total}")


def _reason_for(product_name: str) -> tuple[str, str | None]:
    for raw, value in REASON_BY_RAW.items():
        if raw.casefold() in product_name.casefold():
            return value
    return ("other", "Причина уточняется у менеджера")


# --- точка входа ------------------------------------------------------------------


def main(argv: list[str]) -> None:
    commands = {
        "reset": cmd_reset,
        "clients": cmd_clients,
        "plans": cmd_plans,
        "files": cmd_files,
        "receipts": cmd_receipts,
        "reasons": cmd_reasons,
    }
    if len(argv) < 2 or (argv[1] != "all" and argv[1] not in commands):
        print(__doc__)
        raise SystemExit(2)
    steps = ["reset", "clients", "plans", "files", "receipts"] if argv[1] == "all" else [argv[1]]
    for name in steps:
        print(f"\n=== {name} ===")
        commands[name]()


if __name__ == "__main__":
    main(sys.argv)
