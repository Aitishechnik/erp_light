-- Позиции будущих периодов: планируем номенклатуру, которой ещё нет в 1С.
-- Карточка живёт в products с признаком is_future и служебным кодом БУД-…;
-- после привязки к реальной позиции её ссылки переносятся, а карточка удаляется.
ALTER TABLE products ADD COLUMN IF NOT EXISTS is_future boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS ix_products_is_future ON products (is_future);
