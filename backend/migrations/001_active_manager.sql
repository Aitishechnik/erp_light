-- «Активный менеджер»: личный статус вместо проверки должности.
-- Существующие менеджеры по продажам получают признак автоматически,
-- чтобы после обновления их клиенты и планы остались на месте.
alter table users add column if not exists is_manager boolean not null default false;

update users set is_manager = true where role = 'sales_manager';
