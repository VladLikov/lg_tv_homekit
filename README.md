# LG TV HomeKit Backlight — 0.2.0

Один штатный Home Assistant HomeKit Television accessory с linked Lightbulb `Backlight`.
Компонент расширяет в памяти `TelevisionMediaPlayer` только для выбранной TV entity.
Core-файлы, HomeKit server, pairing и идентификаторы аксессуара остаются под управлением HA.
Это внутренний API HA: совместимость подтверждается для конкретных релизов, а не обещается для всех будущих версий.

## Совместимость

Матрица: HA 2026.8.3 и 2026.9.1, HAP-python 5.0.0, Python 3.14.
Перед изменением реестра проверяются версия и сигнатуры переопределяемых методов.
Поведенческие тесты проверяют настоящие HA/PyHAP объекты, linked services, IID,
питание, очередь яркости и Inputs. Итоги и ограничения — в `VALIDATION.md`.
При неподдерживаемой версии компонент откажется загружаться; штатный HomeKit может
запуститься без Backlight. Поэтому перед обновлением HA проверяйте матрицу и имейте backup.

## Установка через HACS после публикации

Добавьте URL этого репозитория в HACS → Custom repositories → Integration,
скачайте релиз и полностью перезапустите HA после добавления YAML.
Обычный Add integration не нужен: настройка через YAML.

```yaml
lg_tv_homekit:
  tv_entity_id: media_player.tv
  backlight_entity_id: number.tv_backlight
```

Используйте фактические существующие entity IDs. TV должен иметь `device_class: tv`,
а number — диапазон 0–100. Нужен один существующий HomeKit exporter TV в режиме Accessory.
Не создавайте второй exporter поверх настроенного через UI и не удаляйте общий мост.
`configuration.example.yaml` содержит только настройку расширения.

Для ручной установки распакуйте release ZIP в `/config/custom_components/lg_tv_homekit/`.
В корне ZIP находятся файлы компонента, без дополнительной папки. `/config` — путь внутри HA.

## Поведение

- Питание TV управляется штатным media_player.
- Backlight 0–100 записывает `number.set_value`, только когда TV включён и number корректен.
- Backlight Off устанавливает 0, не выключая телевизор; On без яркости ничего не делает.
- On/Off Backlight следует питанию TV даже при яркости 0.
- При выключенном TV отображается Off/0; команды яркости не будят TV и не откладываются.
- HA остаётся источником состояния; недоступная number блокирует запись и выставляет StatusFault.

## Inputs

По умолчанию сохраняются все источники. Не меняйте существующий режим при миграции.
При необходимости `show_inputs: false` убирает InputSource services только у этого TV.
Либо задайте `include_sources: [Apple, PS5]` с точными именами HA.
Горизонтальную раскладку определяет Apple Home; на iPhone она не подтверждена.

## Обновление и проверка

Сначала сохраните backup конфигурации, файлов компонента и штатного состояния HA.
Обновите компонент, выполните Check configuration и полный restart HA.
Проверьте существующий аксессуар: питание, Backlight 30 → Off → 60, Inputs,
изменение number из HA и отсутствие пробуждения от Backlight при выключенном TV.
Не удаляйте pairing при проблеме отображения: остановитесь и выполните откат.

## Разработка

В изолированной Python 3.14 среде:

```sh
python -m pip install homeassistant==2026.9.1 -r requirements-test.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python -m pytest -p pytest_asyncio.plugin tests -q
python scripts/package.py
```

Повторите suite на HA 2026.8.3 в отдельной среде. GitHub Actions проверяет обе версии.
HACS/hassfest workflows выполняются после публикации; их удалённый результат не имитируется локальными тестами.
Упаковка создаёт `dist/lg_tv_homekit.zip` и SHA-256. Workflow только собирает артефакт;
создание GitHub Release остаётся ручным шагом.
