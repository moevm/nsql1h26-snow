import os

from neo4j import GraphDatabase

URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER     = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def seed(session):
    session.run("MATCH (n:HelloWorld) DETACH DELETE n")

    session.run(
        """
        CREATE
          (p:HelloWorld:Parking       {name: 'Стоянка №1',              lat: 59.9343, lon: 30.3351}),
          (s:HelloWorld:SnowMelt      {name: 'Снегоплавильный полигон', lat: 59.9500, lon: 30.3200}),
          (m:HelloWorld:ServiceStation{name: 'Станция ТО',              lat: 59.9200, lon: 30.3600}),
          (t:HelloWorld:Truck         {name: 'КДМ-1', model: 'КО-713',  fuel: 100}),

          (t)-[:PARKED_AT  {since: '2026-02-24'}]->(p),
          (t)-[:ROUTE_TO   {distance_km: 3.7}   ]->(s),
          (t)-[:ROUTE_TO   {distance_km: 2.1}   ]->(m)
        """
    )
    print("Данные записаны\n")


def read(session):
    print("\nПрочитанные данные:\n")
    print("Объекты на карте")
    result = session.run(
        "MATCH (n:HelloWorld) RETURN labels(n) AS labels, n.name AS name, "
        "n.lat AS lat, n.lon AS lon"
    )
    for r in result:
        label = [l for l in r["labels"] if l != "HelloWorld"][0]
        coords = f"({r['lat']}, {r['lon']})" if r["lat"] else ""
        print(f"  [{label:>16}]  {r['name']}  {coords}")

    print("\nМаршруты техники")
    result = session.run(
        """
        MATCH (t:HelloWorld:Truck)-[r:ROUTE_TO]->(dest:HelloWorld)
        RETURN t.name AS truck, dest.name AS destination, r.distance_km AS km
        """
    )
    for r in result:
        print(f"  {r['truck']}  →  {r['destination']}  ({r['km']} км)")

    print("\nМесто стоянки")
    result = session.run(
        """
        MATCH (t:HelloWorld:Truck)-[:PARKED_AT]->(p:HelloWorld:Parking)
        RETURN t.name AS truck, p.name AS parking
        """
    )
    for r in result:
        print(f"  {r['truck']} стоит на: {r['parking']}")


def cleanup(session):
    session.run("MATCH (n:HelloWorld) DETACH DELETE n")
    print("\nТестовые данные удалены")


def main():
    print("Подключение к Neo4j...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    driver.verify_connectivity()
    print(f"Подключено: {URI}\n")

    with driver.session() as session:
        seed(session)
        read(session)
        cleanup(session)

    driver.close()
    print("Готово.")


if __name__ == "__main__":
    main()
