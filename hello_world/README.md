# Hello World — Python + Neo4j

Минимальный пример подключения к Neo4j.  
Создаёт узлы (стоянки, снегоплавильные полигоны, ТО, техника) и связи между ними, затем читает их обратно.

### Docker Compose

Чтобы контейнеры автоматически завершались и были удалены вместе с томами, можно
выполнить:

```bash
cd hello_world
docker compose up --build --abort-on-container-exit --exit-code-from hello \
  && docker compose down -v
```

В результате после завершения скрипта будут удалены все контейнеры и тома.

Либо просто запустить run.sh

## Ожидаемый вывод

```
snow-hello  | Подключение к Neo4j...
snow-hello  | Подключено: bolt://neo4j:7687
snow-hello  | 
snow-hello  | Данные записаны
snow-hello  | 
snow-hello  | 
snow-hello  | Прочитанные данные:
snow-hello  | 
snow-hello  | === Объекты на карте ===
snow-hello  |   [         Parking]  Стоянка №1  (59.9343, 30.3351)
snow-hello  |   [        SnowMelt]  Снегоплавильный полигон  (59.95, 30.32)
snow-hello  |   [  ServiceStation]  Станция ТО  (59.92, 30.36)
snow-hello  |   [           Truck]  КДМ-1  
snow-hello  | 
snow-hello  | === Маршруты техники ===
snow-hello  |   КДМ-1  →  Снегоплавильный полигон  (3.7 км)
snow-hello  |   КДМ-1  →  Станция ТО  (2.1 км)
snow-hello  | 
snow-hello  | === Место стоянки ===
snow-hello  |   КДМ-1 стоит на: Стоянка №1
snow-hello  | 
snow-hello  | Тестовые данные удалены
snow-hello  | Готово.
```
