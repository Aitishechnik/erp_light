-- Состав черновика годового плана продаж: клиенты и позиции, добавленные
-- в форму до заполнения количеств. Хранится отдельно от sales_plan_items,
-- чтобы пустые строки не попадали в утверждённые объёмы.
ALTER TABLE sales_plans ADD COLUMN IF NOT EXISTS draft_clients json;
ALTER TABLE sales_plans ADD COLUMN IF NOT EXISTS draft_rows json;
