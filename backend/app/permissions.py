"""Права доступа: уровни, блоки и матрица по умолчанию.

Уровни доступа — шесть фиксированных бизнес-ролей. Администратор — отдельная
седьмая роль, единственная в системе, у неё всегда полный доступ. Матрица ниже —
это ровно то, как приложение работало до появления конструктора; админ может
переопределить любой блок, и переопределения лягут в ``role_permissions``.

Три сущности:

* ``BLOCKS`` — что вообще можно разрешать: раздел и действия внутри него.
* ``DEFAULTS`` — стартовые права каждого уровня.
* ``Rights`` — итоговый набор действий и охват (``own`` — только свои строки,
  ``all`` — все). Итог собирает ``app.services.access_service``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.auth import (
    ROLE_ADMIN,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_ASSISTANT,
    ROLE_SALES_MANAGER,
    ROLES,
    User,
)


@dataclass(frozen=True)
class ActionSpec:
    """Действие внутри блока: ключ и подпись для конструктора."""

    key: str
    title: str


@dataclass(frozen=True)
class BlockSpec:
    """Блок прав: раздел приложения, который админ включает уровням."""

    key: str
    title: str
    actions: tuple[ActionSpec, ...]
    group: str
    scoped: bool = False


def _a(key: str, title: str) -> ActionSpec:
    return ActionSpec(key, title)


VIEW = _a("view", "Смотреть")
EDIT = _a("edit", "Создавать и править")
DELETE = _a("delete", "Удалять")
APPROVE = _a("approve", "Утверждать")

BLOCKS: tuple[BlockSpec, ...] = (
    BlockSpec(
        "sales_plans",
        "Планирование продаж",
        (
            VIEW,
            EDIT,
            _a("submit", "Отправлять на проверку"),
            APPROVE,
            _a("dispatch", "Отдавать на заполнение"),
            DELETE,
        ),
        "planning",
        scoped=True,
    ),
    BlockSpec(
        "corrections",
        "Корректировки плана продаж",
        (VIEW, _a("propose", "Предлагать корректировку"), APPROVE),
        "planning",
        scoped=True,
    ),
    BlockSpec(
        "annual_plan",
        "Годовой план отдела",
        (VIEW, _a("submit", "Отправлять на согласование"), APPROVE),
        "planning",
    ),
    BlockSpec(
        "monthly_plan",
        "Помесячный план продаж",
        (VIEW, EDIT, APPROVE),
        "planning",
        scoped=True,
    ),
    BlockSpec(
        "purchase_plan",
        "План закупок сырья",
        (VIEW, EDIT, APPROVE, DELETE),
        "purchases",
    ),
    BlockSpec(
        "receipts",
        "Поступления и партии",
        (VIEW, EDIT, DELETE, _a("customs", "Растаможка")),
        "purchases",
    ),
    BlockSpec(
        "directories",
        "Номенклатура и контрагенты",
        (VIEW, EDIT),
        "catalogs",
    ),
    BlockSpec("countries", "Страны и сроки доставки", (VIEW, EDIT), "catalogs"),
    BlockSpec("stock", "Остатки по партиям", (VIEW,), "reports"),
    BlockSpec(
        "month_results",
        "Итоги месяца",
        (
            VIEW,
            _a("match", "Сопоставлять продажи"),
            _a("reasons", "Ставить причины"),
            _a("close", "Закрывать месяц"),
            _a("history", "Смотреть историю"),
        ),
        "reports",
        scoped=True,
    ),
    BlockSpec("plan_fact", "План и факт", (VIEW,), "reports", scoped=True),
    BlockSpec(
        "tasks",
        "Задачи",
        (VIEW, _a("create", "Ставить задачи"), _a("manage", "Управлять чужими задачами")),
        "tasks",
        scoped=True,
    ),
    BlockSpec(
        "imports",
        "Загрузка данных 1С",
        (
            VIEW,
            _a("local_suppliers", "Локальные поставщики"),
            _a("import_suppliers", "Импортные поставщики"),
            _a("customers", "Покупатели"),
            _a("nomenclature", "Номенклатура"),
            _a("import_receipts", "Импортные поступления"),
            _a("batch_items", "Позиции партии"),
            _a("sales", "Продажи за месяц"),
        ),
        "admin",
    ),
    BlockSpec("rates", "Курсы валют", (VIEW, _a("refresh", "Обновлять из ЦБ")), "catalogs"),
    BlockSpec(
        "journal",
        "Журнал действий",
        (VIEW, _a("cleanup", "Очищать журнал")),
        "admin",
        scoped=True,
    ),
    BlockSpec("users", "Список сотрудников", (VIEW,), "admin"),
)

BLOCK_BY_KEY: dict[str, BlockSpec] = {block.key: block for block in BLOCKS}

LEVEL_DESCRIPTIONS: dict[str, str] = {
    ROLE_SALES_MANAGER: "Свои клиенты и планы продаж, свои строки итогов месяца, задачи.",
    ROLE_SALES_ASSISTANT: "Справочники и задачи отдела продаж; планы и отчёты не правит.",
    ROLE_COMMERCIAL_DIRECTOR: (
        "Весь коммерческий блок: планы продаж, корректировки, годовой и помесячный план, "
        "итоги месяца, задачи и справочники."
    ),
    ROLE_PURCHASE_DIRECTOR: (
        "Закупки, поступления и растаможка, страны и справочники, история итогов месяца."
    ),
    ROLE_IMPORT_MANAGER: "План закупок, поступления и импортные выгрузки; продажи — только чтение.",
    ROLE_EXECUTIVE_DIRECTOR: "Обзор всех разделов и согласования верхнего уровня.",
}


@dataclass(frozen=True)
class Rights:
    """Итоговые права на блок."""

    actions: frozenset[str]
    scope: str = "all"


def _r(actions: str, scope: str = "all") -> Rights:
    return Rights(frozenset(actions.split()), scope)


# Стартовая матрица: ровно текущее поведение приложения.
DEFAULTS: dict[str, dict[str, Rights]] = {
    ROLE_SALES_MANAGER: {
        "sales_plans": _r("view edit submit delete", "own"),
        "corrections": _r("view propose", "own"),
        "annual_plan": _r("view"),
        "monthly_plan": _r("view edit", "own"),
        "receipts": _r("view"),
        "month_results": _r("view reasons", "own"),
        "plan_fact": _r("view", "own"),
        "directories": _r("view edit"),
        "countries": _r("view"),
        "stock": _r("view"),
        "tasks": _r("view", "own"),
        "imports": _r("view local_suppliers import_suppliers customers nomenclature"),
        "rates": _r("view"),
        "journal": _r("view", "own"),
    },
    ROLE_SALES_ASSISTANT: {
        "directories": _r("view"),
        "countries": _r("view"),
        "stock": _r("view"),
        "receipts": _r("view"),
        "tasks": _r("view", "own"),
        "imports": _r("view"),
        "rates": _r("view"),
        "journal": _r("view", "own"),
    },
    ROLE_COMMERCIAL_DIRECTOR: {
        "sales_plans": _r("view edit approve dispatch delete"),
        "corrections": _r("view propose approve"),
        "annual_plan": _r("view submit"),
        "monthly_plan": _r("view edit approve"),
        "month_results": _r("view match reasons close history"),
        "plan_fact": _r("view"),
        "receipts": _r("view"),
        "directories": _r("view edit"),
        "countries": _r("view"),
        "stock": _r("view"),
        "tasks": _r("view create manage"),
        "imports": _r("view local_suppliers import_suppliers customers nomenclature sales"),
        "rates": _r("view"),
        "journal": _r("view"),
        "users": _r("view"),
    },
    ROLE_PURCHASE_DIRECTOR: {
        "sales_plans": _r("view"),
        "annual_plan": _r("view"),
        "purchase_plan": _r("view edit delete"),
        "receipts": _r("view edit delete customs"),
        "directories": _r("view edit"),
        "countries": _r("view edit"),
        "stock": _r("view"),
        "month_results": _r("view history"),
        "plan_fact": _r("view"),
        "imports": _r(
            "view local_suppliers import_suppliers customers nomenclature "
            "import_receipts batch_items"
        ),
        "rates": _r("view refresh"),
        "journal": _r("view", "own"),
    },
    ROLE_IMPORT_MANAGER: {
        "sales_plans": _r("view"),
        "purchase_plan": _r("view edit"),
        "receipts": _r("view edit delete"),
        "directories": _r("view"),
        "countries": _r("view"),
        "stock": _r("view"),
        "imports": _r("view import_receipts batch_items"),
        "rates": _r("view refresh"),
        "journal": _r("view", "own"),
    },
    ROLE_EXECUTIVE_DIRECTOR: {
        "sales_plans": _r("view edit submit approve dispatch delete"),
        "corrections": _r("view propose approve"),
        "annual_plan": _r("view submit approve"),
        "monthly_plan": _r("view edit approve"),
        "purchase_plan": _r("view edit approve delete"),
        "receipts": _r("view edit delete customs"),
        "directories": _r("view edit"),
        "countries": _r("view edit"),
        "stock": _r("view"),
        "month_results": _r("view match reasons close history"),
        "plan_fact": _r("view"),
        "tasks": _r("view create manage"),
        "imports": _r(
            "view local_suppliers import_suppliers customers nomenclature "
            "import_receipts batch_items sales"
        ),
        "rates": _r("view refresh"),
        "journal": _r("view cleanup"),
        "users": _r("view"),
    },
}

# Единственный администратор видит и может всё.
ADMIN_RIGHTS: dict[str, Rights] = {
    block.key: Rights(frozenset(action.key for action in block.actions)) for block in BLOCKS
}


def defaults_for(role: str) -> dict[str, Rights]:
    """Стартовые права уровня; для админа — полный доступ."""
    if role == ROLE_ADMIN:
        return ADMIN_RIGHTS
    return DEFAULTS.get(role, {})


def _rights_of(user: User) -> dict[str, Rights]:
    profile = getattr(user, "access_profile", None)
    if isinstance(profile, dict):
        return profile
    return defaults_for(user.role)


def can(user: User, block: str, action: str) -> bool:
    """Может ли пользователь выполнить действие в блоке."""
    if user.role == ROLE_ADMIN:
        return True
    rights = _rights_of(user).get(block)
    return rights is not None and action in rights.actions


def scope_of(user: User, block: str) -> str:
    """Охват данных: own — только свои строки, all — все."""
    if user.role == ROLE_ADMIN:
        return "all"
    rights = _rights_of(user).get(block)
    return rights.scope if rights is not None else "own"


def level_keys() -> tuple[str, ...]:
    """Уровни, которые видит конструктор: шесть бизнес-ролей без админа."""
    return ROLES
