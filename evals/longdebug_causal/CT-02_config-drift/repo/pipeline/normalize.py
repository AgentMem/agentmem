def clean_city(name: str) -> str:
    return name


def clean_country(name: str) -> str:
    return name


def normalize(records):
    return [
        {"city": clean_city(r["city"]), "country": clean_country(r["country"])} for r in records
    ]
